# שולחן 4 — Claude Context

## מה האפליקציה עושה
פלטפורמת עיבוד תוכן מדיה עברית — מתמלל YouTube, מתרגם, יוצר מצגות PPTX עם AI, כולל מנוי, אימות משתמשים, ו-Telegram CEO notifications.

## Entry Points
- **`app.py`** (63KB) — Flask app, כל הלוגיקה
- **`db.py`** — PostgreSQL helpers (psycopg2)
- **`run_cmo.py`, `run_pm_bot.py`, `run_sales_bot.py`, `run_ceo_briefing.py`** — Multi-agent AI bots
- **`pptx_gen/`** — PPTX generation logic
- Port: **5002** (APP_URL env var)

## Tech Stack
- **Flask** + werkzeug.security (auth)
- **Anthropic SDK** — content analysis, summaries
- **yt-dlp** — YouTube download
- **youtube_transcript_api** — transcript (fallback)
- **Invidious** — primary transcript source (first choice)
- **deep_translator** (GoogleTranslator) — תרגום
- **python-pptx** — יצירת מצגות PowerPoint
- **psycopg2** — PostgreSQL
- **Resend** — email API
- **LemonSqueezy** — payment/subscriptions

## DB Schema (db.py)
```sql
users(id, email, password_hash, name, plan, stripe_customer_id, stripe_subscription_id, portal_url, created_at)
episodes(id, user_id, video_id, title, summary, created_at)  -- UNIQUE(user_id, video_id)
usage_log(id, user_id, month, transcript_count)               -- UNIQUE(user_id, month)
reset_tokens(id, user_id, token, expires_at, created_at)
```
- Database: **PostgreSQL** ב-Railway (DATABASE_URL)
- `user_db.init()` נקרא ב-startup

## משתני סביבה (.env)
```
DATABASE_URL=         # PostgreSQL connection string
SECRET_KEY=           # Flask session key
RESEND_API_KEY=       # Email API
LS_API_KEY=           # LemonSqueezy API
LS_STORE_ID=          # LemonSqueezy store
LS_VARIANT_ID=        # Subscription variant
LS_WEBHOOK_SECRET=    # LemonSqueezy webhook verify
APP_URL=              # Base URL (prod: https://...)
SUPADATA_API_KEY=     # Alternative transcript source
TELEGRAM_TOKEN=       # Bot token לCEO notifications
ADMIN_CHAT_ID=        # Telegram chat ID של מנכ"ל
ANTHROPIC_API_KEY=    # Claude API
```

## Multi-Agent Bots (app.py:44)
- **`run_cmo.py`** — CMO agent: marketing strategy
- **`run_pm_bot.py`** — PM agent: product decisions
- **`run_sales_bot.py`** — Sales agent: user outreach
- **`run_ceo_briefing.py`** — CEO briefing: daily summary

## Plans / Permissions
- **free plan**: `FREE_LIMIT = 3` תמלולים
- **admin**: `ADMIN_EMAILS = ['jakovdob@gmail.com']`
- LemonSqueezy webhook מעדכן `plan` ב-DB

## YouTube Transcript Flow
1. ניסיון ראשון: **Invidious** (API עצמאי)
2. גיבוי: **youtube_transcript_api**
3. כישלון: yt-dlp לdownload + whisper transcription

## הפעלה
```powershell
cd c:\Users\555\shulchan4
python app.py
# → http://localhost:5002
```

## Deployment
- **Railway** — production (Docker או Nixpacks)
- `Dockerfile`, `docker-compose.yml`, `nixpacks.toml` קיימים
- `render.yaml` — גיבוי ל-Render
- `Procfile` — web: gunicorn

## Gotchas
- `yt_cookies.txt` — cookies לYouTube (מונע חסימה)
- `SUPADATA_API_KEY` — שירות חיצוני לtranscripts
- `user_db.init()` ב-startup יוצר טבלאות אם לא קיימות
- `notify_ceo()` — fire-and-forget, לא ייזרוק exception
- שם קובץ `app.py` הוא 63KB — קובץ ענק, לעבוד בו בזהירות
