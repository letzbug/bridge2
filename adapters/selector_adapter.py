"""Configurable browser adapter driven by provider selector candidates.

Response completion is decided from COMBINED signals:

* a NEW assistant message relative to the baseline (count and/or message id),
* the generation indicator / stop control is no longer visible,
* the text has been unchanged for the configured stability period,
* a provider completion indicator (e.g. copy/feedback buttons) appeared, when known.

If only the stable-text period could be observed, the result is returned with
confidence "low" and the engine always asks the operator to confirm it.
"""

from __future__ import annotations

import asyncio
import re
import time
from typing import Callable

from app.security import clean_extracted_text, text_hash
from browser.page_driver import PageDriver

from .base import (
    BaseProviderAdapter, ConversationSnapshot, DiagnosticItem, DiagnosticReport, ResponseResult, SubmissionReceipt,
)
from .errors import (
    AdapterError, AuthenticationRequiredError, BrowserClosedError, ElementNotFoundError, MessageTooLongError,
    ParticipantBusyError, RateLimitedError, ResponseTimeoutError,
)
from .registry import SELECTOR_LABELS, ProviderConfig


def _norm(text: str) -> str:
    return " ".join((text or "").split())


class SelectorAdapter(BaseProviderAdapter):
    provider_id = "selector"
    provider_label = "Browser"

    def __init__(self, config: ProviderConfig, page_getter: Callable[[], PageDriver | None],
                 participant_name: str = "", clock: Callable[[], float] = time.monotonic) -> None:
        super().__init__(participant_name)
        self.config = config
        self.provider_id = config.id
        self.provider_label = config.label
        self._page_getter = page_getter
        self.clock = clock
        self._baseline: ConversationSnapshot | None = None
        self._baseline_sels: dict[str, str | None] = {}
        self._gen_known = False
        self._comp_known = False
        self._last_response: str | None = None
        c = self.capabilities
        c.detect_generation = bool(config.candidates("generating"))
        c.stop_generation = bool(config.candidates("stop_button"))
        c.completion_indicator = bool(config.candidates("completion_indicator"))
        c.conversation_id = bool(config.conversation_id_patterns)
        c.automatic_mode = True
        c.requires_live_validation = not config.validated
        self.max_input_chars = config.max_input_chars

    # ------------------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------------------
    def _page(self) -> PageDriver:
        page = self._page_getter()
        if page is None:
            raise BrowserClosedError(f"{self.participant_name or self.provider_label}: no browser window is open")
        if page.is_closed():
            raise BrowserClosedError(f"{self.participant_name or self.provider_label}: the browser window was closed")
        return page

    async def _first_match(self, page: PageDriver, key: str, visible: bool = False) -> tuple[str, int] | None:
        for sel in self.config.candidates(key):
            try:
                n = await page.count(sel)
                if n <= 0:
                    continue
                if visible and not await page.any_visible(sel):
                    continue
                return sel, n
            except BrowserClosedError:
                raise
            except AdapterError:
                continue  # invalid / unsupported selector -> next candidate
        return None

    async def _count(self, page: PageDriver, key: str, fixed: str | None = None) -> tuple[str | None, int]:
        if fixed:
            try:
                return fixed, await page.count(fixed)
            except BrowserClosedError:
                raise
            except AdapterError:
                pass
        m = await self._first_match(page, key)
        return (m[0], m[1]) if m else (None, 0)

    async def _any_visible(self, page: PageDriver, keys: tuple[str, ...]) -> bool:
        seen = set()
        for key in keys:
            for sel in self.config.candidates(key):
                if sel in seen:
                    continue
                seen.add(sel)
                try:
                    if await page.any_visible(sel):
                        return True
                except BrowserClosedError:
                    raise
                except AdapterError:
                    continue
        return False

    async def _is_generating(self, page: PageDriver) -> bool:
        return await self._any_visible(page, ("generating", "stop_button"))

    async def _message_id(self, page: PageDriver, sel: str | None) -> str | None:
        if not sel:
            return None
        for attr in self.config.message_id_attributes:
            try:
                val = await page.get_attribute(sel, -1, attr)
            except BrowserClosedError:
                raise
            except AdapterError:
                continue
            if val:
                return val
        return None

    async def _extract(self, page: PageDriver, sel: str, index: int = -1) -> str:
        raw = await page.extract_text(sel, index, self.config.extract_exclude, self.config.extract_mode)
        return clean_extracted_text(raw)

    def _conversation_id(self, url: str) -> str | None:
        for pattern in self.config.conversation_id_patterns:
            try:
                m = re.search(pattern, url or "")
            except re.error:
                continue
            if m:
                return m.group(1)
        return None

    async def _auth_state(self, page: PageDriver, url: str, input_visible: bool | None = None) -> str:
        low = (url or "").lower()
        if any(p.lower() in low for p in self.config.login_url_patterns):
            return "login_required"
        if await self._any_visible(page, ("login_required",)):
            return "login_required"
        if input_visible is None:
            input_visible = (await self._first_match(page, "input", visible=True)) is not None
        return "logged_in" if input_visible else "unknown"

    async def _check_problems(self, page: PageDriver) -> None:
        url = await page.url()
        if await self._auth_state(page, url, input_visible=True) == "login_required":
            raise AuthenticationRequiredError(
                f"{self.participant_name}: the provider is asking for a login (session expired?)")
        for sel in self.config.candidates("error_banner"):
            try:
                texts = await page.texts(sel, 5)
            except BrowserClosedError:
                raise
            except AdapterError:
                continue
            for t in texts:
                low = t.lower()
                if any(p in low for p in self.config.rate_limit_text_patterns):
                    raise RateLimitedError(f"{self.participant_name}: provider message: “{_norm(t)[:200]}”")

    async def _snapshot(self, page: PageDriver) -> tuple[ConversationSnapshot, dict[str, str | None]]:
        url = await page.url()
        a_sel, a_count = await self._count(page, "assistant_message")
        u_sel, u_count = await self._count(page, "user_message")
        c_sel, c_count = await self._count(page, "completion_indicator")
        last_id = await self._message_id(page, a_sel) if a_count else None
        last_hash = None
        if a_count and a_sel:
            try:
                last_hash = text_hash(await self._extract(page, a_sel, -1))
            except BrowserClosedError:
                raise
            except AdapterError:
                last_hash = None
        input_visible = (await self._first_match(page, "input", visible=True)) is not None
        auth = await self._auth_state(page, url, input_visible)
        snap = ConversationSnapshot(
            url=url, conversation_id=self._conversation_id(url), assistant_count=a_count, user_count=u_count,
            last_assistant_id=last_id, last_assistant_hash=last_hash, completion_count=c_count,
            generating=await self._is_generating(page), input_ready=input_visible,
            logged_in=True if auth == "logged_in" else (False if auth == "login_required" else None))
        if c_count:
            self._comp_known = True
        return snap, {"assistant": a_sel, "user": u_sel, "completion": c_sel}

    # ------------------------------------------------------------------------------
    # interface
    # ------------------------------------------------------------------------------
    async def connect(self) -> None:
        self._page()

    async def is_ready(self) -> bool:
        page = self._page()
        snap, _ = await self._snapshot(page)
        if snap.logged_in is False:
            self.not_ready_reason = "login required – log in manually in the browser window"
            return False
        if not snap.input_ready:
            self.not_ready_reason = "message input not detected (open the chat page or run the diagnostics)"
            return False
        if snap.generating:
            self.not_ready_reason = "the assistant is still generating a response"
            return False
        self.not_ready_reason = ""
        return True

    async def check_auth(self) -> str:
        page = self._page()
        return await self._auth_state(page, await page.url())

    async def get_conversation_state(self) -> ConversationSnapshot:
        snap, _ = await self._snapshot(self._page())
        return snap

    async def send_message(self, text: str) -> SubmissionReceipt:
        page = self._page()
        if len(text) > self.config.max_input_chars:
            raise MessageTooLongError(f"Message has {len(text):,} characters; the configured input limit for "
                               f"{self.provider_label} is {self.config.max_input_chars:,}. Edit or shorten it.")
        snap, sels = await self._snapshot(page)
        if snap.logged_in is False:
            raise AuthenticationRequiredError(f"{self.participant_name}: login required")
        if snap.generating:
            raise ParticipantBusyError(f"{self.participant_name} is still generating a response")
        found = await self._first_match(page, "input", visible=True)
        if not found:
            raise ElementNotFoundError(f"{self.participant_name}: message input not found")
        input_sel = found[0]
        self._baseline, self._baseline_sels = snap, sels

        await page.fill(input_sel, text, self.config.input_method)
        if not await self._input_holds(page, input_sel, text):
            alt = "insert_text" if self.config.input_method == "fill" else "fill"
            await page.fill(input_sel, text, alt)
            if not await self._input_holds(page, input_sel, text):
                raise AdapterError(f"{self.participant_name}: the text could not be inserted into the input")

        self._check_gate()  # last check immediately before the actual submission
        try:
            via = await self._submit(page, input_sel)
        except ElementNotFoundError:
            raise
        except BrowserClosedError as exc:
            exc.submission_attempted = True
            raise
        except AdapterError as exc:
            raise AdapterError(str(exc), submission_attempted=True) from exc

        signals = await self._verify_submission(page, snap, sels, input_sel)
        if signals:
            return SubmissionReceipt("confirmed", signals + [via], final_text=text)
        return SubmissionReceipt("uncertain", [via], final_text=text,
                                 detail="no user message, generation start or input reset observed")

    async def _input_holds(self, page: PageDriver, sel: str, text: str) -> bool:
        try:
            current = _norm(await page.read_input(sel))
        except BrowserClosedError:
            raise
        except AdapterError:
            return False
        wanted = _norm(text)
        return bool(wanted) and (wanted[:60] in current or len(current) >= 0.9 * len(wanted))

    async def _submit(self, page: PageDriver, input_sel: str) -> str:
        method = self.config.send_method
        if method in ("click", "click_or_enter"):
            deadline = self.clock() + 2.5
            while True:
                for sel in self.config.candidates("send_button"):
                    try:
                        if await page.first_visible_enabled(sel):
                            await page.click(sel)
                            return f"click:{sel}"
                    except BrowserClosedError:
                        raise
                    except AdapterError:
                        continue
                if self.clock() > deadline:
                    break
                await asyncio.sleep(0.2)
            if method == "click":
                raise ElementNotFoundError(f"{self.participant_name}: no enabled send control found")
        await page.press(input_sel, "Enter")
        return "enter"

    async def _verify_submission(self, page: PageDriver, snap: ConversationSnapshot,
                                 sels: dict[str, str | None], input_sel: str) -> list[str]:
        start = self.clock()
        deadline = start + self.config.submit_verify_seconds
        while self.clock() < deadline:
            signals: list[str] = []
            _, u = await self._count(page, "user_message", sels.get("user"))
            if u > snap.user_count:
                signals.append("user_message_added")
            if await self._is_generating(page):
                signals.append("generation_started")
                self._gen_known = True
            _, a = await self._count(page, "assistant_message", sels.get("assistant"))
            if a > snap.assistant_count:
                signals.append("assistant_message_added")
            try:
                if not (await page.read_input(input_sel)).strip():
                    signals.append("input_cleared")
            except BrowserClosedError:
                raise
            except AdapterError:
                pass
            strong = {"user_message_added", "generation_started", "assistant_message_added"} & set(signals)
            if strong or (signals and self.clock() - start > 1.5):
                return signals
            await asyncio.sleep(0.25)
        return []

    async def wait_for_response(self, timeout: float) -> ResponseResult:
        if self._baseline is None:
            raise AdapterError(f"{self.participant_name}: no baseline – nothing was sent by this adapter")
        b, sels = self._baseline, self._baseline_sels
        cfg = self.config
        stability = cfg.stability_ms / 1000.0
        poll = cfg.poll_ms / 1000.0
        start = self.clock()
        deadline = start + timeout
        a_sel, c_sel = sels.get("assistant"), sels.get("completion")
        last_text: str | None = None
        last_id: str | None = None
        stable_since = start
        gen_seen = False
        gen_clear_since: float | None = None
        comp_seen = False
        next_aux = start
        while True:
            now = self.clock()
            if now > deadline:
                raise ResponseTimeoutError(
                    f"No completed response from {self.participant_name} within {timeout:.0f}s.",
                    partial_text=last_text)
            page = self._page()
            if now >= next_aux:
                await self._check_problems(page)
                next_aux = now + 2.0
            a_sel, count = await self._count(page, "assistant_message", a_sel)
            generating = await self._is_generating(page)
            if generating:
                gen_seen = self._gen_known = True
                gen_clear_since = None
            elif gen_clear_since is None:
                gen_clear_since = now
            latest_id = await self._message_id(page, a_sel) if count else None
            is_new = count > b.assistant_count or bool(
                latest_id and b.last_assistant_id and latest_id != b.last_assistant_id)
            if not is_new and cfg.newness_by_hash and count and a_sel:
                # for virtualised message lists: a changed last message counts as new
                is_new = text_hash(await self._extract(page, a_sel, -1)) != b.last_assistant_hash
            if not is_new or not a_sel:
                await asyncio.sleep(poll)
                continue
            text = await self._extract(page, a_sel, -1)
            if count == b.assistant_count and text_hash(text) == b.last_assistant_hash:
                await asyncio.sleep(poll)   # still the old message from the existing conversation
                continue
            if text != last_text or latest_id != last_id:
                last_text, last_id, stable_since = text, latest_id, now
            if c_sel or cfg.candidates("completion_indicator"):
                c_sel, c_count = await self._count(page, "completion_indicator", c_sel)
                if c_count > b.completion_count:
                    comp_seen = self._comp_known = True
            if not text.strip():
                await asyncio.sleep(poll)
                continue
            stable_for = now - stable_since
            gen_ok = not generating and gen_clear_since is not None and now - gen_clear_since >= min(stability, 1.0)
            comp_ok = comp_seen or not self._comp_known
            if stable_for >= stability and gen_ok and comp_ok:
                confidence = "high" if (gen_seen or comp_seen) else "low"
                if confidence == "low" and stable_for < stability * 2:
                    await asyncio.sleep(poll)
                    continue
                self._baseline = None
                self._last_response = text
                return ResponseResult(
                    text, message_id=latest_id, confidence=confidence,
                    signals={"generation_seen": gen_seen, "completion_indicator_seen": comp_seen,
                             "stable_seconds": round(stable_for, 2), "selector": a_sel})
            await asyncio.sleep(poll)

    async def get_latest_response(self) -> str | None:
        page = self._page()
        a_sel, count = await self._count(page, "assistant_message")
        if not count or not a_sel:
            return None
        return await self._extract(page, a_sel, -1)

    async def stop_generation(self) -> bool:
        page = self._page()
        for sel in self.config.candidates("stop_button"):
            try:
                if await page.any_visible(sel):
                    await page.click(sel)
                    return True
            except BrowserClosedError:
                raise
            except AdapterError:
                continue
        return False

    # ------------------------------------------------------------------------------
    # diagnostics
    # ------------------------------------------------------------------------------
    async def diagnose(self) -> DiagnosticReport:
        report = DiagnosticReport(self.provider_id)
        try:
            page = self._page()
        except BrowserClosedError as exc:
            report.notes.append(str(exc))
            return report
        report.url = await page.url()
        status = self.config.validation.get("status", "unvalidated")
        if status != "validated":
            report.notes.append(f"Adapter status: {status} – {self.config.validation.get('notes', '')}".strip())
        if self.config.automation.get("note"):
            report.notes.append(self.config.automation["note"])

        async def item(key: str, visible: bool) -> DiagnosticItem:
            label = SELECTOR_LABELS.get(key, key)
            cands = self.config.candidates(key)
            if not cands:
                return DiagnosticItem(key, label, "not_configured", detail="no selector candidates configured")
            m = await self._first_match(page, key, visible=visible)
            if m:
                return DiagnosticItem(key, label, "found", m[0], m[1], f"{len(cands)} candidate(s)")
            return DiagnosticItem(key, label, "missing", None, 0, f"none of {len(cands)} candidate(s) matched")

        inp = await item("input", True)
        send = await item("send_button", True)
        msgs = await item("assistant_message", False)
        report.items += [inp, send, msgs]
        generating = await self._is_generating(page)
        gen_item = await item("generating", True)
        if gen_item.status == "missing":
            gen_item.status, gen_item.detail = "idle", "configured; not visible now (normal while idle)"
        report.items.append(gen_item)
        stop_item = await item("stop_button", True)
        if stop_item.status == "missing":
            stop_item.status, stop_item.detail = "idle", "configured; only visible while generating"
        report.items.append(stop_item)
        report.items.append(await item("completion_indicator", False))
        latest = DiagnosticItem("latest_response", "Latest completed assistant response", "missing")
        if msgs.status == "found" and msgs.selector:
            try:
                text = await self._extract(page, msgs.selector, -1)
                if generating:
                    latest.status, latest.detail = "idle", "assistant is generating – not completed yet"
                elif text:
                    latest.status, latest.count, latest.selector = "found", len(text), msgs.selector
                    latest.detail = f"{len(text)} characters extracted"
                    report.latest_preview = text[:400]
                else:
                    latest.detail = "message container found but no text extracted"
            except AdapterError as exc:
                latest.status, latest.detail = "error", str(exc)
        else:
            latest.status, latest.detail = "n/a", "no assistant message on the page yet (new conversation?)"
        report.items.append(latest)
        report.auth = await self._auth_state(page, report.url)
        send_ok = send.status == "found" or self.config.send_method in ("enter", "click_or_enter")
        report.passed = inp.status == "found" and send_ok and report.auth != "login_required"
        return report

    async def highlight(self, key: str) -> int:
        page = self._page()
        m = await self._first_match(page, key)
        if not m:
            return 0
        return await page.highlight(m[0], "#2fd3b5")
