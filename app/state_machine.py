"""Conversation state machine with an explicit transition table."""

from __future__ import annotations

import time
from enum import Enum
from typing import Callable


class ConversationState(str, Enum):
    IDLE = "IDLE"
    CONNECTING = "CONNECTING"
    READY = "READY"
    WAITING_FOR_HOST = "WAITING_FOR_HOST"
    WAITING_FOR_GUEST = "WAITING_FOR_GUEST"
    WAITING_FOR_CONFIRMATION = "WAITING_FOR_CONFIRMATION"
    TRANSFERRING = "TRANSFERRING"
    PAUSED = "PAUSED"
    HUMAN_INTERVENTION = "HUMAN_INTERVENTION"
    ERROR = "ERROR"
    STOPPED = "STOPPED"
    COMPLETED = "COMPLETED"

    def __str__(self) -> str:  # pragma: no cover - cosmetic
        return self.value


S = ConversationState

#: states in which the engine is doing (or about to do) automated work
ACTIVE_STATES = frozenset({
    S.WAITING_FOR_HOST, S.WAITING_FOR_GUEST, S.WAITING_FOR_CONFIRMATION, S.TRANSFERRING,
})
#: states in which a conversation run exists (not finished)
RUNNING_STATES = ACTIVE_STATES | {S.READY, S.CONNECTING, S.PAUSED, S.HUMAN_INTERVENTION, S.ERROR}
TERMINAL_STATES = frozenset({S.STOPPED, S.COMPLETED})

_WORK = {S.WAITING_FOR_HOST, S.WAITING_FOR_GUEST, S.WAITING_FOR_CONFIRMATION, S.TRANSFERRING}

TRANSITIONS: dict[ConversationState, frozenset[ConversationState]] = {
    S.IDLE: frozenset({S.CONNECTING, S.READY, S.STOPPED}),
    S.CONNECTING: frozenset({S.READY, S.ERROR, S.STOPPED, S.IDLE}),
    S.READY: frozenset(_WORK | {S.PAUSED, S.HUMAN_INTERVENTION, S.STOPPED, S.ERROR, S.IDLE}),
    S.WAITING_FOR_HOST: frozenset(_WORK | {S.PAUSED, S.HUMAN_INTERVENTION, S.ERROR, S.STOPPED, S.COMPLETED}),
    S.WAITING_FOR_GUEST: frozenset(_WORK | {S.PAUSED, S.HUMAN_INTERVENTION, S.ERROR, S.STOPPED, S.COMPLETED}),
    S.WAITING_FOR_CONFIRMATION: frozenset(_WORK | {S.PAUSED, S.HUMAN_INTERVENTION, S.ERROR, S.STOPPED, S.COMPLETED}),
    S.TRANSFERRING: frozenset(_WORK | {S.PAUSED, S.HUMAN_INTERVENTION, S.ERROR, S.STOPPED}),
    S.PAUSED: frozenset(_WORK | {S.HUMAN_INTERVENTION, S.ERROR, S.STOPPED, S.COMPLETED}),
    S.HUMAN_INTERVENTION: frozenset(_WORK | {S.PAUSED, S.ERROR, S.STOPPED, S.COMPLETED}),
    S.ERROR: frozenset(_WORK | {S.CONNECTING, S.PAUSED, S.HUMAN_INTERVENTION, S.STOPPED, S.IDLE}),
    S.STOPPED: frozenset({S.IDLE, S.CONNECTING}),
    S.COMPLETED: frozenset({S.IDLE, S.CONNECTING, S.STOPPED}),
}


class InvalidTransition(RuntimeError):
    pass


class StateMachine:
    def __init__(self, on_change: Callable[[ConversationState, ConversationState, str], None] | None = None) -> None:
        self._state = S.IDLE
        self._on_change = on_change
        self.history: list[tuple[float, ConversationState, str]] = [(time.time(), S.IDLE, "init")]

    @property
    def state(self) -> ConversationState:
        return self._state

    def can(self, target: ConversationState) -> bool:
        return target == self._state or target in TRANSITIONS[self._state]

    def transition(self, target: ConversationState, reason: str = "") -> bool:
        """Move to *target*. Returns False for a same-state no-op. Raises on invalid transitions."""
        if target == self._state:
            return False
        if target not in TRANSITIONS[self._state]:
            raise InvalidTransition(f"{self._state.value} -> {target.value} is not allowed ({reason})")
        previous = self._state
        self._state = target
        self.history.append((time.time(), target, reason))
        if self._on_change:
            self._on_change(target, previous, reason)
        return True

    def force_stop(self, reason: str) -> None:
        """Emergency path: STOPPED is always reachable from a non-terminal state."""
        if self._state in TERMINAL_STATES or self._state == S.IDLE:
            if self._state == S.IDLE:
                self.transition(S.STOPPED, reason)
            return
        self.transition(S.STOPPED, reason)

    @property
    def is_running(self) -> bool:
        return self._state in RUNNING_STATES

    @property
    def is_terminal(self) -> bool:
        return self._state in TERMINAL_STATES
