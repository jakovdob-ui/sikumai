"""
Sales Bot — דני
================
מזהה משתמשים שמוכנים לשדרג ושולח להם מייל מותאם אישית.
Usage: python run_sales_bot.py
Cron: 0 9 * * *  (כל יום ב-9:00)

סגמנטים:
  1. onboarding_d0  — נרשם היום — ברוכים הבאים
  2. onboarding_d2  — נרשם לפני 2 ימים — "נסה את הסיכום החכם"
  3. onboarding_d5  — נרשם לפני 5 ימים, עדיין free — "לפני שתתייאש"
  4. new_user       — נרשם לפני 24-72 שעות, 0 סיכומים
  5. engaged_free   — 2+ סיכומים החודש, עדיין free
  6. dormant        — נרשם לפני 7+ ימים, 0 פעילות החודש
  7. churned_pro    — היה Pro, חזר לחינמי
"""
import asyncio
import os
import json
import httpx
import psycopg2
import psycopg2.extras
from datetime import date, datetime, timedelta
from dotenv import load_dotenv
load_dotenv()

from ai_utils import ask_ai_with_system_async

DATABASE_URL   = os.getenv("DATABASE_URL", "")
RESEND_KEY     = os.getenv("RESEND_API_KEY", "")
ANTHROPIC_KEY  = os.getenv("ANTHROPIC_API_KEY", "")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
ADMIN_CHAT_ID  = os.getenv("ADMIN_CHAT_ID", "")
APP_URL        = os.getenv("APP_URL", "https://podsnap.app")
FROM_EMAIL     = "PodSnap <hi@podsnap.app>"

SYSTEM = """שמך דני — Sales Bot של PodSnap.
אתה כותב מיילים קצרים, אנושיים, ישראליים.
לא corporate, לא יבש — כאילו חבר שולח הודעה.
כתוב בעברית. אל תזכיר שאתה AI.
מייל אחד = מטרה אחת = קריאה אחת לפעולה."""


def _conn():
    return psycopg2.connect(DATABASE_URL, sslmode="require")


def ensure_outreach_table():
    with _conn() as c:
        with c.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS sales_outreach (
                    id SERIAL PRIMARY KEY,
                    user_id INTEGER NOT NULL REFERENCES users(id),
                    segment TEXT NOT NULL,
                    sent_at TIMESTAMP DEFAULT NOW(),
                    UNIQUE(user_id, segment)
                )
            """)
        c.commit()


def already_sent(uid: int, segment: str) -> bool:
    with _conn() as c:
        with c.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM sales_outreach WHERE user_id=%s AND segment=%s",
                (uid, segment)
            )
            return cur.fetchone() is not None


def mark_sent(uid: int, segment: str):
    with _conn() as c:
        with c.cursor() as cur:
            cur.execute(
                "INSERT INTO sales_outreach (user_id, segment) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                (uid, segment)
            )
        c.commit()


def get_segment_users() -> dict[str, list[dict]]:
    now    = datetime.now()
    month  = now.strftime("%Y-%m")
    today  = now.date()
    ago_1d = today - timedelta(days=1)
    ago_3d = today - timedelta(days=3)
    ago_7d = today - timedelta(days=7)

    ago_2d = today - timedelta(days=2)
    ago_5d = today - timedelta(days=5)

    segments: dict[str, list[dict]] = {
        "onboarding_d0": [],
        "onboarding_d2": [],
        "onboarding_d5": [],
        "new_user":      [],
        "engaged_free":  [],
        "dormant":       [],
        "churned_pro":   [],
    }

    with _conn() as c:
        with c.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:

            # 0a. onboarding day 0 — נרשם היום
            cur.execute("""
                SELECT u.id, u.email, u.name, u.plan, u.created_at,
                       COALESCE(ul.transcript_count, 0) AS usage
                FROM users u
                LEFT JOIN usage_log ul ON ul.user_id = u.id AND ul.month = %s
                WHERE u.created_at::date = %s
            """, (month, today))
            segments["onboarding_d0"] = [dict(r) for r in cur.fetchall()]

            # 0b. onboarding day 2 — נרשם לפני 2 ימים
            cur.execute("""
                SELECT u.id, u.email, u.name, u.plan, u.created_at,
                       COALESCE(ul.transcript_count, 0) AS usage
                FROM users u
                LEFT JOIN usage_log ul ON ul.user_id = u.id AND ul.month = %s
                WHERE u.created_at::date = %s
            """, (month, ago_2d))
            segments["onboarding_d2"] = [dict(r) for r in cur.fetchall()]

            # 0c. onboarding day 5 — נרשם לפני 5 ימים, עדיין free
            cur.execute("""
                SELECT u.id, u.email, u.name, u.plan, u.created_at,
                       COALESCE(ul.transcript_count, 0) AS usage
                FROM users u
                LEFT JOIN usage_log ul ON ul.user_id = u.id AND ul.month = %s
                WHERE u.created_at::date = %s
                  AND u.plan = 'free'
            """, (month, ago_5d))
            segments["onboarding_d5"] = [dict(r) for r in cur.fetchall()]

            # 1. new_user — נרשם 24-72 שעות, 0 סיכומים
            cur.execute("""
                SELECT u.id, u.email, u.name, u.plan, u.created_at,
                       COALESCE(ul.transcript_count, 0) AS usage
                FROM users u
                LEFT JOIN usage_log ul ON ul.user_id = u.id AND ul.month = %s
                WHERE u.created_at::date BETWEEN %s AND %s
                  AND u.plan = 'free'
                  AND COALESCE(ul.transcript_count, 0) = 0
            """, (month, ago_3d, ago_1d))
            segments["new_user"] = [dict(r) for r in cur.fetchall()]

            # 2. engaged_free — 2+ סיכומים, עדיין free
            cur.execute("""
                SELECT u.id, u.email, u.name, u.plan, u.created_at,
                       ul.transcript_count AS usage
                FROM users u
                JOIN usage_log ul ON ul.user_id = u.id AND ul.month = %s
                WHERE u.plan = 'free'
                  AND ul.transcript_count >= 2
            """, (month,))
            segments["engaged_free"] = [dict(r) for r in cur.fetchall()]

            # 3. dormant — נרשם לפני 7+ ימים, 0 פעילות החודש
            cur.execute("""
                SELECT u.id, u.email, u.name, u.plan, u.created_at,
                       COALESCE(ul.transcript_count, 0) AS usage
                FROM users u
                LEFT JOIN usage_log ul ON ul.user_id = u.id AND ul.month = %s
                WHERE u.created_at::date <= %s
                  AND u.plan = 'free'
                  AND COALESCE(ul.transcript_count, 0) = 0
            """, (month, ago_7d))
            segments["dormant"] = [dict(r) for r in cur.fetchall()]

            # 4. churned_pro — plan='free', היה Pro (יש stripe_customer_id)
            cur.execute("""
                SELECT u.id, u.email, u.name, u.plan, u.created_at,
                       COALESCE(ul.transcript_count, 0) AS usage
                FROM users u
                LEFT JOIN usage_log ul ON ul.user_id = u.id AND ul.month = %s
                WHERE u.plan = 'free'
                  AND u.stripe_customer_id IS NOT NULL
            """, (month,))
            segments["churned_pro"] = [dict(r) for r in cur.fetchall()]

    return segments


async def generate_email(segment: str, user: dict) -> dict:
    name  = user.get("name") or "חבר"
    usage = user.get("usage", 0)
    days_since = (datetime.now() - user["created_at"]).days if user.get("created_at") else 0

    context = {
        "onboarding_d0": f"משתמש ({name}) נרשם זה עתה לפני שעות ספורות. ברכו אותו וספרו לו את הצעד הראשון.",
        "onboarding_d2": f"משתמש ({name}) נרשם לפני 2 ימים. עשה {usage} סיכומים. הזכירו לו את פיצ'ר הסיכום החכם (Pro).",
        "onboarding_d5": f"משתמש ({name}) נרשם לפני 5 ימים, עדיין free, {usage} סיכומים. אולי התאכזב? בדקו.",
        "new_user":      f"משתמש חדש ({name}) שנרשם לפני {days_since} ימים, עוד לא ניסה את המוצר.",
        "engaged_free":  f"משתמש ({name}) שכבר עשה {usage} סיכומים החודש — ברור שאוהב. עדיין לא Pro.",
        "dormant":       f"משתמש ({name}) שנרשם לפני {days_since} ימים אבל לא חזר בכלל.",
        "churned_pro":   f"משתמש ({name}) שהיה Pro וביטל. זה ציון כישלון שלנו, לא שלו.",
    }

    cta = {
        "onboarding_d0": f"{APP_URL} — מתחילים עכשיו",
        "onboarding_d2": f"{APP_URL}/pricing — ראה מה Pro מציע",
        "onboarding_d5": f"{APP_URL} — חוזרים?",
        "new_user":      f"{APP_URL} — תנסה עכשיו (בחינם!)",
        "engaged_free":  f"{APP_URL}/pricing — Pro ב-₪29/חודש",
        "dormant":       f"{APP_URL} — חוזרים? יש לך 3 סיכומים חינם",
        "churned_pro":   f"{APP_URL}/pricing — חוזרים? הציע להם 20% הנחה",
    }

    prompt = f"""כתוב מייל מכירה קצר ואנושי.

הקשר: {context[segment]}
מוצר: PodSnap — מסכם פודקאסטים ביוטיוב לעברית תוך שניות.
Free: 3 סיכומים/חודש | Pro ₪29: ללא הגבלה + מצגות AI + הזדמנויות עסקיות.
CTA: {cta[segment]}

ענה JSON בלבד:
{{"subject": "נושא המייל (עד 8 מילים)", "body_text": "גוף המייל (3-5 משפטים, ישיר ואנושי, \\n לשורה חדשה)", "cta_text": "טקסט הכפתור (3-4 מילים)", "cta_url": "{APP_URL}/pricing"}}"""

    text = await ask_ai_with_system_async(SYSTEM, prompt, max_tokens=600)
    if "```json" in text:
        text = text.split("```json")[1].split("```")[0].strip()
    elif "```" in text:
        text = text.split("```")[1].split("```")[0].strip()
    start = text.find("{")
    end   = text.rfind("}") + 1
    return json.loads(text[start:end])


def send_resend(to_email: str, subject: str, body_text: str, cta_text: str, cta_url: str) -> bool:
    if not RESEND_KEY:
        print(f"  [skip — no RESEND_KEY] {to_email}")
        return False

    lines = [f"<p>{l}</p>" if l.strip() else "<br>" for l in body_text.split("\\n")]
    html = f"""<div dir="rtl" style="font-family:Arial,sans-serif;max-width:560px;margin:0 auto;padding:24px">
  <div style="background:linear-gradient(135deg,#1a0533,#2d1060);padding:18px 20px;border-radius:10px;margin-bottom:24px">
    <h1 style="color:#fff;margin:0;font-size:1.3rem">PodSnap</h1>
    <p style="color:#a78bfa;margin:4px 0 0;font-size:.85rem">מסכם פודקאסטים ביוטיוב לעברית</p>
  </div>
  {''.join(lines)}
  <div style="text-align:center;margin:28px 0">
    <a href="{cta_url}"
       style="background:#7c3aed;color:#fff;padding:12px 28px;border-radius:8px;text-decoration:none;font-weight:bold;font-size:1rem">
      {cta_text}
    </a>
  </div>
  <hr style="border:none;border-top:1px solid #eee;margin:20px 0">
  <p style="color:#aaa;font-size:.75rem;text-align:center">
    PodSnap · <a href="{APP_URL}/login" style="color:#aaa">כניסה לחשבון</a>
  </p>
</div>"""

    import requests as r
    try:
        resp = r.post(
            "https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {RESEND_KEY}", "Content-Type": "application/json"},
            json={"from": FROM_EMAIL, "to": [to_email], "subject": subject, "html": html},
            timeout=15,
        )
        return resp.status_code == 200
    except Exception as e:
        print(f"  Resend error: {e}")
        return False


async def send_telegram_report(stats: dict, today: str):
    if not TELEGRAM_TOKEN or not ADMIN_CHAT_ID:
        return
    total = sum(v["sent"] for v in stats.values())
    msg = f"<b>📧 דני — Sales Report | {today}</b>\n\n"
    labels = {
        "new_user":     "🆕 משתמשים חדשים",
        "engaged_free": "🔥 משתמשים מעורבים",
        "dormant":      "😴 לא פעילים",
        "churned_pro":  "💔 ביטלו Pro",
    }
    for seg, data in stats.items():
        msg += f"{labels[seg]}: {data['sent']}/{data['eligible']} מיילים\n"
    msg += f"\n<b>סה\"כ: {total} מיילים נשלחו</b>\n<i>— דני, Sales Bot</i>"

    async with httpx.AsyncClient() as http:
        try:
            await http.post(
                f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                json={"chat_id": ADMIN_CHAT_ID, "text": msg, "parse_mode": "HTML"},
            )
        except Exception as e:
            print(f"Telegram error: {e}")


async def run():
    today = str(date.today())
    print(f"\nדני — Sales Bot | {today}")
    print("=" * 50)

    ensure_outreach_table()
    segments = get_segment_users()
    stats: dict[str, dict] = {}

    for segment, users in segments.items():
        eligible = [u for u in users if not already_sent(u["id"], segment)]
        sent_count = 0

        print(f"\n[{segment}] {len(eligible)} משתמשים זכאים")

        for user in eligible:
            try:
                email_data = await generate_email(segment, user)
                ok = send_resend(
                    to_email=user["email"],
                    subject=email_data["subject"],
                    body_text=email_data["body_text"],
                    cta_text=email_data["cta_text"],
                    cta_url=email_data["cta_url"],
                )
                if ok:
                    mark_sent(user["id"], segment)
                    sent_count += 1
                    print(f"  OK  {user['email']} — {email_data['subject']}")
                else:
                    print(f"  FAIL {user['email']}")
            except Exception as e:
                print(f"  ERROR {user['email']}: {e}")

        stats[segment] = {"eligible": len(eligible), "sent": sent_count}

    total = sum(v["sent"] for v in stats.values())
    print(f"\nסה\"כ: {total} מיילים נשלחו")

    await send_telegram_report(stats, today)


if __name__ == "__main__":
    asyncio.run(run())
