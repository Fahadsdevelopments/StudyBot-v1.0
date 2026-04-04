# 🎓 StudyBot v1.0 — AI Student Assistant for Discord

A fully-featured Discord bot that helps university students manage their academic life. Upload lecture slides and assignments, get AI-powered task extraction, track your progress, and sync your study schedule to Google Calendar.

Built with **FastAPI**, **Discord.js**, **MongoDB Atlas**, **OpenRouter (Nemotron)**, and deployed free on **Railway**.

---

## ✨ Features

| Feature | Commands |
|---|---|
| 📄 **PDF Analysis** | Attach any PDF → bot extracts tasks, topics, complexity |
| 📋 **Task Management** | `!tasks`, `!tasks GTI1`, `!done [task]`, `!clear` |
| 📅 **Smart Scheduling** | `!schedule`, `!schedule 4` — respects protected time |
| 📅 **Google Calendar Sync** | `!sync` — pushes schedule to your calendar |
| ⏱️ **Task Timer** | `!start [task]`, `!stop` — logs actual time spent |
| 🎮 **Gamification** | `!level` — XP and levels per subject |
| 🧠 **Skill Profiling** | `!skills` — tracks your mastery per topic over time |
| 📝 **Exam Tracker** | `!exams`, `!exam add CODE DATE TIME LOCATION` |
| 📊 **Grade & ECTS Tracker** | `!grades`, `!grade CODE GRADE` (German 1.0–5.0 scale) |
| 🔒 **Protected Time** | `!protect Monday 18:00 22:00 Personal time` |
| 📈 **Analytics** | `!analytics`, `!analytics 7` — study trends & mastery curves |
| 📚 **Subject Management** | `!subjects`, `!add_subject CODE Name` — dynamic, semester-aware |

---

## 🏗️ Architecture

```
Discord
  └── bot.js (Discord.js v13)
        └── FastAPI backend (server.py)
              ├── processor.py  — PDF text extraction + Nemotron AI analysis
              ├── calendar_sync.py — Google Calendar integration
              └── MongoDB Atlas — all data storage
```

All AI analysis is done via **OpenRouter** using the free **Nvidia Nemotron** model.  
Large PDFs (100+ pages) are automatically split into chunks so nothing gets missed.

---

## 🚀 Deployment Guide

### Prerequisites

You need accounts on these free services before starting:

- [Discord Developer Portal](https://discord.com/developers) — for your bot token
- [OpenRouter](https://openrouter.ai) — for free AI (Nemotron)
- [MongoDB Atlas](https://mongodb.com/atlas) — free database
- [Railway](https://railway.app) — free hosting
- [GitHub](https://github.com) — to host the code
- [Google Cloud Console](https://console.cloud.google.com) — optional, for calendar sync

---

### Step 1: Create your Discord Bot

1. Go to [discord.com/developers/applications](https://discord.com/developers/applications)
2. Click **New Application** → name it (e.g. "StudyBot") → Create
3. Left sidebar → **Bot** → **Reset Token** → copy the token → save it as `DISCORD_TOKEN`
4. On the same page, scroll down and enable:
   - ✅ **Message Content Intent**
   - ✅ **Server Members Intent**
5. Left sidebar → **OAuth2 → URL Generator**
   - Tick: `bot` and `applications.commands`
   - Bot Permissions: Send Messages, Embed Links, Attach Files, Read Message History, Use Slash Commands
6. Copy the generated URL → open in browser → invite bot to your server

---

### Step 2: Get your OpenRouter API key

1. Go to [openrouter.ai](https://openrouter.ai) → Sign up
2. Click **Keys** → **Create Key** → copy it → save as `OPENROUTER_API_KEY`
3. The bot uses `nvidia/nemotron-3-super-120b-a12b:free` — completely free, no credit card needed

---

### Step 3: Set up MongoDB Atlas

1. Go to [mongodb.com/atlas](https://mongodb.com/atlas) → Sign up free
2. Create a free **M0** cluster (any region)
3. Create a database user: username + password → save the password
4. **Network Access** → Add IP Address → **Allow Access from Anywhere** (0.0.0.0/0)
5. **Database** → Connect → Drivers → copy the connection string:
   ```
   mongodb+srv://username:PASSWORD@cluster0.xxxxx.mongodb.net/
   ```
   Replace `PASSWORD` with your actual password → save as `MONGODB_URI`

---

### Step 4: Fork and configure this repo

1. Click **Fork** on this GitHub repo
2. Clone your fork:
   ```bash
   git clone https://github.com/YOUR_USERNAME/StudyBot-v1.0.git
   cd studybot
   ```
3. Update the Railway API URL in `bot.js` — find this line near the top:
   ```javascript
   const API = 'https://web-production-28d84.up.railway.app';
   ```
   You will update this after Step 5 once Railway gives you your URL.

4. Create your local `.env` file (never commit this):
   ```bash
   cp .env.example .env
   ```
   Fill in your values:
   ```
   DISCORD_TOKEN=your_discord_token
   MONGODB_URI=your_mongodb_uri
   OPENROUTER_API_KEY=your_openrouter_key
   ```

---

### Step 5: Deploy to Railway

#### Deploy the FastAPI backend (web service)

1. Go to [railway.app](https://railway.app) → Sign in with GitHub
2. Click **New Project** → **Deploy from GitHub repo** → select your fork
3. Once created, click the service → **Variables** tab → add:
   ```
   MONGODB_URI = your mongodb connection string
   OPENROUTER_API_KEY = your openrouter key
   ```
4. Click **Settings** → **Networking** → **Generate Domain** → copy your URL
   - It looks like: `https://studybot-production-xxxx.up.railway.app`

5. Open `bot.js` and update line 4:
   ```javascript
   const API = 'https://studybot-production-xxxx.up.railway.app';
   ```
   Push the change:
   ```bash
   git add bot.js
   git commit -m "Update API URL"
   git push
   ```

6. Test your backend is live:
   ```
   https://your-railway-url.up.railway.app/health
   ```
   You should see: `{"status":"ok","db":"connected",...}`

#### Deploy the Discord bot (second service)

1. In Railway, click **+ New** → **GitHub Repository** → same repo
2. Click the new service → **Settings** → **Deploy** → **Start Command**:
   ```
   node bot.js
   ```
3. **Variables** tab → add:
   ```
   DISCORD_TOKEN = your discord bot token
   MONGODB_URI = your mongodb connection string
   OPENROUTER_API_KEY = your openrouter key
   ```
4. Click **Deploy**

Your bot should now show as **online** in Discord. Type `!help` to confirm.

---

### Step 6: Add your subjects

Once the bot is online, add your subjects for the semester:

```
!add_subject GTI1 Grundlagen der Theoretischen Informatik 1 5
!add_subject SE Software Engineering 6
```

Format: `!add_subject CODE Full Name ECTS_Credits`

---

### Step 7: (Optional) Google Calendar Integration

This is optional — the bot works fully without it.

1. Go to [console.cloud.google.com](https://console.cloud.google.com)
2. Create a new project named "studybot"
3. Enable the **Google Calendar API**
4. Left sidebar → **APIs & Services** → **Credentials** → **Create Credentials** → **Service Account**
5. Name it `studybot-calendar` → Create and Continue → Done
6. Click the service account → **Keys** tab → **Add Key** → **Create new key** → JSON → Download
7. Rename the downloaded file to `service_account.json`

8. Share your Google Calendar with the service account:
   - Open [calendar.google.com](https://calendar.google.com)
   - Click ⋮ next to your primary calendar → **Settings and sharing**
   - **Share with specific people** → add the service account email
   - (found in `service_account.json` under `"client_email"`)
   - Set permission to **Make changes to events**

9. Add to Railway variables (web service):
   ```
   GOOGLE_CALENDAR_ID = your_email@gmail.com
   TIMEZONE = Europe/Berlin
   ```

10. Add `service_account.json` content as a Railway variable:
    ```bash
    # Run this to get the content as a single line
    python3 -c "import json; print(json.dumps(json.load(open('service_account.json'))))"
    ```
    Add to Railway as:
    ```
    GOOGLE_SERVICE_ACCOUNT = { ...the entire JSON content... }
    ```

    Then update `calendar_sync.py` to read from the environment variable instead of a file — see the **Advanced Configuration** section below.

---

## 📖 Command Reference

### Documents
| Command | Description |
|---|---|
| Attach a PDF | Bot asks: doc type → subject → familiarity (1-5) |

### Tasks
| Command | Description |
|---|---|
| `!tasks` | All pending tasks |
| `!tasks GTI1` | Tasks for a specific subject |
| `!done [task name]` | Mark a task as complete |
| `!clear` | Clear all tasks |

### Schedule
| Command | Description |
|---|---|
| `!schedule` | Generate today's study plan (6h default) |
| `!schedule 4` | Generate plan with custom hours |
| `!sync` | Push schedule to Google Calendar |

### Timer & Skills
| Command | Description |
|---|---|
| `!start [task name]` | Start timing a task |
| `!stop` | Stop timer, log actual time, earn XP |
| `!skills` | Your skill profile per topic |
| `!level` | XP and levels per subject |

### Exams
| Command | Description |
|---|---|
| `!exams` | All upcoming exams with countdown |
| `!exam add CODE YYYY-MM-DD HH:MM Location` | Add an exam |
| `!exam remove CODE` | Remove an exam |

### Grades
| Command | Description |
|---|---|
| `!grades` | All grades + GPA + ECTS summary |
| `!grade CODE GRADE` | Log a final grade (1.0–5.0) |
| `!grade CODE GRADE midterm` | Log a midterm grade |

### Protected Time
| Command | Description |
|---|---|
| `!protected` | See all protected blocks |
| `!protect Monday 18:00 22:00 Label` | Protect a specific day/time |
| `!protect daily 22:00 23:59 Label` | Protect a recurring time |
| `!unprotect Monday 18:00` | Remove a protected block |

### Analytics
| Command | Description |
|---|---|
| `!analytics` | Study trends for last 30 days |
| `!analytics 7` | Study trends for last 7 days |

### Subjects
| Command | Description |
|---|---|
| `!subjects` | List all subjects |
| `!add_subject CODE Name ECTS` | Add a subject |
| `!remove_subject CODE` | Remove a subject |
| `!docs` | All uploaded documents |
| `!docs GTI1` | Documents for a subject |

### Other
| Command | Description |
|---|---|
| `!health` | Check API and database status |
| `!help` | Show all commands |

---

## 🔧 Advanced Configuration

### Use Google Calendar service account from environment variable

If you don't want to store `service_account.json` as a file on Railway, update `calendar_sync.py`:

Replace:
```python
credentials = service_account.Credentials.from_service_account_file(
    SERVICE_ACCOUNT_FILE, scopes=SCOPES)
```

With:
```python
import json
sa_info = json.loads(os.getenv('GOOGLE_SERVICE_ACCOUNT'))
credentials = service_account.Credentials.from_service_account_info(
    sa_info, scopes=SCOPES)
```

### Change the AI model

In `processor.py`, find:
```python
"model": "nvidia/nemotron-3-super-120b-a12b:free",
```
Replace with any model from [openrouter.ai/models](https://openrouter.ai/models).
Free models are marked with `:free`. Faster options include `google/gemma-3-27b-it:free`.

### Change the grading scale

The bot uses the German 1.0–5.0 scale. To change it, update the grade validation in `server.py`:
```python
if not (1.0 <= grade <= 5.0):
    raise HTTPException(...)
```

---

## 📁 File Structure

```
studybot/
├── bot.js              # Discord bot — all commands and user interaction
├── server.py           # FastAPI backend — all API endpoints
├── processor.py        # PDF text extraction + AI analysis (chunked)
├── calendar_sync.py    # Google Calendar integration
├── requirements.txt    # Python dependencies
├── package.json        # Node.js dependencies
├── Procfile            # Railway start command for FastAPI
├── .node-version       # Node.js version for Railway bot service
├── .env.example        # Template for environment variables
├── .gitignore          # Excludes secrets and temp files
└── README.md           # This file
```

**Files you must NOT commit (already in .gitignore):**
- `.env` — your API keys
- `service_account.json` — Google Calendar credentials
- `token.json` — Google OAuth token
- `credentials.json` — Google OAuth credentials

---

## 🔒 Security Notes

- All API keys are stored as environment variables — never hardcoded
- MongoDB Atlas requires authentication for all connections
- The bot only responds in servers/channels it has been invited to
- Protected time blocks are stored per-user in MongoDB
- Skill profiles and XP are stored per Discord user ID

---

## 💰 Cost

Everything runs on free tiers:

| Service | Free Tier |
|---|---|
| Railway | $5 credit/month (resets monthly) |
| MongoDB Atlas | 512 MB storage (lasts years for text data) |
| OpenRouter (Nemotron) | Completely free |
| Google Calendar API | Free |
| Discord Bot | Free |

**Total monthly cost: $0**

---

## 🤝 Contributing

Pull requests welcome! If you add a feature, please:
1. Update the command reference in this README
2. Make sure no API keys are hardcoded
3. Test locally before pushing

---

## 📄 License

MIT License — use it however you want.

---

## 🙏 Credits

Built with:
- [Discord.js](https://discord.js.org/) — Discord bot framework
- [FastAPI](https://fastapi.tiangolo.com/) — Python web framework
- [PyMuPDF](https://pymupdf.readthedocs.io/) — PDF text extraction
- [OpenRouter](https://openrouter.ai/) — AI model gateway
- [MongoDB Atlas](https://mongodb.com/atlas) — Cloud database
- [Railway](https://railway.app/) — Deployment platform
