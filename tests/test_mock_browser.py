"""Real-DOM tests: the selector adapter + Playwright driver against assets/mock_chat.html.

Uses whatever Playwright browser is installed (Firefox preferred, Chromium fallback).
Skipped automatically when Playwright or its browsers are unavailable.
"""

import asyncio

import pytest

from adapters.errors import AuthenticationRequiredError, RateLimitedError
from adapters.registry import ProviderRegistry
from adapters.selector_adapter import SelectorAdapter
from app.engine import TransferMode
from app.gate import SendGate
from app.state_machine import ConversationState as S
from browser.playwright_driver import PlaywrightPageDriver

pw_api = pytest.importorskip("playwright.async_api")


async def _launch(p):
    errors = []
    for name in ("firefox", "chromium"):
        try:
            return await getattr(p, name).launch(headless=True), name
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{name}: {str(exc).splitlines()[0]}")
    pytest.skip("no Playwright browser available: " + "; ".join(errors))


def run_with_page(query: str, body):
    async def main():
        async with pw_api.async_playwright() as p:
            browser, _ = await _launch(p)
            try:
                page = await browser.new_page()
                cfg = ProviderRegistry().get("mock")
                await page.goto(cfg.url + query)
                driver = PlaywrightPageDriver(page)
                adapter = SelectorAdapter(cfg, lambda: driver, "Mock")
                adapter.bind_gate(SendGate())
                await body(adapter, page, driver)
            finally:
                await browser.close()
    asyncio.run(asyncio.wait_for(main(), 60))


def test_full_cycle_and_markdown_extraction():
    async def body(adapter, page, driver):
        assert await adapter.is_ready()
        receipt = await adapter.send_message("Please include some code in your reply")
        assert receipt.confirmed, receipt
        result = await adapter.wait_for_response(15)
        assert result.confidence == "high"
        assert result.text.startswith("Mock reply #1: I received 38 characters.")
        assert "- first point\n- second point" in result.text
        assert "```python\ndef hello():\n    return \"world\"\n```" in result.text
        assert "Inline `x = 1` done." in result.text
        assert "Copy" not in result.text                       # UI buttons excluded
        state = await adapter.get_conversation_state()
        assert state.conversation_id == "t1"
    run_with_page("?conv=t1&speed=fast", body)


def test_existing_conversation_baseline_real_dom():
    async def body(adapter, page, driver):
        await adapter.send_message("Second question")
        result = await adapter.wait_for_response(15)
        assert "Earlier answer" not in result.text
        assert "Mock reply #1" in result.text
    run_with_page("?existing=3&speed=fast", body)


def test_swallowed_submission_is_uncertain():
    async def body(adapter, page, driver):
        receipt = await adapter.send_message("This will be ignored by the page")
        assert receipt.status == "uncertain"
    run_with_page("?ignore=1&speed=fast", body)


def test_login_wall_and_rate_limit():
    async def body(adapter, page, driver):
        assert not await adapter.is_ready()
        with pytest.raises(AuthenticationRequiredError):
            await adapter.send_message("hi")
    run_with_page("?login=1", body)

    async def body2(adapter, page, driver):
        await adapter.send_message("first")
        await adapter.wait_for_response(15)
        await adapter.send_message("second")
        with pytest.raises(RateLimitedError):
            await adapter.wait_for_response(10)
    run_with_page("?ratelimit=1&speed=fast", body2)


def test_stop_control_and_role_selector_and_diagnostics():
    async def body(adapter, page, driver):
        assert await driver.count("role:button:^send$") == 1          # accessibility-role selector
        assert await driver.count('button[aria-label*="SEND" i]') == 1  # case-insensitive attribute
        report = await adapter.diagnose()
        items = {i.key: i.status for i in report.items}
        assert items["input"] == "found" and items["send_button"] == "found" and report.passed
        await adapter.send_message("stream slowly please")
        await asyncio.sleep(0.4)
        assert (await adapter.get_conversation_state()).generating
        assert await adapter.stop_generation()
        result = await adapter.wait_for_response(10)
        assert result.text.startswith("Mock reply #1")
        assert await driver.highlight("article", "#fff") >= 2
    run_with_page("", body)


def test_engine_conversation_between_two_mock_pages():
    from tests.fakes import make_engine

    async def main():
        async with pw_api.async_playwright() as p:
            browser, _ = await _launch(p)
            try:
                cfg = ProviderRegistry().get("mock")
                adapters = []
                for name in ("Cameron (mock)", "Gem (mock)"):
                    page = await browser.new_page()
                    await page.goto(cfg.url + "?speed=fast")
                    driver = PlaywrightPageDriver(page)
                    adapters.append(SelectorAdapter(cfg, lambda d=driver: d, name))
                engine, _ = make_engine(*adapters, max_rounds=2, max_wait_seconds=15,
                                        transfer_mode=TransferMode.AUTOMATIC)
                await engine.start()
                assert await engine.wait_finished(45)
                assert engine.state == S.COMPLETED, engine.transcript.events
                responses = engine.transcript.responses()
                assert [r.speaker_role for r in responses] == ["host", "guest", "host", "guest"]
                assert all(r.text_hash if hasattr(r, "text_hash") else r.message_hash for r in responses)
            finally:
                await browser.close()
    asyncio.run(asyncio.wait_for(main(), 90))
