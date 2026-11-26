# Live validation checklist (ChatGPT first, then Gemini)

None of the real provider adapters were tested against the live websites during development. Use this checklist
on your own machine and record the result in `providers.user.json` (or keep notes in the session *Notes*).

## 0. Offline pipeline check (5 minutes, no account)
1. Settings → Browser & windows → tick **Pipeline test**.
2. Open both browsers (backend *Managed Firefox*), click **Diagnose** on both cards: all rows must be ✓/○.
3. Transfer mode *Automatic*, 2 rounds, **Start**: the run must complete with 4 responses.
4. Untick *Pipeline test* again.

## 1. Login and readiness
- [ ] Host card → Browser *Managed Firefox* → **Open browser** → log in to ChatGPT manually.
- [ ] Close and reopen the application: the login is still present (persistent dedicated profile).
- [ ] Review OpenAI's current terms. Only then: Settings → Providers → ChatGPT → tick the acknowledgement.
      (Diagnostics and automated adapters read the page programmatically and stay disabled without it.)
- [ ] Authentication row shows *Logged in (detected)* (it is only checked once automation is enabled).

## 2. Diagnostics on an existing chat (contains earlier messages)
- [ ] **Diagnose**: Message input ✓, Send control ✓ (may show ✗ while the input is empty – type one letter and run
      again), Assistant message container ✓, Latest completed response shows the last answer.
- [ ] **Highlight** each row and check that the outlined element is the right one.

## 3. Generation signals
- [ ] Send a long prompt manually (“write 30 numbered lines”), and run **Diagnose** while it is streaming:
      Generation status ✓ and Stop control ✓ must be detected.
- [ ] After completion: Completion indicator ✓ (if configured).

## 4. Manual-confirmation session (Cameron ↔ Clipboard guest)
- [ ] Guest browser backend *Installed Firefox* (clipboard), transfer mode *Manual*, 2 rounds, **Start**.
- [ ] The initial prompt appears in ChatGPT exactly once, and the session moves to *Waiting for host*.
- [ ] The extracted response matches what ChatGPT shows (lists, code blocks). No old messages are offered.
- [ ] Edit the text before **Send**: the transcript keeps both the original and the edited version.

## 5. Failure behaviour
- [ ] Close the ChatGPT window while waiting → state **ERROR**, no retries. Reopen it, then **Resume**.
- [ ] Set the max wait to 15 s with a long prompt → timeout pause. **Keep waiting** must not resend.
- [ ] Press **EMERGENCY STOP** while a transfer is pending → nothing is submitted afterwards.

## 6. Repeat for Gemini
Google may refuse sign-in inside the managed browser. If so, keep Gemini on *Installed Firefox + Clipboard*. That
is expected behaviour, not a bug.

If a row fails, add an override in Settings → Providers (see README section 6) and repeat the diagnostic. Once a
provider passes steps 1–5, you can set `"validation": {"status": "validated", "notes": "…, <date>"}` in its
local override.
