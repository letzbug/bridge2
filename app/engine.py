"""Asynchronous conversation engine.

The engine is a step machine. At any time there is exactly one *pending step*:

    SendStep     submit one message to one participant (never two at once)
    AwaitStep    wait for that participant's completed response
    ConfirmStep  show a response to the operator (edit / send / skip / copy)
    VerifyStep   the submission could not be confirmed -> the operator decides

Pausing, human intervention, issues (timeouts, loops, rate limits) and errors
are *holds*: the run loop parks before the next step and the pending step is
kept, so resuming never resends a message. After a timeout, "resume" simply
continues waiting with the original baseline.

The engine is Qt-independent and fully testable with fake adapters.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from adapters.base import BaseProviderAdapter, ResponseResult
from adapters.errors import (
    AdapterError, AuthenticationRequiredError, BrowserClosedError, CapabilityNotSupportedError,
    MessageTooLongError, ParticipantBusyError, RateLimitedError, ResponseTimeoutError, SubmissionBlockedError,
)
from research.transcript import (
    EntryKind, Provenance, SessionMeta, Transcript, TranscriptEntry, fact, now_iso,
)

from .events import EventBus, EventType
from .gate import SendGate
from .loop_detection import HistoryItem, LoopDetector
from .state_machine import ACTIVE_STATES, ConversationState, InvalidTransition, StateMachine
from .templates import (
    ATTRIBUTED_TEMPLATE, DEFAULT_HUMAN_TEMPLATE, DEFAULT_INITIAL_PROMPT, RAW_TEMPLATE,
    render_prompt, render_transfer,
)

log = logging.getLogger(__name__)
S = ConversationState


class Role(str, Enum):
    HOST = "host"
    GUEST = "guest"

    @property
    def other(self) -> "Role":
        return Role.GUEST if self is Role.HOST else Role.HOST


class TransferMode(str, Enum):
    MANUAL = "manual"
    AUTOMATIC = "automatic"
    CLIPBOARD = "clipboard"


@dataclass
class Participant:
    role: Role
    name: str
    provider_label: str
    adapter: BaseProviderAdapter
    provider_id: str = ""
    model_name: str = ""          # user-reported


@dataclass
class ConversationConfig:
    session_name: str = "Untitled session"
    topic: str = ""
    research_question: str = ""
    initial_prompt: str = DEFAULT_INITIAL_PROMPT
    first_speaker: Role = Role.HOST
    max_rounds: int = 10
    delay_seconds: float = 0.0
    max_wait_seconds: float = 180.0
    transfer_mode: TransferMode = TransferMode.MANUAL
    attribution: bool = True
    transfer_template: str = ATTRIBUTED_TEMPLATE
    human_template: str = DEFAULT_HUMAN_TEMPLATE
    human_name: str = "Human researcher"
    record_transcript: bool = True
    max_message_chars: int = 20000
    min_interval_seconds: float = 2.0
    max_messages_per_hour: int = 60
    near_duplicate_threshold: float = 0.85
    demo: bool = False
    notes: str = ""
    experiment: str = ""
    condition: str = ""
    user_reported: dict[str, str] = field(default_factory=dict)

    def normalized(self) -> "ConversationConfig":
        self.max_rounds = max(1, min(int(self.max_rounds), 1000))
        self.delay_seconds = max(0.0, min(float(self.delay_seconds), 600.0))
        self.max_wait_seconds = max(1.0, min(float(self.max_wait_seconds), 7200.0))
        self.max_message_chars = max(500, int(self.max_message_chars))
        self.min_interval_seconds = max(0.0, float(self.min_interval_seconds))
        self.max_messages_per_hour = max(0, int(self.max_messages_per_hour))
        if not isinstance(self.first_speaker, Role):
            self.first_speaker = Role(self.first_speaker)
        if not isinstance(self.transfer_mode, TransferMode):
            self.transfer_mode = TransferMode(self.transfer_mode)
        return self


# --- steps ------------------------------------------------------------------------

@dataclass
class SendStep:
    target: Role
    text: str
    source_turn: int | None
    kind: str = "transfer"        # transfer | initial | human
    apply_delay: bool = True
    edited: bool = False
    after: str = "normal"


@dataclass
class AwaitStep:
    target: Role
    after: str = "normal"         # normal | human | both_first | both_second


@dataclass
class Alternative:
    source_turn: int
    source_name: str
    destination: Role
    destination_name: str
    text: str
    original: str


@dataclass
class ConfirmStep:
    alternatives: list[Alternative]
    warnings: list[str] = field(default_factory=list)
    reason: str = "manual"


@dataclass
class VerifyStep:
    target: Role
    text: str
    source_turn: int | None
    kind: str = "transfer"
    after: str = "normal"


Step = SendStep | AwaitStep | ConfirmStep | VerifyStep

HOLD_PAUSE = "pause"
HOLD_HUMAN = "human"
HOLD_ISSUE = "issue"
HOLD_ERROR = "error"


class ConversationEngine:
    def __init__(self, host: Participant, guest: Participant, config: ConversationConfig,
                 bus: EventBus | None = None, gate: SendGate | None = None,
                 loop_detector: LoopDetector | None = None, clock=time.monotonic) -> None:
        self.participants: dict[Role, Participant] = {Role.HOST: host, Role.GUEST: guest}
        self.config = config.normalized()
        self.bus = bus or EventBus()
        self.gate = gate or SendGate()
        self.detector = loop_detector or LoopDetector(near_threshold=self.config.near_duplicate_threshold)
        self.clock = clock
        self.sm = StateMachine(on_change=self._on_state_change)
        self.transcript = Transcript(meta=self._build_meta())
        for p in self.participants.values():
            p.adapter.bind_gate(self.gate)

        self._loop: asyncio.AbstractEventLoop | None = None
        self._run_task: asyncio.Task | None = None
        self._step_task: asyncio.Future | None = None
        self._human_task: asyncio.Task | None = None
        self._phase: str | None = None
        self._next_step: Step | None = None
        self._hold: str | None = None
        self._hold_detail: dict[str, Any] | None = None
        self._pause_after_human = False
        self._step_once = False
        self._stopped = False
        self._resume_event: asyncio.Event | None = None
        self._parked: asyncio.Event | None = None
        self._finished: asyncio.Event | None = None
        self._send_lock: asyncio.Lock | None = None
        self._human_lock: asyncio.Lock | None = None
        self._decision: asyncio.Future | None = None
        self._decision_kind: str | None = None
        self._underlying: ConversationState | None = None
        self._turn = 0
        self._response_counts = {Role.HOST: 0, Role.GUEST: 0}
        self._sent_at: dict[Role, float] = {}
        self._last_received: dict[Role, str | None] = {Role.HOST: None, Role.GUEST: None}
        self._send_history: dict[Role, deque[float]] = {Role.HOST: deque(), Role.GUEST: deque()}
        self._cancelled_generation: set[Role] = set()
        self._observed_roles: set[Role] = set()
        self._both_first_turn: int | None = None

    # =========================================================================
    # properties
    # =========================================================================
    @property
    def state(self) -> ConversationState:
        return self.sm.state

    @property
    def hold(self) -> str | None:
        return self._hold

    @property
    def pending_step(self) -> Step | None:
        return self._next_step

    @property
    def response_counts(self) -> dict[str, int]:
        return {r.value: c for r, c in self._response_counts.items()}

    @property
    def completed_rounds(self) -> int:
        return min(self._response_counts.values())

    def transcript_copy(self) -> Transcript:
        return self.transcript.snapshot()

    async def wait_finished(self, timeout: float | None = None) -> bool:
        if self._finished is None:
            return True
        try:
            await asyncio.wait_for(self._finished.wait(), timeout)
            return True
        except asyncio.TimeoutError:
            return False

    # =========================================================================
    # lifecycle
    # =========================================================================
    async def start(self) -> None:
        if self._run_task is not None:
            raise RuntimeError("engine already started")
        self._loop = asyncio.get_running_loop()
        self._resume_event = asyncio.Event()
        self._parked = asyncio.Event()
        self._finished = asyncio.Event()
        self._send_lock = asyncio.Lock()
        self._human_lock = asyncio.Lock()
        self.gate.arm()
        self._transition(S.CONNECTING, "start")
        self.bus.emit(EventType.SESSION_STARTED, meta=self.transcript.meta.as_dict())
        self._log(f"Session '{self.config.session_name}' started "
                  f"({self.config.transfer_mode.value} transfer, max {self.config.max_rounds} rounds)")

        problems = await self._check_participants(require_ready=True)
        for role in Role:
            await self._capture_observed(role, initial=True)

        first = self.config.first_speaker
        text = render_prompt(
            self.config.initial_prompt or DEFAULT_INITIAL_PROMPT,
            topic=self.config.topic, host=self.participants[Role.HOST].name,
            guest=self.participants[Role.GUEST].name, recipient=self.participants[first].name,
            other=self.participants[first.other].name,
        ).strip()
        entry = self._add_entry(TranscriptEntry(
            turn=self._next_turn(), round=1, kind=EntryKind.INITIAL_PROMPT, speaker_role="operator",
            speaker_name="Operator (initial prompt)", provider="—", timestamp=now_iso(),
            original_text=text, destination=first.value, destination_name=self.participants[first].name,
            transfer_status="pending"))
        self._next_step = SendStep(first, text, entry.turn, kind="initial", apply_delay=False)
        self._emit_round()

        if problems:
            self._enter_error("not_ready", "Not ready: " + "; ".join(problems) +
                              ". Fix it in the browser window(s), then press Resume.")
        else:
            self._transition(S.READY, "participants ready")
        self._run_task = asyncio.ensure_future(self._run())

    async def stop(self, reason: str = "Stopped by operator", emergency: bool = False) -> None:
        if self._stopped:
            return
        if self.sm.is_terminal:
            self._stopped = True
            if emergency:
                self.gate.disarm("emergency stop")
            return
        self._stopped = True
        if emergency:
            self.gate.disarm("emergency stop")
        self._hold = None
        current = asyncio.current_task()
        for task in (self._step_task, self._human_task):
            if task is not None and not task.done() and task is not current:
                task.cancel()
        if self._decision is not None and not self._decision.done():
            self._decision.cancel()
        if self._resume_event is not None:
            self._resume_event.set()
        self.transcript.add_event("error" if emergency else "info",
                                  "emergency_stop" if emergency else "stopped", reason)
        self.bus.emit(EventType.CONFIRMATION_CLEARED)
        self.bus.emit(EventType.HUMAN, status="closed")
        self.bus.emit(EventType.ISSUE_CLEARED)
        self.sm.force_stop(reason)
        self._log(reason, "error" if emergency else "info")
        self._end_session(S.STOPPED.value, reason)
        if self._run_task is not None and self._run_task is not current:
            await asyncio.wait({self._run_task}, timeout=5)

    async def emergency_stop(self) -> None:
        self.gate.disarm("emergency stop")
        await self.stop("EMERGENCY STOP – all pending transfers cancelled, automated submissions blocked",
                        emergency=True)

    def emergency_stop_threadsafe(self) -> None:
        """Callable from ANY thread (GUI). Closes the send gate synchronously first."""
        self.gate.disarm("emergency stop")
        loop = self._loop
        if loop is not None and not loop.is_closed():
            asyncio.run_coroutine_threadsafe(self.emergency_stop(), loop)

    # =========================================================================
    # operator controls (call in the engine loop thread)
    # =========================================================================
    def pause(self) -> None:
        if not self._controllable():
            return
        if self._hold == HOLD_HUMAN:
            self._pause_after_human = True
            return
        if self._hold in (HOLD_ERROR, HOLD_ISSUE, HOLD_PAUSE):
            return
        self._hold = HOLD_PAUSE
        self._step_once = False
        self._interrupt(for_human=False)
        self._transition(S.PAUSED, "paused by operator")
        detail = ""
        if self._phase == "await" and isinstance(self._next_step, AwaitStep):
            name = self.participants[self._next_step.target].name
            detail = f" – still receiving {name}'s current response, it will be recorded but not forwarded"
        self._log("Paused by operator" + detail)

    async def resume(self) -> None:
        if not self._controllable() or self._hold is None:
            return
        if self._hold == HOLD_HUMAN:
            self.resume_previous()
            return
        if self._hold == HOLD_ERROR:
            problems = await self._check_participants(require_ready=False)
            if problems:
                self._enter_error("still_unavailable", "Still unavailable: " + "; ".join(problems))
                return
            self._log("Participants reachable again – resuming")
        self._clear_hold()

    async def next_turn(self) -> None:
        """Manual stepping: send the pending confirmation as-is, or resume for exactly one turn."""
        if self._decision_kind == "confirm" and self.state == S.WAITING_FOR_CONFIRMATION:
            self.confirm(None)
            return
        if self._hold in (HOLD_PAUSE, HOLD_ISSUE):
            self._step_once = True
            await self.resume()

    def confirm(self, text: str | None = None, alternative: int = 0) -> bool:
        if self._decision_kind != "confirm" or self._decision is None or self._decision.done():
            return False
        self._decision.set_result(("send", (alternative, text)))
        return True

    def skip(self) -> bool:
        if self._decision_kind != "confirm" or self._decision is None or self._decision.done():
            return False
        self._decision.set_result(("skip", None))
        return True

    def resolve_verification(self, submitted: bool) -> bool:
        if self._decision_kind != "verify" or self._decision is None or self._decision.done():
            return False
        self._decision.set_result(("submitted" if submitted else "not_submitted", None))
        return True

    def begin_human_intervention(self) -> bool:
        if not self._controllable():
            return False
        if self._hold == HOLD_HUMAN:
            return True
        if self._decision_kind == "verify":
            self.bus.emit(EventType.HUMAN, status="blocked",
                          detail="Resolve the pending submission check first (was the message submitted?).")
            return False
        self._hold = HOLD_HUMAN
        self._pause_after_human = False
        self._step_once = False
        self._interrupt(for_human=True)
        self._transition(S.HUMAN_INTERVENTION, "human intervention")
        self.bus.emit(EventType.HUMAN, status="open", pending=self._describe_pending())
        self._log("Human intervention – automatic forwarding paused")
        return True

    def resume_previous(self) -> None:
        if self._hold != HOLD_HUMAN:
            return
        self.bus.emit(EventType.HUMAN, status="closed")
        self._log("Resuming previous conversation")
        if self._pause_after_human:
            self._hold = HOLD_PAUSE
            self._transition(S.PAUSED, "paused after human intervention")
        else:
            self._hold = None
        self._resume_event.set()  # type: ignore[union-attr]

    async def human_send(self, target: str, text: str) -> bool:
        """Send an operator message to 'host', 'guest' or 'both' (sequentially, never simultaneously)."""
        text = (text or "").strip()
        if not text or self._stopped:
            return False
        if self._hold != HOLD_HUMAN and not self.begin_human_intervention():
            return False
        assert self._human_lock is not None and self._parked is not None
        if self._human_lock.locked():
            self._log("A human message is already being sent – please wait", "warning")
            return False
        async with self._human_lock:
            self._human_task = asyncio.current_task()
            try:
                await self._parked.wait()
                await self._human_send_locked(target, text)
                return True
            except SubmissionBlockedError:
                return False
            except asyncio.CancelledError:
                if self._stopped:
                    return False
                raise
            except Exception as exc:  # noqa: BLE001 - converted into an operator-visible hold
                self._handle_step_exception(self._next_step, exc)
                return False
            finally:
                self._phase = None
                self._human_task = None

    async def cancel_generation(self, role: str) -> bool:
        p = self.participants[Role(role)]
        try:
            ok = await p.adapter.stop_generation()
        except CapabilityNotSupportedError as exc:
            self._log(str(exc), "warning")
            return False
        except AdapterError as exc:
            self._log(f"Could not cancel generation for {p.name}: {exc}", "warning")
            return False
        if ok:
            self._cancelled_generation.add(p.role)
            self.transcript.add_event("info", "generation_cancelled", f"Operator cancelled {p.name}'s generation")
            self._log(f"Operator cancelled {p.name}'s generation")
        else:
            self._log(f"No active generation found for {p.name}", "warning")
        return ok

    # =========================================================================
    # run loop
    # =========================================================================
    async def _run(self) -> None:
        assert self._finished is not None
        try:
            while not self._stopped:
                if self._next_step is None:
                    self._complete("Round limit reached")
                    break
                await self._checkpoint()
                if self._stopped:
                    break
                if self._next_step is None:
                    continue
                step = self._next_step
                task = asyncio.ensure_future(self._execute(step))
                self._step_task = task
                try:
                    await asyncio.wait({task})
                except asyncio.CancelledError:
                    task.cancel()
                    with contextlib.suppress(BaseException):
                        await task
                    raise
                finally:
                    self._step_task = None
                if task.cancelled():
                    continue
                exc = task.exception()
                if exc is not None:
                    self._handle_step_exception(step, exc)
        except asyncio.CancelledError:
            pass
        except Exception as exc:  # pragma: no cover - defensive
            log.exception("engine loop crashed")
            self._enter_error("internal_error", f"Internal engine error: {exc}")
        finally:
            self._finished.set()

    async def _checkpoint(self) -> None:
        assert self._resume_event is not None and self._parked is not None
        while self._hold is not None and not self._stopped:
            self._resume_event.clear()
            self._parked.set()
            await self._resume_event.wait()
        self._parked.clear()

    async def _execute(self, step: Step) -> None:
        if isinstance(step, SendStep):
            await self._do_send(step)
        elif isinstance(step, AwaitStep):
            await self._do_await(step)
        elif isinstance(step, ConfirmStep):
            await self._do_confirm(step)
        elif isinstance(step, VerifyStep):
            await self._do_verify(step)

    # --- send ----------------------------------------------------------------------
    async def _do_send(self, step: SendStep) -> None:
        p = self.participants[step.target]
        try:
            if step.apply_delay and self.config.delay_seconds > 0:
                self._phase = "delay"
                self.bus.emit(EventType.TRANSFER, status="delay", destination=p.role.value,
                              destination_name=p.name, detail=f"{self.config.delay_seconds:.1f}s delay")
                await asyncio.sleep(self.config.delay_seconds)
            wait = self._rate_limit_wait(step.target)
            if wait > 0:
                self._phase = "delay"
                self.bus.emit(EventType.TRANSFER, status="rate_wait", destination=p.role.value,
                              destination_name=p.name, detail=f"minimum interval: waiting {wait:.1f}s")
                await asyncio.sleep(wait)
            self._phase = "delay"
            await self._ensure_idle(p)
        finally:
            self._phase = None
        if self._hold is not None or self._stopped:
            return  # parked before anything was submitted; step stays pending

        self._phase = "delay" if p.adapter.capabilities.human_in_the_loop else "send"
        self._set_state(S.TRANSFERRING, f"sending to {p.name}")
        self.bus.emit(EventType.TRANSFER, status="sending", destination=p.role.value,
                      destination_name=p.name, source_turn=step.source_turn)
        self.gate.check()
        assert self._send_lock is not None
        async with self._send_lock:
            receipt = await p.adapter.send_message(step.text)
        self._phase = None

        final_text = receipt.final_text or step.text
        now = self.clock()
        self._send_history[step.target].append(now)
        self._sent_at[step.target] = now
        self._last_received[step.target] = final_text
        entry = self.transcript.by_turn(step.source_turn) if step.source_turn else None
        if entry is not None:
            entry.forwarded_text = final_text
            entry.destination = p.role.value
            entry.destination_name = p.name
            entry.edited = entry.edited or step.edited or (receipt.final_text not in ("", step.text))
            entry.transfer_status = "sent" if receipt.confirmed else "uncertain"
            self._entry_updated(entry)

        if not receipt.confirmed:
            self.transcript.add_event("warning", "uncertain_submission",
                                      f"Submission to {p.name} could not be confirmed ({receipt.detail})")
            self.bus.emit(EventType.TRANSFER, status="uncertain", destination=p.role.value,
                          destination_name=p.name, detail=receipt.detail)
            self._next_step = VerifyStep(step.target, step.text, step.source_turn, step.kind, step.after)
            return
        self.bus.emit(EventType.TRANSFER, status="sent", destination=p.role.value,
                      destination_name=p.name, detail=", ".join(receipt.signals))
        self._next_step = AwaitStep(step.target, after=step.after)

    async def _ensure_idle(self, p: Participant) -> None:
        deadline = self.clock() + self.config.max_wait_seconds
        notified = False
        while True:
            state = await p.adapter.get_conversation_state()
            if not state.generating:
                return
            if not notified:
                notified = True
                self.bus.emit(EventType.TRANSFER, status="waiting_idle", destination=p.role.value,
                              destination_name=p.name, detail=f"{p.name} is still generating – waiting")
            if self.clock() > deadline:
                raise ParticipantBusyError(f"{p.name} is still generating a response. Wait, or cancel the "
                                           "generation explicitly in the human intervention panel.")
            await asyncio.sleep(0.5)

    def _rate_limit_wait(self, role: Role) -> float:
        hist = self._send_history[role]
        now = self.clock()
        while hist and now - hist[0] > 3600:
            hist.popleft()
        cap = self.config.max_messages_per_hour
        if cap and len(hist) >= cap:
            raise RateLimitedError(f"Configured limit of {cap} messages per hour to "
                                   f"{self.participants[role].name} reached.")
        if hist and self.config.min_interval_seconds > 0:
            return max(0.0, self.config.min_interval_seconds - (now - hist[-1]))
        return 0.0

    # --- await -------------------------------------------------------------------------
    async def _do_await(self, step: AwaitStep) -> None:
        entry, result = await self._await_response(step.target)
        await self._after_response(entry, result, step)

    async def _await_response(self, target: Role) -> tuple[TranscriptEntry, ResponseResult]:
        p = self.participants[target]
        self._phase = "await"
        self._set_state(S.WAITING_FOR_HOST if target is Role.HOST else S.WAITING_FOR_GUEST,
                        f"waiting for {p.name}")
        started = self._sent_at.get(target, self.clock())
        self.bus.emit(EventType.WAITING, role=target.value, name=p.name, active=True,
                      timeout=self.config.max_wait_seconds)
        try:
            result = await p.adapter.wait_for_response(self.config.max_wait_seconds)
        finally:
            self._phase = None
            self.bus.emit(EventType.WAITING, role=target.value, name=p.name, active=False)
        role = Role(result.speaker_override) if result.speaker_override else target
        entry = self._record_response(role, result, started)
        await self._capture_observed(role)
        return entry, result

    async def _after_response(self, entry: TranscriptEntry, result: ResponseResult, step: AwaitStep) -> None:
        role = Role(entry.speaker_role)
        p = self.participants[role]
        mode = self.config.transfer_mode
        history = [HistoryItem(e.turn, e.speaker_role, e.original_text)
                   for e in self.transcript.responses() if e.turn != entry.turn]
        verdict = self.detector.check(role.value, entry.original_text, history,
                                      received_text=self._strip_for_echo(role))
        warnings: list[str] = []
        if verdict.triggered:
            entry.flags.append(f"possible_loop:{verdict.kind}")
            warnings.append(verdict.describe())
            self.transcript.add_event("warning", "loop_detected", f"Turn {entry.turn}: {verdict.describe()}")
        oversize = len(entry.original_text) > self.config.max_message_chars
        if oversize:
            entry.flags.append("oversize")
            warnings.append(f"Message is {len(entry.original_text):,} characters "
                            f"(warning limit {self.config.max_message_chars:,}).")
        if result.confidence == "low":
            warnings.append("Completion was inferred only from a stable-text period – confirm the response "
                            "is complete before forwarding.")
        self._entry_updated(entry)
        self._emit_round()

        if self.completed_rounds >= self.config.max_rounds:
            self._next_step = None
            return

        if step.after == "both_first":
            self._both_first_turn = entry.turn
            self._next_step = AwaitStep(role.other, after="both_second")
            return

        dest = role.other
        alts = [self._alternative(entry, dest)]
        reason = mode.value
        if step.after == "both_second":
            first_turn = self._both_first_turn
            first_entry = self.transcript.by_turn(first_turn) if first_turn else None
            if first_entry is not None:
                alts.append(self._alternative(first_entry, Role(first_entry.speaker_role).other))
            reason = "both_responded"
            warnings.insert(0, "Both participants answered your intervention. Choose which reply to forward.")

        limit = getattr(self.participants[dest].adapter, "max_input_chars", None)
        if isinstance(limit, int) and len(alts[0].text) > limit:
            warnings.append(f"The forwarded text has {len(alts[0].text):,} characters; the input limit configured for "
                            f"{self.participants[dest].name} is {limit:,}. Shorten it before sending.")
            oversize = True
        needs_confirm = (
            mode is TransferMode.MANUAL
            or result.confidence == "low"
            or p.adapter.capabilities.requires_confirmation
            or step.after == "both_second"
        )
        for alt in alts:
            src = self.transcript.by_turn(alt.source_turn)
            if src is not None and src.transfer_status == "not_forwarded":
                src.destination, src.destination_name = alt.destination.value, alt.destination_name
                src.transfer_status = "pending"
                self._entry_updated(src)

        if verdict.triggered or (oversize and mode is not TransferMode.MANUAL):
            self._next_step = ConfirmStep(alts, warnings, "loop_warning" if verdict.triggered else "oversize")
            self._raise_issue("loop_detected" if verdict.triggered else "oversize",
                              "Session paused: " + " ".join(warnings[:2]),
                              actions=["resume", "human", "stop"])
            return
        if needs_confirm:
            self._next_step = ConfirmStep(alts, warnings, reason)
        else:
            self._next_step = SendStep(dest, alts[0].text, entry.turn, kind="transfer")
        if self._step_once:
            self._step_once = False
            self._hold = HOLD_PAUSE
            self._transition(S.PAUSED, "single step finished")

    def _strip_for_echo(self, role: Role) -> str | None:
        received = self._last_received.get(role)
        return received

    def _alternative(self, entry: TranscriptEntry, dest: Role) -> Alternative:
        d = self.participants[dest]
        template = self.config.transfer_template if self.config.attribution else RAW_TEMPLATE
        text = render_transfer(template, entry.original_text, speaker=entry.speaker_name,
                               destination=d.name, round=entry.round, turn=entry.turn,
                               topic=self.config.topic, host=self.participants[Role.HOST].name,
                               guest=self.participants[Role.GUEST].name)
        return Alternative(entry.turn, entry.speaker_name, dest, d.name, text, entry.original_text)

    # --- confirm / verify ----------------------------------------------------------------
    async def _do_confirm(self, step: ConfirmStep) -> None:
        assert self._loop is not None
        self._phase = "confirm"
        self._set_state(S.WAITING_FOR_CONFIRMATION, "awaiting operator confirmation")
        fut = self._loop.create_future()
        self._decision, self._decision_kind = fut, "confirm"
        self.bus.emit(
            EventType.CONFIRMATION_REQUIRED, kind="transfer", reason=step.reason, warnings=list(step.warnings),
            mode=self.config.transfer_mode.value,
            alternatives=[{
                "source_turn": a.source_turn, "source_name": a.source_name, "destination": a.destination.value,
                "destination_name": a.destination_name, "text": a.text, "original": a.original,
            } for a in step.alternatives],
        )
        try:
            action, payload = await fut
        finally:
            self._decision, self._decision_kind, self._phase = None, None, None
            self.bus.emit(EventType.CONFIRMATION_CLEARED)

        if action == "send":
            index, text = payload
            index = index if 0 <= index < len(step.alternatives) else 0
            alt = step.alternatives[index]
            text = alt.text if text is None else text
            if not text.strip():
                self._log("Empty message not sent – edit the text or skip", "warning")
                return  # step stays pending -> re-offered
            for other_alt in step.alternatives:
                if other_alt is not alt:
                    self._mark_entry(other_alt.source_turn, "not_forwarded")
            self._next_step = SendStep(alt.destination, text, alt.source_turn, kind="transfer",
                                       apply_delay=False, edited=text != alt.text)
        elif action == "skip":
            for alt in step.alternatives:
                self._mark_entry(alt.source_turn, "skipped")
            self.transcript.add_event("info", "transfer_skipped", "Operator skipped a transfer")
            self._hold = HOLD_HUMAN
            self._pause_after_human = False
            self._transition(S.HUMAN_INTERVENTION, "transfer skipped")
            self.bus.emit(EventType.HUMAN, status="open", reason="skipped", pending=self._describe_pending())
            self._log("Transfer skipped – human intervention opened (Resume previous re-offers it)")

    async def _do_verify(self, step: VerifyStep) -> None:
        assert self._loop is not None
        p = self.participants[step.target]
        self._phase = "verify"
        self._set_state(S.WAITING_FOR_CONFIRMATION, "submission uncertain")
        fut = self._loop.create_future()
        self._decision, self._decision_kind = fut, "verify"
        self.bus.emit(EventType.CONFIRMATION_REQUIRED, kind="verify", role=p.role.value, name=p.name,
                      text=step.text,
                      message=(f"The application could not confirm that the message to {p.name} was submitted. "
                               f"Look at {p.name}'s browser window. Nothing will be resent automatically."))
        try:
            action, _ = await fut
        finally:
            self._decision, self._decision_kind, self._phase = None, None, None
            self.bus.emit(EventType.CONFIRMATION_CLEARED)
        if action == "submitted":
            self._mark_entry(step.source_turn, "sent")
            self.transcript.add_event("info", "submission_verified", f"Operator verified submission to {p.name}")
            self._next_step = AwaitStep(step.target, after=step.after)
        else:
            self.transcript.add_event("info", "resend_requested", f"Operator requested resend to {p.name}")
            self._next_step = SendStep(step.target, step.text, step.source_turn, step.kind,
                                       apply_delay=False, after=step.after)

    # --- human intervention ------------------------------------------------------------
    async def _human_send_locked(self, target: str, text: str) -> None:
        pending = self._next_step
        discard_turns: list[int] = []
        if isinstance(pending, AwaitStep):
            outstanding = [pending.target]
            if pending.after == "both_first":
                outstanding.append(pending.target.other)
            last_entry: TranscriptEntry | None = None
            for role in outstanding:
                name = self.participants[role].name
                self.bus.emit(EventType.HUMAN, status="waiting_for_pending", role=role.value, name=name,
                              detail=f"Waiting for {name} to finish its current response before sending.")
                last_entry, _ = await self._await_response(role)
                self._emit_round()
            assert last_entry is not None
            # If sending the human message fails, Resume re-offers forwarding this response.
            self._next_step = ConfirmStep(
                [self._alternative(last_entry, Role(last_entry.speaker_role).other)], [], "after_intervention")
            self._transition(S.HUMAN_INTERVENTION, "pending responses recorded")
        elif isinstance(pending, ConfirmStep):
            discard_turns = [alt.source_turn for alt in pending.alternatives]
        elif isinstance(pending, SendStep) and pending.kind == "transfer" and pending.source_turn:
            discard_turns = [pending.source_turn]

        targets = [Role.HOST, Role.GUEST] if target == "both" else [Role(target)]
        current_round = min(self.completed_rounds + 1, self.config.max_rounds)
        for idx, role in enumerate(targets):
            p = self.participants[role]
            self._phase = "delay"
            await self._ensure_idle(p)
            entry = self._add_entry(TranscriptEntry(
                turn=self._next_turn(), round=current_round, kind=EntryKind.HUMAN, speaker_role="human",
                speaker_name=self.config.human_name, provider="—", timestamp=now_iso(), original_text=text,
                destination=role.value, destination_name=p.name, transfer_status="pending"))
            outgoing = render_transfer(self.config.human_template, text, speaker=self.config.human_name,
                                       destination=p.name, topic=self.config.topic,
                                       host=self.participants[Role.HOST].name,
                                       guest=self.participants[Role.GUEST].name,
                                       round=current_round, turn=entry.turn)
            self._phase = "delay" if p.adapter.capabilities.human_in_the_loop else "send"
            self._set_state(S.TRANSFERRING, f"human message to {p.name}")
            self.gate.check()
            assert self._send_lock is not None
            async with self._send_lock:
                receipt = await p.adapter.send_message(outgoing)
            self._phase = None
            final_text = receipt.final_text or outgoing
            now = self.clock()
            self._send_history[role].append(now)
            self._sent_at[role] = now
            self._last_received[role] = final_text
            entry.forwarded_text = final_text
            entry.transfer_status = "sent" if receipt.confirmed else "uncertain"
            self._entry_updated(entry)
            for turn in discard_turns:
                self._mark_entry(turn, "discarded", only_if_unsent=True)
            discard_turns = []
            after = "both_first" if (target == "both" and idx == 0) else "human"
            if not receipt.confirmed:
                if target == "both" and idx == 0:
                    self._log(f"Message to {self.participants[Role.GUEST].name} was not sent because the "
                              f"submission to {p.name} is uncertain.", "warning")
                    after = "human"
                self._next_step = VerifyStep(role, outgoing, entry.turn, "human", after)
                self._finish_human()
                return
        self._next_step = AwaitStep(Role.HOST, after="both_first") if target == "both" \
            else AwaitStep(targets[0], after="human")
        self._finish_human()

    def _finish_human(self) -> None:
        self.bus.emit(EventType.HUMAN, status="closed")
        if self._pause_after_human:
            self._hold = HOLD_PAUSE
            self._transition(S.PAUSED, "paused after human intervention")
        else:
            self._hold = None
        assert self._resume_event is not None
        self._resume_event.set()

    # =========================================================================
    # holds, issues, errors
    # =========================================================================
    def _interrupt(self, for_human: bool) -> None:
        task = self._step_task
        if task is None or task.done():
            return
        phase = self._phase
        if phase in ("confirm", "delay") or (phase == "verify" and not for_human) or \
                (for_human and phase == "await"):
            task.cancel()

    def _clear_hold(self) -> None:
        self._hold = None
        self._hold_detail = None
        self.bus.emit(EventType.ISSUE_CLEARED)
        if self._step_task is not None and not self._step_task.done() and self._underlying is not None:
            self._transition(self._underlying, "resumed")
        assert self._resume_event is not None
        self._resume_event.set()

    def _raise_issue(self, code: str, message: str, actions: list[str] | None = None,
                     severity: str = "warning") -> None:
        self._hold = HOLD_ISSUE
        self._hold_detail = {"code": code, "message": message}
        self._transition(S.PAUSED, code)
        self.transcript.add_event(severity, code, message)
        self.bus.emit(EventType.ISSUE, code=code, severity=severity, message=message,
                      actions=actions or ["resume", "human", "stop"])
        self._log(message, severity)

    def _enter_error(self, code: str, message: str) -> None:
        self._hold = HOLD_ERROR
        self._hold_detail = {"code": code, "message": message}
        self._transition(S.ERROR, code)
        self.transcript.add_event("error", code, message)
        self.bus.emit(EventType.ISSUE, code=code, severity="error", message=message,
                      actions=["resume", "stop"])
        self._log(message, "error")

    def _handle_step_exception(self, step: Step | None, exc: BaseException) -> None:
        if self._stopped or isinstance(exc, SubmissionBlockedError):
            return
        if isinstance(exc, ResponseTimeoutError):
            self._raise_issue("timeout", f"{exc} Resume keeps waiting (nothing is resent).",
                              actions=["keep_waiting", "human", "stop"])
        elif isinstance(exc, RateLimitedError):
            self._raise_issue("rate_limited", f"Rate limit: {exc} Resume when the provider allows it.")
        elif isinstance(exc, ParticipantBusyError):
            self._raise_issue("participant_busy", str(exc))
        elif isinstance(exc, MessageTooLongError) and isinstance(step, SendStep):
            entry = self.transcript.by_turn(step.source_turn) if step.source_turn else None
            self._next_step = ConfirmStep([Alternative(
                step.source_turn or 0, entry.speaker_name if entry else "Operator", step.target,
                self.participants[step.target].name, step.text, entry.original_text if entry else step.text)],
                [str(exc)], "too_long")
            self._raise_issue("message_too_long", f"{exc} Resume to edit the text.")
        elif isinstance(exc, (BrowserClosedError, AuthenticationRequiredError, AdapterError)):
            if isinstance(step, SendStep) and getattr(exc, "submission_attempted", False):
                self._next_step = VerifyStep(step.target, step.text, step.source_turn, step.kind, step.after)
            code = getattr(exc, "code", "adapter_error")
            hint = {
                "browser_closed": " Reopen the browser window, then press Resume.",
                "authentication_required": " Log in manually in the browser window, then press Resume.",
                "element_not_found": " Run the adapter diagnostics; selectors may need an update.",
            }.get(code, "")
            self._enter_error(code, f"{exc}{hint}")
        else:
            log.exception("unexpected step failure", exc_info=exc)
            if isinstance(step, SendStep):
                self._next_step = VerifyStep(step.target, step.text, step.source_turn, step.kind, step.after)
            self._enter_error("unexpected_error", f"Unexpected error: {type(exc).__name__}: {exc}")

    async def _check_participants(self, require_ready: bool) -> list[str]:
        problems: list[str] = []
        for p in self.participants.values():
            try:
                await p.adapter.connect()
                if require_ready and not await p.adapter.is_ready():
                    problems.append(f"{p.name} – {p.adapter.not_ready_reason or 'not ready'}")
            except AdapterError as exc:
                problems.append(f"{p.name} – {exc}")
            except Exception as exc:  # noqa: BLE001
                problems.append(f"{p.name} – {type(exc).__name__}: {exc}")
        return problems

    def _controllable(self) -> bool:
        return self._run_task is not None and not self._stopped and not self.sm.is_terminal

    def _describe_pending(self) -> dict[str, Any]:
        step = self._next_step
        if isinstance(step, AwaitStep):
            return {"kind": "await", "role": step.target.value, "name": self.participants[step.target].name}
        if isinstance(step, ConfirmStep):
            a = step.alternatives[0]
            return {"kind": "confirm", "role": a.destination.value, "name": a.destination_name}
        if isinstance(step, SendStep):
            return {"kind": "send", "role": step.target.value, "name": self.participants[step.target].name}
        if isinstance(step, VerifyStep):
            return {"kind": "verify", "role": step.target.value, "name": self.participants[step.target].name}
        return {"kind": "none"}

    # =========================================================================
    # transcript helpers
    # =========================================================================
    def _next_turn(self) -> int:
        self._turn += 1
        return self._turn

    def _add_entry(self, entry: TranscriptEntry) -> TranscriptEntry:
        self.transcript.add(entry)
        self.bus.emit(EventType.ENTRY_ADDED, entry=entry.as_dict())
        return entry

    def _entry_updated(self, entry: TranscriptEntry) -> None:
        self.bus.emit(EventType.ENTRY_UPDATED, entry=entry.as_dict())

    def _mark_entry(self, turn: int | None, status: str, only_if_unsent: bool = False) -> None:
        entry = self.transcript.by_turn(turn) if turn else None
        if entry is None or (only_if_unsent and entry.transfer_status == "sent"):
            return
        entry.transfer_status = status
        self._entry_updated(entry)

    def _record_response(self, role: Role, result: ResponseResult, started: float) -> TranscriptEntry:
        p = self.participants[role]
        self._response_counts[role] += 1
        flags = list(result.flags)
        if role in self._cancelled_generation:
            flags.append("generation_cancelled_by_operator")
            self._cancelled_generation.discard(role)
        entry = TranscriptEntry(
            turn=self._next_turn(), round=self._response_counts[role], kind=EntryKind.RESPONSE,
            speaker_role=role.value, speaker_name=p.name, provider=p.provider_label, timestamp=now_iso(),
            original_text=result.text, message_hash=result.text_hash, message_id=result.message_id,
            confidence=result.confidence, simulated=p.adapter.capabilities.simulated, flags=flags,
            duration_s=round(max(0.0, self.clock() - started), 2))
        return self._add_entry(entry)

    def _emit_round(self) -> None:
        completed = self.completed_rounds
        self.bus.emit(EventType.ROUND, current_round=min(completed + 1, self.config.max_rounds),
                      completed_rounds=completed, max_rounds=self.config.max_rounds, turn=self._turn,
                      responses=self.response_counts)

    async def _capture_observed(self, role: Role, initial: bool = False) -> None:
        if role in self._observed_roles and not initial:
            return
        p = self.participants[role]
        try:
            snap = await asyncio.wait_for(p.adapter.get_conversation_state(), 5)
        except Exception:  # noqa: BLE001 - observation is best effort
            return
        facts = self.transcript.meta.facts
        if snap.conversation_id:
            facts[f"{role.value}_conversation_id"] = fact(snap.conversation_id, Provenance.OBSERVED)
            self._observed_roles.add(role)
        elif f"{role.value}_conversation_id" not in facts:
            facts[f"{role.value}_conversation_id"] = fact(None, Provenance.UNAVAILABLE)
        if initial:
            facts[f"{role.value}_existing_messages_at_start"] = fact(snap.assistant_count, Provenance.OBSERVED) \
                if snap.url else fact(None, Provenance.UNAVAILABLE)

    def _build_meta(self) -> SessionMeta:
        c = self.config
        host, guest = self.participants[Role.HOST], self.participants[Role.GUEST]
        meta = SessionMeta(
            title=c.session_name, research_question=c.research_question, topic=c.topic,
            host_name=host.name, host_provider=host.provider_label, guest_name=guest.name,
            guest_provider=guest.provider_label, transfer_mode=c.transfer_mode.value,
            template_mode="attributed" if c.attribution else "raw",
            transfer_template=c.transfer_template if c.attribution else RAW_TEMPLATE,
            initial_prompt=c.initial_prompt, first_speaker=c.first_speaker.value, max_rounds=c.max_rounds,
            demo=c.demo, notes=c.notes, experiment=c.experiment, condition=c.condition)
        meta.facts["host_model"] = fact(host.model_name, Provenance.USER_REPORTED)
        meta.facts["guest_model"] = fact(guest.model_name, Provenance.USER_REPORTED)
        for key, value in c.user_reported.items():
            meta.facts[key] = fact(value, Provenance.USER_REPORTED)
        return meta

    def _complete(self, reason: str) -> None:
        if self.sm.is_terminal:
            return
        self._transition(S.COMPLETED, reason)
        self.transcript.add_event("info", "completed", reason)
        self._log(f"Session completed – {reason}")
        self._end_session(S.COMPLETED.value, reason)

    def _end_session(self, end_state: str, reason: str) -> None:
        self.transcript.meta.ended_at = now_iso()
        self.transcript.meta.end_state = end_state
        self.bus.emit(EventType.SESSION_ENDED, end_state=end_state, reason=reason,
                      meta=self.transcript.meta.as_dict(),
                      events=[e.as_dict() for e in self.transcript.events])

    # =========================================================================
    # state plumbing
    # =========================================================================
    def _set_state(self, state: ConversationState, reason: str = "") -> None:
        if state in ACTIVE_STATES:
            self._underlying = state
        if self._hold == HOLD_PAUSE and state in ACTIVE_STATES:
            return
        self._transition(state, reason)

    def _transition(self, state: ConversationState, reason: str = "") -> None:
        try:
            self.sm.transition(state, reason)
        except InvalidTransition as exc:
            log.warning("ignored transition: %s", exc)
            self.bus.emit(EventType.LOG, level="debug", message=f"Ignored state transition: {exc}")

    def _on_state_change(self, state: ConversationState, previous: ConversationState, reason: str) -> None:
        self.bus.emit(EventType.STATE, state=state.value, previous=previous.value, reason=reason,
                      hold=self._hold)

    def _log(self, message: str, level: str = "info") -> None:
        getattr(log, level if level in ("debug", "info", "warning", "error") else "info")(message)
        self.bus.emit(EventType.LOG, level=level, message=message)
