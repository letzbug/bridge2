"""Audio setup wizard for the Animated Companion mode (experimental)."""

from __future__ import annotations

import asyncio

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QFormLayout, QGroupBox, QHBoxLayout, QLabel, QMessageBox, QProgressBar,
    QPushButton, QSlider, QTextBrowser, QVBoxLayout,
)

from audio import device_manager as dm
from audio import wizard_ops as ops
from audio.audio_manager import AudioSettings
from audio.stt_engine import LANGUAGES, MODEL_SIZES, stt_available

TROUBLESHOOTING = """
<h3>Routing a companion through virtual audio cables (optional)</h3>
<p>EMERGENCE LAB never installs audio drivers. If you want fully isolated routing, install a virtual audio cable
yourself (for example <b>VB-CABLE</b> from vb-audio.com, or <b>VoiceMeeter</b>):</p>
<ol>
<li><b>Cameron → companion:</b> set <i>Cameron's speech output</i> here to <code>CABLE Input</code>, and select
<code>CABLE Output</code> as the microphone inside the companion app.</li>
<li><b>Companion → Cameron:</b> set the companion app's speaker output to a second cable (e.g. <code>CABLE-A Input</code>)
and select <code>CABLE-A Output</code> here as <i>companion input</i>.</li>
<li>Run the <b>routing validation</b>: if Cameron's test tone is audible on the companion input, outgoing speech would
be transcribed again – keep strict half-duplex enabled (default).</li>
</ol>
<p>Without virtual cables you can still use loudspeaker + microphone. Half-duplex then prevents Cameron's speech from
being captured, and transcripts that repeat Cameron's own words are discarded automatically.</p>
<p><b>Nothing records in the background:</b> capture only starts after you arm the microphone in the guest panel, only
from the input device selected here, and a red REC indicator is shown while recording. The whole desktop audio is
never recorded by default.</p>
<p>Speech recognition runs locally with faster-whisper. Models are downloaded only when you click Download.</p>
"""


class AudioWizard(QDialog):
    def __init__(self, parent, settings, bridge) -> None:
        super().__init__(parent)
        self.settings, self.bridge = settings, bridge
        self.cfg = AudioSettings.from_dict(settings.get("audio", {}))
        self.meter = ops.LevelMeter()
        self.setWindowTitle("Audio setup – Animated Companion (experimental)")
        self.resize(820, 760)
        lay = QVBoxLayout(self)
        ok, msg = dm.audio_available()
        stt_ok, stt_msg = stt_available()
        status = QLabel(("✓ Audio capture/playback available." if ok else f"✗ {msg}") + "<br>" +
                        ("✓ faster-whisper available." if stt_ok else f"✗ {stt_msg}"))
        status.setWordWrap(True)
        lay.addWidget(status)

        g1 = QGroupBox("Cameron's speech (text-to-speech)")
        f1 = QFormLayout(g1)
        self.engine = QComboBox()
        self.engine.addItem("Windows speech synthesis (built-in)", "sapi")
        self.engine.addItem("Piper (local, optional – configure paths in settings.json)", "piper")
        self.engine.setCurrentIndex(0 if self.cfg.tts_engine == "sapi" else 1)
        self.voice = QComboBox()
        self.voice.setEditable(True)
        self.voice.setCurrentText(self.cfg.voice)
        self.load_voices = QPushButton("Load voices")
        vrow = QHBoxLayout()
        vrow.addWidget(self.voice, 1)
        vrow.addWidget(self.load_voices)
        self.speed = QSlider(Qt.Orientation.Horizontal)
        self.speed.setRange(50, 200)
        self.speed.setValue(int(self.cfg.speed * 100))
        self.speed_label = QLabel()
        srow = QHBoxLayout()
        srow.addWidget(self.speed, 1)
        srow.addWidget(self.speed_label)
        self.output = QComboBox()
        self.tts_btn = QPushButton("Play TTS test")
        f1.addRow("Engine", self.engine)
        f1.addRow("Voice", vrow)
        f1.addRow("Speech speed", srow)
        f1.addRow("Output device", self.output)
        f1.addRow("", self.tts_btn)
        lay.addWidget(g1)

        g2 = QGroupBox("Companion voice (capture & transcription)")
        f2 = QFormLayout(g2)
        self.input = QComboBox()
        self.level = QProgressBar()
        self.level.setObjectName("Meter")
        self.level.setRange(0, 60)
        self.level.setTextVisible(False)
        self.meter_btn = QPushButton("Start level meter")
        self.meter_btn.setCheckable(True)
        mrow = QHBoxLayout()
        mrow.addWidget(self.level, 1)
        mrow.addWidget(self.meter_btn)
        self.language = QComboBox()
        for k, v in LANGUAGES.items():
            self.language.addItem(v, k)
        self.language.setCurrentIndex(max(0, self.language.findData(self.cfg.language)))
        self.model = QComboBox()
        for k, v in MODEL_SIZES.items():
            self.model.addItem(f"{k} ({v})", k)
        self.model.setCurrentIndex(max(0, self.model.findData(self.cfg.whisper_model)))
        self.download_btn = QPushButton("Download model…")
        mdrow = QHBoxLayout()
        mdrow.addWidget(self.model, 1)
        mdrow.addWidget(self.download_btn)
        self.manual = QCheckBox("Manual recording (stop with the Stop-generation button instead of silence detection)")
        self.manual.setChecked(self.cfg.manual_recording)
        tests = QHBoxLayout()
        self.mic_btn = QPushButton("Microphone test (3 s, plays back)")
        self.comp_btn = QPushButton("Companion input test (5 s)")
        self.stt_btn = QPushButton("Transcription test (5 s)")
        for b in (self.mic_btn, self.comp_btn, self.stt_btn):
            tests.addWidget(b)
        f2.addRow("Companion input", self.input)
        f2.addRow("Level", mrow)
        f2.addRow("Language", self.language)
        f2.addRow("Whisper model", mdrow)
        f2.addRow("", self.manual)
        f2.addRow(tests)
        lay.addWidget(g2)

        g3 = QGroupBox("Routing validation")
        f3 = QVBoxLayout(g3)
        self.route_btn = QPushButton("Play test tone on Cameron's output and listen on the companion input")
        self.isolated = QCheckBox("Isolated routing validated – allow listening while Cameron speaks (not recommended)")
        self.isolated.setChecked(self.cfg.isolated_routing_validated)
        self.isolated.setEnabled(self.cfg.isolated_routing_validated)
        f3.addWidget(self.route_btn)
        f3.addWidget(self.isolated)
        lay.addWidget(g3)

        self.result = QLabel()
        self.result.setWordWrap(True)
        lay.addWidget(self.result)
        help_view = QTextBrowser()
        help_view.setHtml(TROUBLESHOOTING)
        help_view.setOpenExternalLinks(False)
        lay.addWidget(help_view, 1)
        row = QHBoxLayout()
        row.addStretch(1)
        save = QPushButton("Save")
        save.setObjectName("Primary")
        close = QPushButton("Close")
        row.addWidget(save)
        row.addWidget(close)
        lay.addLayout(row)

        self._fill_devices()
        self._speed_changed()
        self.speed.valueChanged.connect(self._speed_changed)
        self.load_voices.clicked.connect(self._voices)
        self.tts_btn.clicked.connect(self._tts)
        self.meter_btn.toggled.connect(self._toggle_meter)
        self.mic_btn.clicked.connect(lambda: self._run(lambda: ops.mic_test(self._in(), self._out()), "Microphone test"))
        self.comp_btn.clicked.connect(lambda: self._run(lambda: ops.companion_input_test(self._in()),
                                                        "Companion input test"))
        self.stt_btn.clicked.connect(lambda: self._run(lambda: ops.stt_test(self._collect()), "Transcription test"))
        self.download_btn.clicked.connect(self._download)
        self.route_btn.clicked.connect(self._routing)
        save.clicked.connect(self._save)
        close.clicked.connect(self.reject)
        self.timer = QTimer(self)
        self.timer.setInterval(100)
        self.timer.timeout.connect(self._meter_tick)
        self.timer.start()
        for w in (self.mic_btn, self.comp_btn, self.meter_btn, self.route_btn):
            w.setEnabled(ok)
        self.stt_btn.setEnabled(ok and stt_ok)
        self.download_btn.setEnabled(stt_ok)

    # ---------------------------------------------------------------------------------
    def _fill_devices(self) -> None:
        self.output.addItem("(system default)", "")
        for d in dm.outputs():
            self.output.addItem(d.label + ("  · virtual" if dm.looks_virtual(d.name) else ""), d.name)
        self.input.addItem("(select the companion input)", "")
        for d in dm.inputs():
            self.input.addItem(d.label + ("  · virtual" if dm.looks_virtual(d.name) else ""), d.name)
        self.output.setCurrentIndex(max(0, self.output.findData(self.cfg.output_device)))
        self.input.setCurrentIndex(max(0, self.input.findData(self.cfg.input_device)))

    def _in(self) -> str:
        return self.input.currentData() or ""

    def _out(self) -> str:
        return self.output.currentData() or ""

    def _speed_changed(self) -> None:
        self.speed_label.setText(f"{self.speed.value() / 100:.2f}×")

    def _collect(self) -> AudioSettings:
        c = self.cfg
        c.tts_engine = self.engine.currentData()
        c.voice = self.voice.currentText().strip()
        c.speed = self.speed.value() / 100
        c.output_device, c.input_device = self._out(), self._in()
        c.language = self.language.currentData()
        c.whisper_model = self.model.currentData()
        c.manual_recording = self.manual.isChecked()
        c.isolated_routing_validated = self.isolated.isChecked()
        return c

    def _run(self, fn, title: str) -> None:
        self.result.setText(f"{title} running …")

        async def job():
            return await asyncio.to_thread(fn)
        self.bridge.call(job, lambda r: self.result.setText(f"{title}: {r}"),
                         lambda m: self.result.setText(f"{title} failed: {m}"))

    def _voices(self) -> None:
        from audio.tts_engine import WindowsSapiTTS

        async def job():
            return await asyncio.to_thread(lambda: WindowsSapiTTS().voices())

        def done(voices):
            current = self.voice.currentText()
            self.voice.clear()
            for v in voices:
                self.voice.addItem(v.label, v.name)
            i = self.voice.findData(current)
            if i >= 0:
                self.voice.setCurrentIndex(i)
            self.result.setText(f"{len(voices)} voice(s) found.")
        self.bridge.call(job, done, lambda m: self.result.setText(f"Voices: {m}"))

    def _tts(self) -> None:
        cfg = self._collect()
        if self.voice.currentData():
            cfg.voice = self.voice.currentData()
        self._run(lambda: ops.tts_test(cfg, "Hello, this is Cameron. Hallo, hier ist Cameron. Bonjour, ici Cameron."),
                  "TTS test")

    def _toggle_meter(self, on: bool) -> None:
        try:
            if on:
                self.meter.start(self._in())
                self.meter_btn.setText("Stop level meter")
            else:
                self.meter.stop()
                self.meter_btn.setText("Start level meter")
        except Exception as exc:  # noqa: BLE001
            self.meter_btn.setChecked(False)
            self.result.setText(f"Level meter: {exc}")

    def _meter_tick(self) -> None:
        self.level.setValue(int(max(0.0, min(60.0, self.meter.level_db + 60))) if self.meter.running else 0)

    def _download(self) -> None:
        size = self.model.currentData()
        if QMessageBox.question(self, "Download model",
                                f"Download the Whisper model '{size}' ({MODEL_SIZES[size]}) from Hugging Face into "
                                "the local data folder? This is the only network request the audio module makes."
                                ) != QMessageBox.StandardButton.Yes:
            return
        self._run(lambda: ops.download_model(size), "Model download")

    def _routing(self) -> None:
        def done(r):
            leaked = r.get("leaked")
            self.result.setText(f"Routing validation: {r}. " + (
                "The tone WAS audible on the companion input → keep strict half-duplex." if leaked else
                "The tone was not detected on the companion input. You may enable isolated routing."))
            self.isolated.setEnabled(not leaked)
            if leaked:
                self.isolated.setChecked(False)

        async def job():
            return await asyncio.to_thread(lambda: ops.routing_test(self._out(), self._in()))
        self.result.setText("Routing validation running …")
        self.bridge.call(job, done, lambda m: self.result.setText(f"Routing validation failed: {m}"))

    def _save(self) -> None:
        cfg = self._collect()
        if self.voice.currentData():
            cfg.voice = self.voice.currentData()
        data = self.settings.get("audio", {})
        data.update({k: getattr(cfg, k) for k in ("tts_engine", "voice", "speed", "language", "output_device",
                                                  "input_device", "whisper_model", "manual_recording",
                                                  "isolated_routing_validated")})
        self.settings.set("audio", data)
        self.settings.save()
        self.bridge.controller.audio.settings = AudioSettings.from_dict(data)
        self.result.setText("Audio settings saved.")

    def done(self, r: int) -> None:  # noqa: D401 - Qt override
        self.meter.stop()
        super().done(r)
