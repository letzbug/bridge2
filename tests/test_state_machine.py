import pytest

from app.state_machine import TRANSITIONS, ConversationState as S, InvalidTransition, StateMachine


def test_required_states_exist():
    names = {s.value for s in S}
    assert names == {"IDLE", "CONNECTING", "READY", "WAITING_FOR_HOST", "WAITING_FOR_GUEST",
                     "WAITING_FOR_CONFIRMATION", "TRANSFERRING", "PAUSED", "HUMAN_INTERVENTION",
                     "ERROR", "STOPPED", "COMPLETED"}
    assert set(TRANSITIONS) == set(S)


def test_valid_path_and_history():
    changes = []
    sm = StateMachine(on_change=lambda new, old, reason: changes.append((old, new)))
    for target in (S.CONNECTING, S.READY, S.TRANSFERRING, S.WAITING_FOR_HOST, S.WAITING_FOR_CONFIRMATION,
                   S.TRANSFERRING, S.WAITING_FOR_GUEST, S.COMPLETED):
        sm.transition(target)
    assert sm.state == S.COMPLETED
    assert sm.is_terminal
    assert changes[0] == (S.IDLE, S.CONNECTING)


def test_invalid_transitions_raise():
    sm = StateMachine()
    with pytest.raises(InvalidTransition):
        sm.transition(S.TRANSFERRING)
    sm.transition(S.CONNECTING)
    sm.transition(S.READY)
    sm.transition(S.STOPPED)
    with pytest.raises(InvalidTransition):
        sm.transition(S.WAITING_FOR_HOST)   # a stopped session never continues by itself


def test_same_state_is_noop():
    sm = StateMachine()
    assert sm.transition(S.IDLE) is False


def test_stop_reachable_from_every_running_state():
    for state, targets in TRANSITIONS.items():
        if state not in (S.STOPPED, S.COMPLETED):
            assert S.STOPPED in targets, state


def test_force_stop():
    sm = StateMachine()
    sm.transition(S.CONNECTING)
    sm.transition(S.READY)
    sm.transition(S.WAITING_FOR_GUEST)
    sm.force_stop("emergency")
    assert sm.state == S.STOPPED
