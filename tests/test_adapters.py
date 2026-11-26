"""Provider registry and selector adapter tests (fake page)."""

import asyncio
import json

import pytest

from adapters.errors import (
    AuthenticationRequiredError, BrowserClosedError, RateLimitedError, ResponseTimeoutError, SubmissionBlockedError,
)
from adapters.registry import GUEST_CHOICES, ProviderConfigError, ProviderRegistry, adapter_class_for
from adapters.selector_adapter import SelectorAdapter
from app.gate import SendGate

from .fake_page import FakeChatPage, fake_config


def run(coro):
    return asyncio.run(asyncio.wait_for(coro, 20))


# --- registry ------------------------------------------------------------------------

def test_registry_loads_all_providers(tmp_path):
    reg = ProviderRegistry(user_path=tmp_path / "providers.user.json")
    for pid in ["chatgpt", *GUEST_CHOICES, "mock"]:
        cfg = reg.get(pid)
        assert cfg.label
        if cfg.kind == "browser" and pid != "companion":
            assert cfg.candidates("input"), pid
            adapter_class_for(pid)
    chatgpt = reg.get("chatgpt")
    assert chatgpt.candidates("input")[0] == "#prompt-textarea"
    assert "textarea" in chatgpt.candidates("input")           # generic fallback appended
    assert not chatgpt.validated and reg.get("mock").validated
    assert reg.get("mock").url.startswith("file://")


def test_user_override_changes_selectors_without_code(tmp_path):
    user = tmp_path / "providers.user.json"
    reg = ProviderRegistry(user_path=user)
    reg.save_override("gemini", {"selectors": {"input": ["#my-input"]}, "stability_ms": 2500})
    cfg = ProviderRegistry(user_path=user).get("gemini")
    assert cfg.candidates("input")[0] == "#my-input"
    assert cfg.stability_ms == 2500 and cfg.overridden
    reg.reset_override("gemini")
    assert not ProviderRegistry(user_path=user).get("gemini").overridden


def test_invalid_override_rejected(tmp_path):
    reg = ProviderRegistry(user_path=tmp_path / "p.json")
    with pytest.raises(ProviderConfigError):
        reg.save_override("chatgpt", {"selectors": {"input": "not-a-list"}})
    with pytest.raises(ProviderConfigError):
        reg.save_override("chatgpt", {"selectors": {"bogus_key": ["x"]}})
    (tmp_path / "bad.json").write_text(json.dumps({"providers": {"chatgpt": {"selectors": {"input": 3}}}}))
    reg2 = ProviderRegistry(user_path=tmp_path / "bad.json")
    assert reg2.load_error and reg2.get("chatgpt").candidates("input")[0] == "#prompt-textarea"


# --- selector adapter -------------------------------------------------------------------

def make(page, **cfg):
    adapter = SelectorAdapter(fake_config(**cfg), lambda: page, "Gem")
    adapter.bind_gate(SendGate())
    return adapter


def test_send_and_wait_with_candidate_fallback():
    async def scenario():
        page = FakeChatPage()
        a = make(page)
        assert await a.is_ready()
        receipt = await a.send_message("Hello there")
        assert receipt.confirmed and "user_message_added" in receipt.signals
        result = await a.wait_for_response(5)
        assert result.text == "Fake reply 0 to: Hello there"
        assert result.confidence == "high" and result.message_id
        state = await a.get_conversation_state()
        assert state.conversation_id == "abc123"
    run(scenario())


def test_existing_conversation_baseline_ignores_old_messages():
    async def scenario():
        page = FakeChatPage(existing=3)
        a = make(page)
        await a.send_message("New question")
        result = await a.wait_for_response(5)
        assert "Earlier answer" not in result.text
        assert result.text.startswith("Fake reply 0")
    run(scenario())


def test_no_response_without_new_message_times_out():
    async def scenario():
        page = FakeChatPage(existing=2, ignore_submit=True)
        a = make(page)
        receipt = await a.send_message("Will be swallowed")
        assert receipt.status == "uncertain"            # never assumed submitted
        with pytest.raises(ResponseTimeoutError):
            await a.wait_for_response(0.5)               # old message is never returned
        assert page.clicks == 1                          # adapter never resends by itself
    run(scenario())


def test_streaming_is_not_returned_early():
    async def scenario():
        page = FakeChatPage(steps=6, step_s=0.05)
        a = make(page)
        await a.send_message("long")
        result = await a.wait_for_response(5)
        assert result.text == "Fake reply 0 to: long"    # complete text only
    run(scenario())


def test_low_confidence_without_generation_signals():
    async def scenario():
        page = FakeChatPage(show_generation=False)
        a = make(page, with_generation=False, with_completion=False)
        await a.send_message("hi")
        result = await a.wait_for_response(5)
        assert result.confidence == "low"
    run(scenario())


def test_browser_closed_during_wait():
    async def scenario():
        page = FakeChatPage(steps=20, step_s=0.05)
        a = make(page)
        await a.send_message("hi")
        asyncio.get_running_loop().call_later(0.15, lambda: setattr(page, "closed", True))
        with pytest.raises(BrowserClosedError):
            await a.wait_for_response(5)
    run(scenario())


def test_login_required_detected():
    async def scenario():
        a = make(FakeChatPage(login=True))
        assert not await a.is_ready()
        assert "login" in a.not_ready_reason
        with pytest.raises(AuthenticationRequiredError):
            await a.send_message("hi")
    run(scenario())


def test_rate_limit_banner_detected():
    async def scenario():
        page = FakeChatPage(rate_limit_after=0)
        a = make(page)
        await a.send_message("hi")
        with pytest.raises(RateLimitedError):
            await a.wait_for_response(3)
    run(scenario())


def test_gate_blocks_submission_after_text_insert():
    async def scenario():
        page = FakeChatPage()
        a = make(page)
        a.gate.disarm("emergency stop")
        with pytest.raises(SubmissionBlockedError):
            await a.send_message("must not be sent")
        assert page.clicks == 0 and not page._of("user")
    run(scenario())


def test_stop_generation_and_diagnostics():
    async def scenario():
        page = FakeChatPage(steps=50, step_s=0.05)
        a = make(page)
        report = await a.diagnose()
        items = {i.key: i for i in report.items}
        assert items["input"].status == "found" and items["input"].selector == "#prompt"
        assert items["send_button"].status == "found"
        assert report.passed
        await a.send_message("hi")
        await asyncio.sleep(0.1)
        assert await a.stop_generation()
    run(scenario())
