# Manual screen-reader and Safari checklist

Closes two items of `FRONTEND_UX_IMPROVEMENT_PLAN.md` §9.1 that no automated test can: **item 3**
(NVDA and VoiceOver pass) and the real-Safari half of **item 6**. A person runs this once before a
public launch, and again after a change to the shell, the forms, the audio player or the dialogs.
A private beta may go ahead without it; a public launch should not.

Automated coverage already exists (axe on every route in both themes, keyboard-only flows, focus
rings, 320 px reflow, forced colours). This list covers what only a human and a real assistive
technology can judge: **does what is spoken make sense, in the right order, at the right time?**

## 1. Set up

### Test matrix

Run every section of Part A on at least the first two rows, and Part B on the Safari rows.

| #   | Platform             | Browser           | Screen reader                        | Notes                                     |
| --- | -------------------- | ----------------- | ------------------------------------ | ----------------------------------------- |
| 1   | Windows 10/11        | Firefox (current) | NVDA (free, nvaccess.org)            | The most common pairing; do this first    |
| 2   | Windows 10/11        | Chrome (current)  | NVDA                                 | Different live-region timing from Firefox |
| 3   | macOS (current)      | Safari            | VoiceOver (Cmd+F5)                   | Safari part B runs here too               |
| 4   | iPhone (current iOS) | Safari            | VoiceOver (Settings > Accessibility) | Touch gestures; Part B runs here too      |
| 5   | Android              | Chrome            | TalkBack                             | Optional                                  |

Record the exact versions in the sign-off table.

### What you need

- A deployed build over **HTTPS** (the refresh cookie is `Secure`, so Safari stores nothing over
  plain http). A local `http://localhost` build works in Chrome and Firefox only.
- A throwaway account with a **verified** email, and a second brand-new account (to see the
  first-run state).
- A 10 to 30 second speech sample as a **.wav** file (the repo has `backend/tests/fixtures/sample_5sec.wav`,
  which is only 5 s: fine for upload, short for quality).
- A working microphone for the recording step.
- Do the pass with the screen to hand but **do not look at it for the speech checks**: turn the
  monitor off or close your eyes, so you find what is actually announced.

### How to record

For every row write **P** (pass), **F** (fail) or **N** (not applicable, with the reason). A fail
needs the screen reader, browser, page, what you did, what you heard, and what you expected. Use
the severity scale at the end.

## 2. Part A: screen reader

"Expected" describes what must be conveyed, not exact words; screen readers phrase things
differently. A row passes if the information is there, in a sensible order, without needing the
screen.

### A1. Landing page `/` (signed out)

| #    | Do                                                                  | Expected                                                                                                           | NVDA FF | NVDA Ch | VO mac | VO iOS |
| ---- | ------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------ | ------- | ------- | ------ | ------ |
| A1.1 | Load the page, then read from the top (NVDA: Insert+Down; VO: VO+A) | Page title; a "Skip to content" link first; header with the logo link, "Sign in", "Create account", a theme button |         |         |        |        |
| A1.2 | List headings (NVDA: H; VO: rotor > Headings)                       | Exactly one level-1 "Clone a voice. Say anything."; level-2 "Before you start"                                     |         |         |        |        |
| A1.3 | Read the three statements                                           | They are a list (item count announced), each a full sentence                                                       |         |         |        |        |
| A1.4 | Activate the theme button three times                               | Each press says the new mode ("Theme: Light. Switch to dark." style); the screen does not need to be seen          |         |         |        |        |

### A2. Create an account `/signup`

| #    | Do                               | Expected                                                                                                                                        | NVDA FF | NVDA Ch | VO mac | VO iOS |
| ---- | -------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------- | ------- | ------- | ------ | ------ |
| A2.1 | Tab to each field                | Each says its label (Name, Email, Password) and its type; the password rule ("8 to 128 characters") is read with the password field             |         |         |        |        |
| A2.2 | Submit empty                     | Focus or announcement lands on the problem; each error is read next to its field ("invalid", the message); not just a colour                    |         |         |        |        |
| A2.3 | Use the "Show password" checkbox | Announced as a checkbox with its state; ticking it reveals the text and the field keeps its value and focus order                               |         |         |        |        |
| A2.4 | Submit a valid account           | You are told you arrived on the next page: the heading **"Generate speech" is read** (the app moves focus to the page heading after navigation) |         |         |        |        |
| A2.5 | Check the Google option          | "Continue with Google" is a link; the "or use email" divider is not read as noise                                                               |         |         |        |        |

### A3. Sign in `/login` and session end

| #    | Do                                          | Expected                                                                                | NVDA FF | NVDA Ch | VO mac | VO iOS |
| ---- | ------------------------------------------- | --------------------------------------------------------------------------------------- | ------- | ------- | ------ | ------ |
| A3.1 | Enter a wrong password                      | The error is announced without moving focus away from the form; it says what to do next |         |         |        |        |
| A3.2 | Sign in correctly                           | Lands on Generate, heading read                                                         |         |         |        |        |
| A3.3 | Sign out, then open `/login?reason=expired` | "Your session ended. Sign in to continue." is announced or the first thing read         |         |         |        |        |

### A4. Navigation and the shell (signed in)

| #    | Do                                              | Expected                                                                                                                                                                      | NVDA FF | NVDA Ch | VO mac | VO iOS |
| ---- | ----------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------- | ------- | ------ | ------ |
| A4.1 | List landmarks (NVDA: D; VO: rotor > Landmarks) | "Primary" navigation, main, footer; on a phone width also a "Mobile" navigation (the tab bar); no duplicate unlabeled navigation                                              |         |         |        |        |
| A4.2 | Move through the nav                            | The current page is spoken as "current page" (Generate, Voices, History, Account)                                                                                             |         |         |        |        |
| A4.3 | Follow Voices, then History                     | After each, the new **h1 is read** and reading continues from it; you are not left on the old link                                                                            |         |         |        |        |
| A4.4 | Use "Skip to content" first thing on any page   | Jumps past the header to the main content                                                                                                                                     |         |         |        |        |
| A4.5 | Go offline (turn off Wi-Fi), then back on       | "You're offline. Uploading and generating are paused..." is announced politely; the generate and create buttons say why they are disabled; when back online the notice clears |         |         |        |        |

### A5. First-run state (the brand-new account)

| #    | Do                                               | Expected                                                                                                                       | NVDA FF | NVDA Ch | VO mac | VO iOS |
| ---- | ------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------ | ------- | ------- | ------ | ------ |
| A5.1 | Open Generate with a new, **unverified** account | The "First steps" list is a numbered list; the current step is identified as such; each step says Done / Next / To do in words |         |         |        |        |
| A5.2 | Find the Generate button                         | It is disabled and its **reason is read with it** ("Verify your email first" or similar)                                       |         |         |        |        |
| A5.3 | Use "Resend verification email"                  | Result is announced (sent, or wait N seconds)                                                                                  |         |         |        |        |

### A6. Create a voice `/voices`

| #    | Do                                                | Expected                                                                                                                                                                                                                  | NVDA FF | NVDA Ch | VO mac | VO iOS |
| ---- | ------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------- | ------- | ------ | ------ |
| A6.1 | Reach "How to add a sample"                       | A radio group named so; "Upload a file" selected; **one tab stop**; Left/Right arrows change the choice and speak it                                                                                                      |         |         |        |        |
| A6.2 | Choose a file (Choose file button)                | The chosen file name and size are read afterwards; the control is not a mystery "button"                                                                                                                                  |         |         |        |        |
| A6.3 | Reach the consent checkbox                        | Full sentence read ("I confirm I have the right to use this voice sample..."), state checked/unchecked; the "Terms are being finalised" line is reachable; "Your sample is kept until you delete this voice" is reachable |         |         |        |        |
| A6.4 | Submit without consent                            | The error is announced and tied to the checkbox                                                                                                                                                                           |         |         |        |        |
| A6.5 | Submit correctly                                  | While working: "Creating voice..." / progress is announced (not every percent); on success "Voice “X” created." is announced and a "Generate speech with “X”" link appears                                                |         |         |        |        |
| A6.6 | Switch to "Record now"                            | Microphone permission prompt is operable by keyboard; "Start recording" then a live status; "Stop recording" is **disabled with the reason "at least 5 seconds"** read; level meter is not chatty (it should not spam)    |         |         |        |        |
| A6.7 | Stop and preview the recording                    | "Recorded 0:07. Listen before you upload." announced; the preview player is operable (see A8)                                                                                                                             |         |         |        |        |
| A6.8 | In the voice list, activate **Delete** on a voice | A dialog opens: its title and the warning are read; focus is inside it; Tab stays inside; **Escape closes it and focus returns to the Delete button**; confirming announces the result and the row is gone                |         |         |        |        |

### A7. Generate `/generate`

| #    | Do                                                                      | Expected                                                                                                                   | NVDA FF | NVDA Ch | VO mac | VO iOS |
| ---- | ----------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------- | ------- | ------- | ------ | ------ |
| A7.1 | Reach "Voice" and "Text"                                                | Labels read; the character counter and hint ("Plain text works best...") are read as a description of the text box         |         |         |        |        |
| A7.2 | Choose a voice with the keyboard                                        | Selected voice name is spoken                                                                                              |         |         |        |        |
| A7.3 | Press "Generate speech"                                                 | A busy state is announced ("Generating...", elapsed seconds not announced every second); "Cancel" is reachable             |         |         |        |        |
| A7.4 | Wait for the result                                                     | Completion is announced; the result region is reachable and labelled; Play/Pause, Seek and "Download WAV" are all operable |         |         |        |        |
| A7.5 | Use "Edit text" and "Generate again"                                    | Edit text puts focus in the text box with the text selected; Generate again starts a new run                               |         |         |        |        |
| A7.6 | Trigger a cooldown (many quick runs, or use a rate-limited environment) | "You can try again in N s" is read and linked to the disabled button                                                       |         |         |        |        |

### A8. The audio player ("take") everywhere it appears

Check once on Generate, once in History, once in the recording preview.

| #    | Do                                        | Expected                                                                                                             | NVDA FF | NVDA Ch | VO mac | VO iOS |
| ---- | ----------------------------------------- | -------------------------------------------------------------------------------------------------------------------- | ------- | ------- | ------ | ------ |
| A8.1 | Tab into the player                       | Play button name includes what it plays ("Play Generated speech"); changes to "Pause ..." while playing              |         |         |        |        |
| A8.2 | Reach the seek slider                     | Named ("Seek ..."), its value is a time like "0:03 of 0:07" not a raw number; arrow keys move it by about 2 s        |         |         |        |        |
| A8.3 | Let it play to the end                    | No stream of timer announcements; the end state is clear                                                             |         |         |        |        |
| A8.4 | Break the audio (expired item in History) | "The audio has expired and is no longer available (clips are kept for N days)" is read; no dead Play control remains |         |         |        |        |

### A9. History `/history`

| #    | Do                   | Expected                                                                                                                | NVDA FF | NVDA Ch | VO mac | VO iOS |
| ---- | -------------------- | ----------------------------------------------------------------------------------------------------------------------- | ------- | ------- | ------ | ------ |
| A9.1 | Read the list        | A list; each item gives date, voice name and the text start; "Audio is kept for N days..." note is read once at the top |         |         |        |        |
| A9.2 | Play an item         | Focus stays on a sensible control; "Load more" is a button and loading is announced                                     |         |         |        |        |
| A9.3 | Open with no history | The empty message and a "Generate speech" link are read                                                                 |         |         |        |        |

### A10. Account `/account`

| #     | Do                               | Expected                                                                                                         | NVDA FF | NVDA Ch | VO mac | VO iOS |
| ----- | -------------------------------- | ---------------------------------------------------------------------------------------------------------------- | ------- | ------- | ------ | ------ |
| A10.1 | Change the display name and save | "Name updated." toast is announced politely (it must not steal focus)                                            |         |         |        |        |
| A10.2 | Open "Delete my account"         | A dialog: title read, the "type DELETE" field first and focused; the confirm button is disabled until it matches |         |         |        |        |
| A10.3 | Enter a wrong password           | The error is announced and tied to the password field                                                            |         |         |        |        |
| A10.4 | Cancel with Escape               | Closes, focus returns to "Delete my account"                                                                     |         |         |        |        |

### A11. Errors and unusual states

| #     | Do                                                   | Expected                                                                                                                                                                                                                                                             | NVDA FF | NVDA Ch | VO mac | VO iOS |
| ----- | ---------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------- | ------- | ------ | ------ |
| A11.1 | Open `/dashboard` and `/profile`                     | Redirected to Generate / Voices; the page is announced normally                                                                                                                                                                                                      |         |         |        |        |
| A11.2 | Open a made-up path                                  | Next.js's default "404 / This page could not be found" page, inside the normal header and footer. It must be announced as a page (title and a heading), and the logo or nav must be a clear way home. There is no custom 404 page, so note any wording that confuses |         |         |        |        |
| A11.3 | Zoom to 200% and 400% with the screen reader running | Nothing is clipped; reading order still matches the visual order                                                                                                                                                                                                     |         |         |        |        |
| A11.4 | Turn on the OS high-contrast / forced-colours mode   | Buttons, inputs, the focus position and the current nav item are still distinguishable                                                                                                                                                                               |         |         |        |        |

## 3. Part B: real Safari (macOS and iPhone)

Automated runs only cover Playwright's WebKit build, not Safari itself. Run these on a real Mac
and a real iPhone, **with VoiceOver off first** (to judge the plain behaviour), then spot-check
with it on.

| #   | Do                                                                                                    | Expected                                                                                                                                        | Mac | iPhone |
| --- | ----------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------- | --- | ------ |
| B1  | Sign up and stay signed in after a full reload                                                        | Still signed in (proves the `Secure` refresh cookie is stored; needs HTTPS)                                                                     |     |        |
| B2  | Close the tab, reopen the site                                                                        | Still signed in; no flash of the wrong theme                                                                                                    |     |        |
| B3  | Sign out and in; open the site in a second tab and sign out there                                     | The first tab signs out too                                                                                                                     |     |        |
| B4  | Open Voices                                                                                           | **"Record now" is not offered** (Safari records a format the server rejects); the upload path is the only one and the page does not look broken |     |        |
| B5  | Upload a .wav (iPhone: from Files and from the photo/music sources)                                   | File name and size appear; create succeeds                                                                                                      |     |        |
| B6  | Generate speech and press Play                                                                        | Plays on the first tap (no autoplay is attempted); seek works; time display updates                                                             |     |        |
| B7  | Tap "Download WAV"                                                                                    | The file downloads or opens a share/preview; it is a playable WAV                                                                               |     |        |
| B8  | Play from History after an hour offline-online cycle                                                  | Plays; no stale-session error                                                                                                                   |     |        |
| B9  | Tap into every input on iPhone                                                                        | **The page does not zoom in** when a field is focused (text under 16 px triggers this)                                                          |     |        |
| B10 | Rotate the iPhone, and use Split View on iPad                                                         | Layout reflows; the bottom tab bar does not cover content or the home indicator                                                                 |     |        |
| B11 | Switch the system between light and dark; use the in-app theme button                                 | Both follow; the browser chrome colour matches                                                                                                  |     |        |
| B12 | Open the Web Inspector console (Mac: Safari > Develop; iPhone: connect to a Mac) while doing B1 to B7 | No CSP errors and no red console errors; note any "violates the following Content Security Policy" line                                         |     |        |
| B13 | Reduce Motion on, then use the page                                                                   | No animation other than instant state changes; the waveform is static                                                                           |     |        |
| B14 | Turn on "Prevent Cross-Site Tracking" and "Block All Cookies" in turn                                 | With the second, sign-in should fail with a message, not a blank or spinning page                                                               |     |        |

## 4. Defects

**Severity.** _Blocker_: a user with this assistive technology cannot complete signup, creating a
voice, generating, or deleting data. _Major_: they can, but need the screen or a workaround.
_Minor_: wrong or noisy wording, order slightly off. _Note_: preference.

Template (one per defect):

```
Platform / browser / screen reader + versions:
Page and step (row id, e.g. A6.8):
Did:
Heard (or saw):
Expected:
Severity:
```

File each as an issue; do **not** edit the app to pass a row without a retest of that row.

## 5. Sign-off

A launch gate is: **no Blocker or Major open** on rows 1 and 2 of the matrix and on the Safari rows.
Minor items may ship with a ticket. Re-run only the affected sections after a fix.

| Matrix row                             | Tester | Date | App version (commit) | Blockers | Majors | Minors | Result |
| -------------------------------------- | ------ | ---- | -------------------- | -------- | ------ | ------ | ------ |
| 1 Windows, Firefox, NVDA               |        |      |                      |          |        |        |        |
| 2 Windows, Chrome, NVDA                |        |      |                      |          |        |        |        |
| 3 macOS, Safari, VoiceOver             |        |      |                      |          |        |        |        |
| 4 iPhone, Safari, VoiceOver            |        |      |                      |          |        |        |        |
| 5 Android, Chrome, TalkBack (optional) |        |      |                      |          |        |        |        |
| Part B, macOS Safari                   |        |      |                      |          |        |        |        |
| Part B, iPhone Safari                  |        |      |                      |          |        |        |        |

When the gate is met, update `FRONTEND_UX_IMPROVEMENT_PLAN.md` §9.1: item 3 to **Met** and the
Safari part of item 6 to **Met**, citing the commit tested and this table.
