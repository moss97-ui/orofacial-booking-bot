# n8n workflows

This folder holds the n8n versions of the booking bot. Both are exports **without credentials** (no bot tokens, no
Google accounts), so they are safe to keep in a public repository.

| File | What it is |
|---|---|
| `OroFacial-Booking-bot.workflow.json` | The original OroFacial clinic bot (Armenian only). The Python version in `bot/` is a port of it. |
| `Clinic-Booking-bot.workflow.json` | The generic **"Clinic - Booking bot"** (@ClinicBookingAssistant_bot): no clinic-specific details, waitlist, and 3 languages (Armenian, English, Russian). |
| `clinic-code/` | The JavaScript of every Code node in the Clinic bot, one file per node, so it is easy to read on GitHub. These are copies; the real code is inside the workflow file. |
| `clinic-i18n.json` | English and Russian translations used by the Clinic bot. **The live bot downloads this file from GitHub**, so do not rename or move it. |

## How the Clinic bot works (short version)

* **Telegram Trigger → Load languages → Lang pack → Parse update → Route → …** handles every message and button tap.
  *Every 30 minutes* goes through the same *Load languages → Lang pack* nodes and then sends reminders and rating requests.
* **Lang pack** (`clinic-code/lang-pack.js`) downloads `clinic-i18n.json` (cached for 6 hours) and builds the
  Armenian → English / Russian replacement lists, including all date labels.
* **Parse update** (`clinic-code/parse-update.js`) shows the language buttons on `/start`, remembers the choice in the
  data table `clinic_user_langs`, and turns English/Russian button taps back into the Armenian labels the rest of the
  workflow understands.
* **Route** (`clinic-code/route.js`) is the main brain: it decides what the bot does next for every message.
* Every Telegram node translates its text with a short expression just before sending, so the bot logic itself stays
  in Armenian.

## Changing translations

Edit `clinic-i18n.json` on GitHub. Each row in `static` is `[Armenian, English, Russian]`. The bot picks up changes
within 6 hours (or right away after the workflow is re-published). When you add a new doctor, add rows for their name
and description too.

## Importing the Clinic bot into another n8n

1. In n8n: **Workflows → Import from file** → choose `Clinic-Booking-bot.workflow.json`.
2. Create the data tables it uses: `clinic_patient_sessions`, `clinic_booking_requests`, `clinic_waitlist`,
   `clinic_doctors_v2`, `clinic_user_langs` (columns `chat_id`, `lang`). Point the Data Table nodes at them.
3. Select your own **Telegram** credential (your bot token) and **Google Calendar** credential on the nodes that ask
   for one.
4. Publish. Only one workflow may use a given Telegram bot at a time.
