# EMERGENCE LAB – AI Conversation Bridge · v0.1.1

**Built by Frank G – IBM Certified AI Developer**

A local desktop research environment in which two AI assistants talk to each other **through their native
browser interfaces** – with their own conversation history, personalisation and memory features – instead of
through LLM APIs. The left browser is the permanent host **Cameron (ChatGPT)**, the right browser a configurable
guest. A control panel relays, records and safeguards the conversation.

> **Research note.** The application records observable conversation behaviour. It does not and cannot establish
> consciousness, subjective experience or hidden model states, and it never infers memory activity.

---

## Contents

1. [Quick facts](#1-quick-facts)
2. [Installation: portable ZIP or from source](#2-installation-windows-11)
3. [First launch](#3-first-launch)
4. [Browser backends, authentication and persistent profiles](#4-browser-backends-authentication-and-persistent-profiles)
5. [Guest selection](#5-guest-selection)
6. [Provider validation (adapter diagnostics)](#6-provider-validation-adapter-diagnostics)
7. [Transfer modes: manual, automatic, clipboard](#7-transfer-modes)
8. [Human intervention, safety and error handling](#8-human-intervention-safety-and-error-handling)
9. [Research recording and exports](#9-research-recording-and-exports)
10. [Audio setup (Animated Companion, experimental)](#10-audio-setup-animated-companion-experimental)
11. [Privacy and security](#11-privacy-and-security)
12. [Provider terms of service](#12-provider-terms-of-service)
13. [Troubleshooting](#13-troubleshooting)
14. [Adding new providers](#14-adding-new-providers)
15. [Architecture, Selenium evaluation, tests](#15-architecture-selenium-evaluation-tests)
16. [Known limitations](#16-known-limitations)
17. [Kurzanleitung (Deutsch)](#17-kurzanleitung-deutsch)
18. [Building the portable distribution (PyInstaller, GitHub Actions)](#18-building-the-portable-distribution)

---

## 1. Quick facts

| | |
|---|---|
| Platform | Windows 11 x64 (primary). macOS/Linux from source: `install.sh`, `start.sh` |
| Portable edition | Extract the ZIP, double-click **`EmergenceLab.exe`** – no installation, no admin rights, no Python, no Node.js |
| From source | Python 3.11–3.13 (3.12 recommended), PySide6, Playwright · no Docker, no Node.js, no API keys |
| Works immediately | **Demo mode** and **Clipboard mode** – no browser automation, no accounts needed |
| Needs live validation | Every real provider adapter (ChatGPT, Gemini, Claude, Grok, Mistral, Vibe, Custom) |
| Local data | `%LOCALAPPDATA%\EmergenceLab` (settings, sessions database, logs, exports, profiles, optional browser runtime) – never inside the application folder |
| Defaults | Manual confirmation · attributed transfer · 10 rounds · recording on |

---

## 2. Installation (Windows 11)

### 2.1 Portable edition (recommended – nothing to install)

1. Download `EmergenceLab-0.1.1-win-x64.zip` (or `…-win-x64-audio.zip` with the experimental audio companion
   packages) from the GitHub Actions run or release (section 18).
2. *Optional, avoids the SmartScreen prompt:* right-click the ZIP → **Properties** → tick **Unblock** → OK.
3. Extract the **whole** ZIP to any folder you can write to, e.g. `C:\Users\<you>\Apps\`.
4. Double-click **`EmergenceLab.exe`**. The program is not code-signed. If Windows shows *“Windows protected your
   PC”*, click **More info → Run anyway**.

The folder contains the bundled Python runtime, Qt/PySide6 and the Playwright driver (with its own Node.js
runtime). Nothing is written into it. All data goes to `%LOCALAPPDATA%\EmergenceLab`.

| In the ZIP | Purpose |
|---|---|
| `EmergenceLab.exe` | the application (double-click) |
| `EmergenceLab-console.exe` | the same program with a console window, for diagnostics: `--self-check`, `--gui-selftest`, `--browser-selftest`, `--install-browser` |
| `_internal\` | bundled runtime, Qt, Playwright driver, shipped configuration and assets (read-only) |
| `READ-ME-FIRST.txt`, `README.md`, `CHANGELOG.md`, `BUILD-INFO.txt` | documentation and build details |

**First start without the optional browser runtime:** both participants start with your **installed Firefox**
(dedicated profiles, clipboard workflow), or with *No browser* if no Firefox is found. Demo mode works as well.
Automated adapters need Playwright's own Firefox build (~80–100 MB). Install it whenever you want under
**Settings → Browser & windows → Browser runtime → Manage… → Install**. It is downloaded from Playwright's
servers into `%LOCALAPPDATA%\EmergenceLab\browser-runtime`, and *Remove runtime* deletes it again.

**Portable data mode (USB stick):** create an empty file `EmergenceLab.portable` next to `EmergenceLab.exe`.
Data then goes to a folder `EmergenceLab-Data` **next to** (never inside) the application folder. To update,
replace the application folder. Your data stays where it is.

**Audio:** the standard ZIP contains no audio packages, so text mode works everywhere. The `-audio` ZIP adds
numpy, sounddevice and faster-whisper. Whisper models are still downloaded only on request (section 10).

### 2.2 From source (developers)

1. Install **Python 3.12** from <https://www.python.org/downloads/windows/> and tick **“Add python.exe to PATH”**.
2. Unzip the source project anywhere, e.g. `C:\Users\<you>\EmergenceLab`.
3. Double-click **`install.bat`**. It
   * finds Python ≥ 3.11 (via the `py` launcher or `python`),
   * creates a local virtual environment `.venv` in the application folder,
   * installs PySide6 and Playwright,
   * asks whether to install **Playwright's managed Firefox build** (~80–100 MB; needed only for automated adapters),
   * creates the local data folders and runs a headless self-check.

   No administrator rights are needed. Non-interactive variants: `install.bat /browser` or `install.bat /nobrowser`.
4. Optional audio companion support: **`install_audio.bat`** (see section 10).
5. Start with **`start.bat`**. To build the portable edition yourself, run **`build_portable.bat`** (section 18).

## 3. First launch

Double-click **`EmergenceLab.exe`** (portable) or **`start.bat`** (source; `start.bat --demo` for demo mode).
No conversation ever starts automatically.

**Recommended first steps**

1. Click **Demo mode** in the header → **Start**. Two clearly labelled *simulated* participants talk. Try Pause,
   Resume, Next turn, Human intervention, Emergency stop and Export. The *Demo* tab offers scenarios for loop
   detection, timeouts and uncertain submissions.
2. Switch Demo mode off. Set **Transfer mode → Clipboard** and try a real conversation without any automation
   (section 7.3).
3. Optional, for automation: **Settings → Browser & windows → Pipeline test** uses the local mock chat page for both
   participants, so you can validate the complete browser pipeline offline before touching a real account.

Useful command-line options: `--demo`, `--data-dir <folder>`, `--verbose`. Diagnostics (with
`EmergenceLab-console.exe` in the portable edition): `--self-check` (no GUI, no network), `--gui-selftest`,
`--browser-selftest` (managed Firefox against the local mock page), `--install-browser`, `--report <file.json>`.

---

## 4. Browser backends, authentication and persistent profiles

Each participant card has a **Browser** selector:

| Backend | What it is | Automation |
|---|---|---|
| **Playwright-managed Firefox** | Playwright's *own* Firefox build, launched with a dedicated persistent profile per participant and provider: `profiles\managed-firefox\host-chatgpt`, `guest-gemini`, … | yes (after you enable it per provider) |
| **Installed Firefox** | *Your* installed Firefox program, started with a **separate dedicated profile** (`profiles\standard-firefox\…`, `-no-remote -new-instance`) | **never** – clipboard workflow |
| **No browser** | Use any window you like | never – clipboard workflow |

Important distinctions:

* Playwright's Firefox is **not** your installed Firefox. The application **cannot attach** to Firefox windows you
  opened yourself and it **never reads, modifies or deletes your normal Firefox profile**.
* **Log in manually** in the opened window, the first time only. The login is stored in the dedicated profile and
  reused on later launches. The application never asks for passwords.
* No CAPTCHA bypass, stealth mode or fingerprint manipulation is used. If a provider shows a human-verification
  check, solve it yourself. If a provider refuses to sign in inside an automated browser (Google commonly shows
  *“This browser or app may not be secure”*), use **Installed Firefox + Clipboard mode** for that participant.
* **Window layout:** *Open both browsers* puts Cameron left and the guest right, and opens the compact always-on-top
  control bar in the remaining column (wide screens) or floating on top (narrow screens). Positioning uses the
  Firefox `xulstore.json` of the dedicated profile plus Windows window placement, both best effort. Each
  dedicated profile also remembers its own window position. Turn automatic positioning off in
  *Settings → Browser & windows*.
* **Stopping a conversation never closes browser windows.** Managed windows close when the application exits;
  installed-Firefox windows stay open.
* *Settings → General → Delete dedicated browser profiles* logs you out of all dedicated profiles.

## 5. Guest selection

Gemini · Claude · Grok · Mistral Le Chat · Vibe · Animated Companion · Custom. Set a **display name** (e.g. *Gem*).
For **Vibe** and **Custom**, enter the website URL in the guest card, because no default URL is shipped for them.
**Animated Companion** uses audio instead of text (section 10).

The host is always **Cameron (ChatGPT)**. Model names, memory settings and existing/new conversation can be
recorded in the *Research* tab as **user-reported** information.

## 6. Provider validation (adapter diagnostics)

Every adapter except the local mock page is **unvalidated**: its selectors are *candidates* based on publicly
known page structure, not verified against the live sites. Validate them on your machine:

1. Open the participant's browser with the **managed** backend, log in, open a chat. Enable automation for the
   provider under *Settings → Providers* (diagnostics read the page programmatically, so they need it too).
2. Click **Diagnose**. The diagnostic table shows whether the following can be detected: **message input, send
   control, assistant message container, generation status, stop control, latest completed assistant response**
   (with preview). **Highlight** outlines the matched element in the browser for 4 seconds.
3. Send one message manually in that chat and run **Diagnose** again, so the response container and completion
   indicator can be verified.
4. If something is missing, open **Adapter… / Edit selectors** (Settings → Providers) and add a JSON override, for
   example:

```json
{ "selectors": { "input": ["div#prompt-textarea"], "assistant_message": ["[data-message-author-role=\"assistant\"]"] },
  "stability_ms": 2000 }
```

Selector syntax: CSS (default) · `role:<role>` · `role:<role>:<name regex>` · `text:<regex>` · `xpath=<expr>`.
Prefer semantic attributes (`data-testid`, `aria-label`, roles) over generated class names. Overrides are stored in
`%LOCALAPPDATA%\EmergenceLab\providers.user.json`; *Reset* restores the shipped defaults. A step-by-step checklist is
in [`docs/LIVE_VALIDATION.md`](docs/LIVE_VALIDATION.md).

## 7. Transfer modes

### 7.1 Manual confirmation (default)
After each completed response, the panel shows the extracted text and its destination. You can **edit**, **Send**,
**Skip** (opens human intervention; *Resume previous conversation* offers the transfer again) or **Copy** it. The
original response is always stored unchanged. The edited text is stored separately as the forwarded text.

### 7.2 Automatic transfer
Completed responses are forwarded automatically within the configured limits. Requirements, checked at start:
automation enabled for the provider (Settings → Providers) **and** a passed diagnostic for each automated
participant in this session. Even in automatic mode the engine falls back to confirmation when:
* completion could only be inferred from a stable-text period (low confidence),
* a message comes from an audio transcript,
* a repeated or near-identical response or an oversized message was detected (the session pauses with a warning).

Completion detection combines **generation controls** (stop button / streaming markers), **assistant message
identity** (count + message id vs. a baseline captured before each send), **text changes**, a **configurable
stability period** and **provider completion indicators** (e.g. copy/feedback buttons). Old messages of an
existing conversation are never forwarded.

### 7.3 Clipboard mode (provider-independent, no automation)
Works with any website and keeps working when every automated adapter fails:

1. The panel shows the text for the next participant → **Copy to clipboard** (`Ctrl+Shift+C`), paste it into that
   participant's window and send it there → **I pasted and sent it** (`Ctrl+Shift+Enter`).
2. When the reply is complete, copy it in the browser → **Import from clipboard** (`Ctrl+Shift+V`), check the
   speaker, **Accept reply**.

The clipboard is only read or written on these explicit actions. It is never monitored. Shortcuts are configurable
and work while an EMERGENCE LAB window is focused (they are not global system hooks).

### Templates
Research sessions use **attributed transfer** by default: `Message from [speaker]:\n\n[original_message]`. Untick
attribution for **raw transfer** (the message only). Placeholders inside AI messages are never expanded. Human
messages use their own template (default: the plain text).

## 8. Human intervention, safety and error handling

* **Human intervention** pauses automatic forwarding. Choose *Send to Cameron*, *Send to Guest*, *Send to both*
  (sent one after another, never simultaneously) or *Resume previous conversation*. If a participant is still
  generating, the response is recorded first, or you can explicitly *Cancel … generation*. Human messages are marked
  as such in the transcript.
* **Emergency stop** (`Ctrl+Shift+X`) closes a thread-safe submission gate immediately. Every adapter checks it
  right before the actual click, Enter key or audio playback. Pending transfers are cancelled. Browsers stay open.
  A stopped session never restarts by itself.
* **Pause** lets a response that is currently being generated finish and records it, but forwards nothing.
  **Next turn** advances exactly one response.
* **Timeouts** pause the session. *Keep waiting* continues with the original baseline and never resends.
* **Uncertain submission**: if no user message, generation start or input reset is observed after sending, the
  session asks you to check the window: *It was submitted* / *send again*. It never resends automatically.
* **Loops**: exact duplicates, near duplicates (3-gram similarity) and echoes of the received message pause the
  session with a warning.
* **Limits**: maximum rounds (default 10), message-size warning, minimum interval and hourly cap per participant,
  provider rate-limit banners, browser closure, login interruption. None of them triggers a retry loop.

A **round** is one completed response from each participant.

## 9. Research recording and exports

With recording enabled, each session is stored in `%LOCALAPPDATA%\EmergenceLab\research\sessions.sqlite3`:
session id, title, research question, start/end, providers, user-reported model names and memory settings,
observed conversation ids, initial prompt, transfer mode, every turn with speaker, original and forwarded text,
human interventions, response duration, errors and notes. Facts are tagged **observed / user_reported /
unavailable**.

**Sessions** (header) lets you view, export, delete, delete all, and compare selected sessions (rounds, response
lengths and durations, loop warnings, edits, interventions). Use the *Experiment* and *Condition* fields to compare
existing vs. new conversation, memory on/off (user-reported), different guests, different initial prompts, or raw
vs. attributed transfer. The application never changes provider settings.

**Export** formats: TXT, Markdown, JSON, CSV, standalone HTML. HTML exports escape all content and forbid scripts.
Markdown fences cannot be broken by message content. CSV cells are protected against formula injection. Loading a
transcript never resumes or replays a conversation. Cookies, tokens and passwords are not part of the data model,
so they can never be exported.

## 10. Audio setup (Animated Companion, experimental)

1. Run `install_audio.bat` (numpy, sounddevice, faster-whisper; packages ~150–250 MB; optional Whisper model:
   tiny ~75 MB, **base ~145 MB**, small ~465 MB, medium ~1.5 GB).
2. Guest = **Animated Companion** → **Audio setup…**: choose the TTS engine (Windows speech, built in, or Piper),
   voice, speed and **output device** for Cameron's speech, the **companion input** device, language
   (German / English / French / automatic) and Whisper model. Then run the microphone, TTS, companion-input,
   transcription and **routing validation** tests. A live level meter is included.
3. **Arm microphone** in the guest card. Capture only runs while armed and a red **REC** indicator is shown.

**Routing (optional, never installed automatically):** with VB-CABLE or VoiceMeeter, route Cameron's speech to
`CABLE Input` (the companion's microphone = `CABLE Output`). Route the companion's speaker to a second cable and
select that cable's output as *companion input*.

**Feedback prevention:** half duplex (no capture while Cameron speaks plus a guard interval), echo rejection of
transcripts that repeat Cameron's words, explicit listening/speaking indicators, and manual recording mode. Every
transcript is shown for confirmation before it is forwarded. Only the selected input is captured, never the whole
desktop audio by default. Text mode works without any audio packages.

## 11. Privacy and security

* Local-first: no telemetry, no analytics, no hidden network requests, no cloud storage. The only external traffic
  is what the AI websites load in their windows, plus the dependency and model downloads you start yourself.
* Logs (`logs\emergence-lab.log`) record events and errors, **not message contents**.
* **AI responses are untrusted text.** They are only stored, displayed (escaped), exported (escaped) or passed as a
  value to a browser input or to TTS. They are never executed or parsed for commands. JavaScript is called with the
  text as an argument, never by string concatenation. An AI message cannot change settings, start programs, read
  files, access credentials, change the guest, override the round limit, disable the emergency stop or activate
  audio capture. Research controls belong to the human operator only.

## 12. Provider terms of service

The consumer terms of several providers restrict automated or programmatic access to their chat interfaces. At
the time of writing, OpenAI's terms prohibit programmatic output extraction, and Anthropic's consumer terms only
allow automated access via API keys. Terms change, so check the current versions yourself. For this reason
automated interaction is **disabled per provider until you confirm** under *Settings → Providers* that you have
reviewed the provider's current terms. **Clipboard mode involves no automation at all** and is the safe default
for any provider whose terms you are unsure about. Breaking provider terms can put the account and its
conversation history at risk.

## 13. Troubleshooting

| Symptom | What to do |
|---|---|
| `install.bat`: Python not found | Install Python 3.12 with “Add to PATH”, or use the `py` launcher. Disable the Microsoft Store `python` alias (Settings → Apps → Advanced app settings → App execution aliases). |
| PySide6 install fails on Python 3.14 | Use Python 3.12 or 3.13 and delete `.venv`, then run install.bat again. |
| “Playwright's managed Firefox build is not installed” | `.venv\Scripts\python -m playwright install firefox` |
| “Profile is already in use” | Close the other window that uses this dedicated profile. |
| Google / provider refuses sign-in in the managed browser | Use *Installed Firefox* + *Clipboard* mode for that participant. |
| Diagnose shows ✗ for input / send / messages | The site changed or uses another UI language → add a selector override (section 6). |
| Session pauses with “completion uncertain” | No generation or completion signal was detected → validate the `generating` / `completion_indicator` selectors. |
| “Submission uncertain” | Look at the window. Confirm *It was submitted* or *send again*. Then check the `user_message` selectors. |
| Windows not positioned | Positioning is best effort. Move the windows yourself; each dedicated profile remembers its position. |
| Startup error | Portable: `EmergenceLab-console.exe --self-check`. Source: `start.bat --self-check`. Then check `%LOCALAPPDATA%\EmergenceLab\logs\emergence-lab.log` (hard crashes: `crash.log`). |
| “Windows protected your PC” | Unsigned program: *More info → Run anyway*, or unblock the ZIP before extracting (section 2.1). |
| Antivirus quarantines `EmergenceLab.exe` | PyInstaller executables are occasionally flagged as false positives. Restore the file / add an exception, or run from source. |
| Portable app does not start from inside the ZIP | Extract the whole ZIP first – the `_internal` folder must sit next to the exe. |
| No audio devices listed | Run `install_audio.bat`; check Windows privacy settings for microphone access. |

## 14. Adding new providers

*Selectors only (no code):* use a local override (section 6).

*A new provider:*

1. Add an entry to `config/providers.json` → `providers` (copy `custom`): `label`, `url`, `host_patterns`,
   `selectors` (`input`, `send_button`, `assistant_message`, `user_message`, `generating`, `stop_button`,
   `completion_indicator`, `login_required`, `error_banner`), `message_id_attributes`, `login_url_patterns`,
   `conversation_id_patterns`, `input_method` (`fill` / `insert_text`), `send_method` (`click` / `enter` /
   `click_or_enter`), `stability_ms`, `automation`, `validation`.
2. Create `adapters/<id>.py` with a subclass of `SelectorAdapter` (override `_extract`, `wait_for_response` …
   for provider-specific behaviour).
3. Register it in `adapters/registry.py` → `adapter_class_for` and, for a guest, in `GUEST_CHOICES`.
4. Validate it with the diagnostics and add a fixture-based test (see `tests/test_mock_browser.py`).

Adapters implement `BaseProviderAdapter` (`connect`, `is_ready`, `get_conversation_state`, `send_message`,
`wait_for_response`, `get_latest_response`, `stop_generation`, `disconnect`) and expose capability flags.

## 15. Architecture, Selenium evaluation, tests

```
main.py                 entry point (GUI, --self-check, --smoke-test)
app/                    engine (step machine), state machine, controller, events, gate, loop detection,
                        templates, security, settings, async runner, clipboard workflow
adapters/               base interface, selector adapter, one module per provider, demo, clipboard, registry
browser/                page-driver interface, Playwright driver, managed Firefox, installed Firefox, window manager
audio/                  TTS, STT, devices, voice activity, half-duplex manager, companion adapter, wizard ops
research/               transcript model, SQLite store, exports, experiment metrics
ui/                     PySide6 dashboard, compact bar, dialogs, styles, icons, Qt thread bridge
config/                 providers.json (selector candidates), defaults.json
assets/mock_chat.html   local mock chat page for offline pipeline validation
tests/                  pytest suite, fake adapters, fake page, Qt stand-in for structural GUI checks
```

The engine runs in a dedicated asyncio thread. The GUI never blocks. Events reach the GUI through queued Qt
signals.

**Selenium evaluation.** Selenium + geckodriver could drive the *installed* Firefox with a dedicated profile. It
is not implemented (v0.1.x). It adds a geckodriver download and gives no capability Playwright lacks for this
use case, and a Marionette-controlled Firefox is just as detectable as an automated browser. Adapters talk to a
backend-neutral `PageDriver` interface (`browser/page_driver.py`), so a Selenium driver can be added without
changing any adapter.

**Tests.** `.venv\Scripts\pip install -r requirements-dev.txt`, then `.venv\Scripts\python -m pytest tests`.
`python tests\gui_smoke.py` runs the real GUI self-test on your machine (`EmergenceLab-console.exe --gui-selftest` in
the portable edition). The suite covers conversation
rounds, alternating speakers, round limits, manual confirmation, automatic transfer with mock providers, pause during
generation, emergency stop (including from another thread), duplicate/loop detection, browser disconnection,
timeouts, existing-conversation baselines, uncertain submissions, exports, malicious instructions inside AI
messages, HTML sanitisation, the clipboard fallback, the audio logic and a real-DOM pipeline test against the
local mock page.

## 16. Known limitations

* **No live provider testing was performed during development** (no account access). All real provider adapters
  need live validation. Grok, Mistral, Vibe and Custom use low-confidence generic selectors.
* Some providers may block sign-in or show verification checks in automated browsers. The application does not work
  around this. Clipboard mode is the fallback.
* Text extraction produces light Markdown (paragraphs, lists, code fences, inline code). Rich elements (tables,
  images, canvases, formulas) may lose structure.
* Window positioning is best effort (xulstore + Win32). Managed browser windows close when the application exits.
* The audio companion mode is experimental and unverified with a real companion.
* Keyboard shortcuts are application-level, not global.
* The portable executables are not code-signed (SmartScreen prompt on first start).
* The portable build is produced by the GitHub Actions workflow on Windows. It cannot be built on Linux or macOS.

## 17. Kurzanleitung (Deutsch)

**Portable Version (empfohlen):** `EmergenceLab-0.1.1-win-x64.zip` komplett entpacken, dann
**`EmergenceLab.exe`** doppelklicken. Keine Installation, keine Administratorrechte, kein Python, kein Node.js.
Die Windows-Warnung „Der Computer wurde durch Windows geschützt“ bestätigst du mit *Weitere Informationen →
Trotzdem ausführen*, denn das Programm ist nicht signiert. Die optionale Firefox-Runtime für Automatisierung
installierst du unter *Settings → Browser & windows → Browser runtime*. Ab dann geht es weiter mit Schritt 3.

**Aus dem Quellcode:**

1. **Python 3.12** installieren (Häkchen bei „Add python.exe to PATH“).
2. ZIP entpacken und **`install.bat`** doppelklicken. Die Frage nach dem *Playwright-Firefox* nur mit **J/Y**
   beantworten, wenn du automatisierte Adapter nutzen willst.
3. **`start.bat`** starten (portable: `EmergenceLab.exe`). Zuerst **Demo mode** einschalten, dann **Start**. Die Teilnehmer sind klar als
   *simuliert* markiert.
4. Echte Unterhaltung ohne Automatisierung: Transfer mode **Clipboard**. Text kopieren, ins Chatfenster einfügen
   und dort senden, dann *I pasted and sent it*. Die Antwort im Browser kopieren, dann *Import from clipboard* und
   *Accept reply*.
5. Mit Automatisierung: Browser **Managed Firefox** wählen, **Open browser**, dich **selbst einloggen** und
   **Diagnose** ausführen. Erst danach unter *Settings → Providers* die Automatisierung bestätigen (vorher die
   Nutzungsbedingungen des Anbieters prüfen!).
6. **EMERGENCY STOP** (`Strg+Umschalt+X`) blockiert sofort jede automatische Übermittlung. Die Browserfenster
   bleiben offen.
7. Daten liegen lokal in `%LOCALAPPDATA%\EmergenceLab`. Kein Tracking, keine Cloud. Exporte als TXT, Markdown, JSON,
   CSV oder HTML.

## 18. Building the portable distribution

* **GitHub Actions:** push the project to a GitHub repository. `.github/workflows/windows-portable.yml` runs on every
  push to `main`, on pull requests, on tags `v*` and manually (*Actions → Windows portable build → Run workflow*).
  Download the ZIPs from the run's **Artifacts** section. A tag such as `v0.1.1` also creates a **draft release**
  with both ZIPs attached.
* **Locally on Windows:** `build_portable.bat` (or `build_portable.bat audio`). This needs Python 3.11+ on the
  build computer only. The output goes to `dist\EmergenceLab-0.1.1-win-x64.zip`.

Details, the verification steps of the workflow and the build layout are described in
[`docs/PORTABLE.md`](docs/PORTABLE.md).

---

© frankG × Cameron · EMERGENCE LAB · v0.1.1
