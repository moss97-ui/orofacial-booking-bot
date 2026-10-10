# OroFacial booking bot (Python)

A Telegram bot that books dental appointments for the OroFacial clinic (Yerevan). Patients choose a doctor, a visit
reason, a day and a time. The doctor approves in Telegram, and only then the visit is added to Google Calendar.

This is the Python version of the n8n workflow **"OroFacial - Booking bot"**. It has the same features and the same
Armenian texts, and it runs on any server without n8n. Tests compare it with the original n8n code (see *Tests* below).

## What it does

**Patients**
- Choose a doctor (with ℹ️ profile, services and prices), or choose by service.
- Pick a visit reason. The reason sets the visit length (30 / 60 / 90 min).
- Pick the month, then the day (only days with free time are shown), then the time.
- Enter a name and phone number (or share the Telegram phone). Both are remembered for the next booking.
- Get the doctor's answer in Telegram, then directions to the clinic (Yandex Maps).
- Get reminders 1 day and 2 hours before the visit, with ✅ Կգամ / ❌ Չեմ կարող գալ / 🔁 Փոխել ժամը buttons.
- Manage bookings in 📋 Իմ ամրագրումները: cancel, or change the time (the old booking is cancelled only after the new one is approved).
- Join the 🔔 waitlist when there is no free time, and get a message when a booking with that doctor is cancelled.
- Rate the visit (1–5 ⭐) afterwards. High ratings get a Yandex review link; low ratings alert the clinic.
- Use 📞 Կապ կլինիկայի հետ (phone, Telegram, WhatsApp, Viber, Instagram, map) and ❓ Ինչպես օգտվել (help).

**Doctors / administrators** (anyone whose Telegram chat ID is an `approver_chat_id`)
- Approve or reject requests with one tap. Two people can't approve the same request twice.
- 📊 Dashboard, 📅 today, 📆 tomorrow, 🗓 next 7 days, ⏳ pending requests (each with approve / reject buttons).
- 🚫 Block a whole day or a time range for a doctor (vacation, break). It creates a "⛔ Փակ" calendar event, and an undo button is provided.
- ❓ A staff guide, and 🧑 a button to try the bot as a patient.

## How it is built

```
bot/
  main.py              Telegram connection (polling or webhook), runs reminders every 30 min
  router.py            decides what to do with each message / button tap (pure logic)
  actions.py           carries out the decision: messages, database, calendar
  slots.py             free times and free days (doctor shift − calendar events − other requests)
  jobs.py              reminders and rating requests
  reports.py           staff dashboard and lists
  db.py                SQLite database (sessions, requests, waitlist)
  calendar_service.py  Google Calendar (service account), or an in-memory calendar for tests
  clinic.py            reads config/clinic.yaml
config/clinic.example.yaml   doctors, hours, services, prices, contacts — copy to config/clinic.yaml
tests/                 parity tests against the n8n code + end-to-end tests
n8n/                   the original n8n workflow (export, without credentials)
deploy/                systemd service file
```

## 1. What you need

1. **A Telegram bot token.** Get one from [@BotFather](https://t.me/BotFather) (`/newbot`). You can reuse the current bot's token.
2. **A Google service account**, so the bot can read and write the calendars:
   1. Open [Google Cloud Console](https://console.cloud.google.com/) and create a project.
   2. Enable the **Google Calendar API**.
   3. Go to *IAM & Admin → Service accounts → Create*. Then *Keys → Add key → JSON*, and download the file.
   4. Save the file as `secrets/google-service-account.json`.
   5. In Google Calendar, open each doctor's calendar: *Settings and sharing → Share with specific people*. Add the
      service account's e-mail (it looks like `…@….iam.gserviceaccount.com`) with **"Make changes to events"**.
   6. Copy each calendar's **Calendar ID** (under *Integrate calendar*) into `config/clinic.yaml`.
3. **Python 3.11+**, or Docker.

## 2. Configure

```bash
cp .env.example .env                              # put TELEGRAM_BOT_TOKEN here
cp config/clinic.example.yaml config/clinic.yaml  # edit doctors, calendar IDs, approver chat IDs, prices
mkdir -p secrets                                  # put google-service-account.json here
```

- `approver_chat_id` is the Telegram chat ID of the person who approves a doctor's requests. To find yours, send
  `/myid` to the bot.
- Several doctors may share one calendar. Events are then matched by the doctor's name in the event title.
- Bios, prices and hours in the example file are **sample texts**. Replace them with the clinic's real data.
- `.env`, `config/clinic.yaml`, `secrets/` and `data/` are in `.gitignore`, so they are never pushed to GitHub.

## 3. Run it on your computer (test)

```bash
python -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python -m bot.main
```

If `GOOGLE_SERVICE_ACCOUNT_FILE` is empty, the bot runs as a **dry run**. It works, but uses an in-memory calendar,
so nothing is written to Google Calendar. Use this for a first test.

> ⚠️ **Only one program may run a Telegram bot at a time.** Before starting this Python bot with the same token,
> **deactivate the n8n workflow** "OroFacial - Booking bot" in n8n. Otherwise the two will take messages from each
> other. (Starting this bot removes n8n's webhook.) Bookings stored in the n8n data tables are not copied over.

## 4. Deploy on a server

### Option A: Docker (recommended)

On any Linux server (Hetzner, DigitalOcean, AWS Lightsail…):

```bash
git clone https://github.com/moss97-ui/orofacial-booking-bot.git
cd orofacial-booking-bot
cp .env.example .env && nano .env                     # token, settings
cp config/clinic.example.yaml config/clinic.yaml && nano config/clinic.yaml
mkdir -p secrets data && nano secrets/google-service-account.json   # paste the key
docker compose up -d --build
docker compose logs -f                                # watch the logs
```

To update later: `git pull && docker compose up -d --build`.

### Option B: plain Python + systemd

```bash
sudo useradd -m orofacial
sudo git clone https://github.com/moss97-ui/orofacial-booking-bot.git /opt/orofacial-booking-bot
cd /opt/orofacial-booking-bot
sudo python3 -m venv .venv && sudo .venv/bin/pip install -r requirements.txt
# create .env, config/clinic.yaml and secrets/ as above, then:
sudo chown -R orofacial /opt/orofacial-booking-bot
sudo cp deploy/orofacial-bot.service /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now orofacial-bot
journalctl -u orofacial-bot -f
```

### Polling or webhook?

- **Polling** (default, `WEBHOOK_URL` empty) works everywhere. The server doesn't need a domain or open ports.
- **Webhook**: set `WEBHOOK_URL=https://your-domain` and `WEBHOOK_SECRET=<random text>`. The bot listens on `PORT`
  at `/telegram`. Put an HTTPS reverse proxy (Caddy, nginx) in front of it.

## 5. Backups

All bookings are in one file: `data/bot.sqlite3`. Copy it regularly, for example with a daily cron job:
`sqlite3 data/bot.sqlite3 ".backup 'backups/bot-$(date +%F).sqlite3'"`.

## Tests

```bash
pip install -r requirements-dev.txt
pytest -q
```

- `tests/test_parity.py` runs the **original n8n JavaScript** (needs Node.js) and the Python code on thousands of
  generated situations and checks that they make the same decisions. This covers routing (~2,800 cases), free
  time slots (~3,200), free days and the staff reports.
- `tests/test_flow.py` drives the whole bot like real users, with fake Telegram and calendar. It covers booking and
  approval, rejection, double booking, cancellation and the waitlist, time change, staff blocking, reminders,
  rating, reports, calendar outage, and an unreachable doctor.
- GitHub Actions runs the tests on every push (`.github/workflows/tests.yml`).

One difference from n8n is intentional. In n8n, a staff member who typed an impossible date such as `9.30` while
blocking time got no answer, because the workflow crashed. The Python bot replies "Չհասկացա ամսաթիվը…" instead.

## Not included yet

These ideas were discussed but not built: a consent and privacy notice, a reception "backup approver" with alerts
for unanswered requests, Russian and English texts, booking added by staff for phone calls, and no-show tracking.
