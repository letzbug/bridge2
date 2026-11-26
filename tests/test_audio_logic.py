"""Audio companion logic without hardware: VAD, half duplex, echo rejection, authorisation."""

import asyncio
from types import SimpleNamespace

import pytest

from adapters.errors import AdapterError, ResponseTimeoutError
from app.events import EventBus, EventRecorder, EventType
from audio.audio_manager import AudioManager, AudioSettings
from audio.companion_adapter import AudioCompanionAdapter
from audio.voice_activity import UtteranceSegmenter, VadConfig, rms_dbfs


def test_rms_dbfs():
    assert rms_dbfs([]) == -120.0
    assert abs(rms_dbfs([1.0, -1.0]) - 0.0) < 1e-6
    assert -21 < rms_dbfs([0.1] * 10) < -19


def test_segmenter_detects_utterance_end():
    seg = UtteranceSegmenter(VadConfig(min_speech_ms=90, end_silence_ms=300, frame_ms=30))
    statuses = [seg.feed(-70) for _ in range(20)]
    assert set(statuses) == {"silence"}
    statuses = [seg.feed(-20) for _ in range(10)]
    assert statuses[-1] == "speech"
    statuses = [seg.feed(-70) for _ in range(12)]
    assert "complete" in statuses


def test_segmenter_ignores_short_clicks():
    seg = UtteranceSegmenter(VadConfig(min_speech_ms=200, end_silence_ms=300, frame_ms=30))
    for _ in range(3):
        seg.feed(-15)          # 90 ms click
    assert all(seg.feed(-70) == "silence" for _ in range(20))
    assert not seg.started


class FakeSource:
    rate = 16000

    def __init__(self, levels, manager=None, speak_during=None):
        self.levels = levels
        self.manager = manager

    async def frames(self):
        for i, lvl in enumerate(self.levels):
            await asyncio.sleep(0.001)
            yield lvl, (i, lvl)

    async def close(self):
        pass


def make_manager(transcripts, levels, **settings):
    bus = EventBus()
    rec = EventRecorder(bus)
    captured = []
    texts = iter(transcripts)

    def transcribe(chunks, rate):
        captured.append(list(chunks))
        return SimpleNamespace(text=next(texts), language="de")

    cfg = AudioSettings(guard_ms=50, vad=VadConfig(min_speech_ms=60, end_silence_ms=150, frame_ms=30), **settings)
    m = AudioManager(bus, cfg, synthesize=lambda t: "x.wav", play=lambda w: 0.01, transcribe=transcribe,
                     source_factory=lambda: FakeSource(levels))
    return m, rec, captured


UTTERANCE = [-70] * 5 + [-20] * 8 + [-70] * 10


def test_capture_requires_operator_authorisation():
    async def scenario():
        m, _, _ = make_manager(["hallo"], UTTERANCE)
        with pytest.raises(AdapterError):
            await m.listen(2)
        m.authorize(True)
        text, lang = await m.listen(2)
        assert text == "hallo" and lang == "de"
    asyncio.run(scenario())


def test_echo_of_own_speech_is_discarded_and_listening_continues():
    async def scenario():
        m, rec, _ = make_manager(["Message from Cameron: what do dreams do with memory",
                                  "Ich glaube, Träume sortieren Erinnerungen neu."], UTTERANCE + UTTERANCE)
        m.authorize(True)
        await m.speak("Message from Cameron: what do dreams do with memory")
        await asyncio.sleep(0.1)
        text, _ = await m.listen(3)
        assert text.startswith("Ich glaube")
        reasons = [e.data.get("reason", "") for e in rec.of(EventType.AUDIO) if e.data["status"] == "discarded"]
        assert any("echo" in r for r in reasons)
    asyncio.run(scenario())


def test_half_duplex_waits_for_speech_and_guard():
    async def scenario():
        clock = {"t": 0.0}
        m, _, _ = make_manager(["ok"], UTTERANCE)
        m.clock = lambda: clock["t"]
        m.authorize(True)
        m._speaking_until = 5.0                       # Cameron still speaking
        task = asyncio.ensure_future(m.listen(10))
        await asyncio.sleep(0.1)
        assert m.state != AudioManager.LISTENING      # not listening while speech plays
        clock["t"] = 6.0
        text, _ = await asyncio.wait_for(task, 3)
        assert text == "ok"
    asyncio.run(scenario())


def test_timeout_when_no_speech():
    async def scenario():
        m, _, _ = make_manager(["never"], [-70] * 30)
        m.authorize(True)
        with pytest.raises(ResponseTimeoutError):
            await m.listen(0.5)
    asyncio.run(scenario())


def test_companion_adapter_requires_confirmation_and_speaks():
    async def scenario():
        m, _, _ = make_manager(["Bonjour Cameron"], UTTERANCE)
        a = AudioCompanionAdapter("guest", "Lumi", m)
        assert a.capabilities.requires_confirmation and a.capabilities.audio
        assert not await a.is_ready()                 # not armed yet
        m.authorize(True)
        assert await a.is_ready()
        r = await a.send_message("Hello Lumi")
        assert r.confirmed and m.last_spoken == "Hello Lumi"
        await asyncio.sleep(0.1)
        res = await a.wait_for_response(3)
        assert res.text == "Bonjour Cameron" and "audio_transcript" in res.flags
    asyncio.run(scenario())
