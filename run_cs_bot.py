"""
Customer Success Bot — רונה
============================
עוקבת אחרי משתמשי Pro, מזהה at-risk, חוגגת milestones.
Usage: python run_cs_bot.py
Cron: 0 10 * * *  (כל יום ב-10:00)

סגמנטים:
  1. at_risk_pro     — Pro user שפעילותו ירדה ב-50%+ מחודש קודם
  2. new_pro         — עלה ל-Pro לפני פחות מ-7 ימים (טיפ ראשון)
  3. milestone_10    — הגיע ל-10 סיכומים החודש
  4. power_user      — 20+ סיכומים — מציעים ambassador program
  5. tip_weekly      — Pro user פעיל — טיפ שבועי ביום ראשון
"""
import asyncio
import json
import os
import httpx
import psycopg2
import psycopg2.extras
import requests as r
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

SYSTEM = """שמך רונה — Customer Success של PodSnap.
את כותבת מיילים חמים, אישיים, ישראליים.
לא בוס, לא מכירות — חברה שמתעניינת.
כתבי בעברית, קצר, אנושי."""


def _conn():
    return psycopg2.connect(DATABASE_URL, sslmode="require")


def ensure_table():
    with _conn() as c:
        with c.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS cs_outreach (
                    id SERIAL PRIMARY KEY,
                    user_id INTEGER NOT NULL REFERENCES users(id),
                    type TEXT NOT NULL,
                    sent_at TIMESTAMP DEFAULT NOW()
                )
            """)
            # index לבדיקה מהירה
            cur.execute("""
                CREATE INDEX IF NOT EXISTS cs_outreach_user_type
                ON cs_outreach (user_id, type)
            """)
        c.commit()


def already_sent(uid: int, msg_type: str, within_days: int = 30) -> bool:
    since = datetime.now() - timedelta(days=within_days)
    with _conn() as c:
        with c.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM cs_outreach WHERE user_id=%s AND type=%s AND sent_at > %s",
                (uid, msg_type, since)
            )
            return cur.fetchone() is not None


def mark_sent(uid: int, msg_type: str):
    with _conn() as c:
        with c.cursor() as cur:
            cur.execute(
                "INSERT INTO cs_outreach (user_id, type) VALUES (%s, %s)",
                (uid, msg_type)
            )
        c.commit()


def get_segments() -> dict[str, list[dict]]:
    now    = datetime.now()
    month  = now.strftime("%Y-%m")
    prev_m = (now.replace(day=1) - timedelta(days=1)).strftime("%Y-%m")
    today  = now.date()
    ago_7d = today - timedelta(days=7)

    segs: dict[str, list[dict]] = {
        "new_pro":      [],
        "at_risk_pro":  [],
        "milestone_10": [],
        "power_user":   [],
        "tip_weekly":   [],
    }

    with _conn() as c:
        with c.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:

            # 1. new_pro — עלה ל-Pro לפני פחות מ-7 ימים
            cur.execute("""
                SELECT u.id, u.email, u.name, u.created_at,
                       COALESCE(ul.transcript_count, 0) AS usage_this_month
                FROM users u
                LEFT JOIN usage_log ul ON ul.user_id = u.id AND ul.month = %s
                WHERE u.plan = 'pro'
                  AND u.stripe_customer_id IS NOT NULL
                  AND u.created_at::date > %s
            """, (month, ago_7d))
            segs["new_pro"] = [dict(r) for r in cur.fetchall()]

            # 2. at_risk_pro — Pro שפעילותו ירדה ב-50%+ מחודש קודם
            cur.execute("""
                SELECT u.id, u.email, u.name,
                       COALESCE(curr.transcript_count, 0) AS usage_curr,
                       COALESCE(prev.transcript_count, 0) AS usage_prev
                FROM users u
                LEFT JOIN usage_log curr ON curr.user_id = u.id AND curr.month = %s
                LEFT JOIN usage_log prev ON prev.user_id = u.id AND prev.month = %s
                WHERE u.plan = 'pro'
                  AND COALESCE(prev.transcript_count, 0) >= 3
                  AND COALESCE(curr.transcript_count, 0) <= COALESCE(prev.transcript_count, 0) * 0.5
            """, (month, prev_m))
            segs["at_risk_pro"] = [dict(r) for r in cur.fetchall()]

            # 3. milestone_10 — הגיע ל-10 סיכומים החודש
            cur.execute("""
                SELECT u.id, u.email, u.name, ul.transcript_count AS usage_this_month
                FROM users u
                JOIN usage_log ul ON ul.user_id = u.id AND ul.month = %s
                WHERE ul.transcript_count >= 10
            """, (month,))
            segs["milestone_10"] = [dict(r) for r in cur.fetchall()]

            # 4. power_user — 20+ סיכומים החודש
            cur.execute("""
                SELECT u.id, u.email, u.name, ul.transcript_count AS usage_this_month
                FROM users u
                JOIN usage_log ul ON ul.user_id = u.id AND ul.month = %s
                WHERE ul.transcript_count >= 20
            """, (month,))
            segs["power_user"] = [dict(r) for r in cur.fetchall()]

            # 5. tip_weekly — Pro פעיל (3+ החודש) — טיפ שבועי (רק ביום ראשון)
            if now.weekday() == 6:  # ראשון
                cur.execute("""
                    SELECT u.id, u.email, u.name, ul.transcript_count AS usage_this_month
                    FROM users u
                    JOIN usage_log ul ON ul.user_id = u.id AND ul.month = %s
                    WHERE u.plan = 'pro'
                      AND ul.transcript_count >= 3
                """, (month,))
                segs["tip_weekly"] = [dict(r) for r in cur.fetchall()]

    return segs


TIPS = [
    "לחץ על כל טיימקוד בסיכום כדי לקפוץ ישר לרגע בסרטון — חוסך חיפוש",
    "מצגת AI מציגה רק את הנקודות החשובות — מושלם לשיתוף עם צוות",
    "בפודקאסטים עסקיים — נסה את זיהוי הזדמנויות עסקיות. מוצא דברים שפספסת",
    "שלח סיכום ישירות למייל שלך אחרי כל פרק — יוצר ארכיון אישי",
    "Ctrl+F בסיכום — מחפש מונח ספציפי שהמרצה הזכיר",
]


async def generate_email(seg: str, user: dict) -> dict:
    name  = user.get("name") or "חבר"
    usage = user.get("usage_this_month", user.get("usage_curr", 0))

    contexts = {
        "new_pro": f"משתמש {name} שדרג ל-Pro לפני כמה ימים. עדיין בהתחלה — {usage} סיכומים החודש.",
        "at_risk_pro": f"משתמש Pro ({name}) שהחודש עשה {usage} סיכומים לעומת {user.get('usage_prev',0)} בחודש שעבר. ירידה חדה.",
        "milestone_10": f"משתמש {name} הגיע ל-{usage} סיכומים החודש. מייסטון!",
        "power_user": f"משתמש {name} עשה {usage} סיכומים החודש — power user אמיתי.",
        "tip_weekly": f"משתמש Pro פעיל ({name}), {usage} סיכומים החודש. מייל שבועי עם טיפ.",
    }

    import random
    tip = random.choice(TIPS)

    ctas = {
        "new_pro":      (f"{APP_URL}", "פתח PodSnap"),
        "at_risk_pro":  (f"{APP_URL}", "חוזרים?"),
        "milestone_10": (f"{APP_URL}", "להמשך"),
        "power_user":   (f"mailto:hi@podsnap.app?subject=Ambassador", "צור קשר"),
        "tip_weekly":   (f"{APP_URL}", "נסה עכשיו"),
    }
    cta_url, cta_text = ctas[seg]

    extra = {
        "new_pro":      "ספר להם על טיפ אחד שישנה להם את החוויה.",
        "at_risk_pro":  "אל תמכור — שאל מה לא עבד. תהיה אנושי.",
        "milestone_10": "חגוג איתם. משפט קצר, חם, אמיתי.",
        "power_user":   "הצע להם להיות ambassador — 20% הנחה לחבר שיביאו.",
        "tip_weekly":   f"הטיפ השבועי: {tip}",
    }

    prompt = f"""כתוב מייל Customer Success קצר.

הקשר: {contexts[seg]}
{extra[seg]}
CTA: {cta_url} — כפתור: '{cta_text}'

ענה JSON בלבד:
{{"subject": "נושא המייל", "body_text": "גוף המייל (2-4 משפטים, \\n לשורה חדשה)", "cta_text": "{cta_text}", "cta_url": "{cta_url}"}}"""

    text = await ask_ai_with_system_async(SYSTEM, prompt, max_tokens=400)
    if "```json" in text:
        text = text.split("```json")[1].split("```")[0].strip()
    elif "```" in text:
        text = text.split("```")[1].split("```")[0].strip()
    return json.loads(text[text.find("{"):text.rfind("}")+1])


def send_email(to: str, subject: str, body: str, cta_text: str, cta_url: str) -> bool:
    if not RESEND_KEY:
        return False
    lines = [f"<p>{l}</p>" if l.strip() else "<br>" for l in body.split("\\n")]
    html = f"""<div dir="rtl" style="font-family:Arial,sans-serif;max-width:560px;margin:0 auto;padding:24px">
  <div style="background:linear-gradient(135deg,#1a0533,#2d1060);padding:16px 20px;border-radius:10px;margin-bottom:20px">
    <h1 style="color:#fff;margin:0;font-size:1.2rem">PodSnap</h1>
  </div>
  {''.join(lines)}
  <div style="text-align:center;margin:24px 0">
    <a href="{cta_url}" style="background:#7c3aed;color:#fff;padding:11px 26px;border-radius:8px;text-decoration:none;font-weight:bold">{cta_text}</a>
  </div>
  <p style="color:#aaa;font-size:.75rem;text-align:center">PodSnap · <a href="{APP_URL}/login" style="color:#aaa">כניסה</a></p>
</div>"""
    try:
        resp = r.post(
            "https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {RESEND_KEY}", "Content-Type": "application/json"},
            json={"from": FROM_EMAIL, "to": [to], "subject": subject, "html": html},
            timeout=15,
        )
        return resp.status_code == 200
    except Exception as e:
        print(f"  Resend error: {e}")
        return False


# כמה ימים צריכים לעבור בין כל סוג הודעה
COOLDOWN = {
    "new_pro":      7,
    "at_risk_pro":  14,
    "milestone_10": 30,
    "power_user":   60,
    "tip_weekly":   6,
}


async def run():
    today = str(date.today())
    print(f"\nרונה — Customer Success | {today}")
    print("=" * 50)

    ensure_table()
    segs    = get_segments()
    stats   = {}

    for seg, users in segs.items():
        cooldown  = COOLDOWN[seg]
        eligible  = [u for u in users if not already_sent(u["id"], seg, within_days=cooldown)]
        sent_cnt  = 0

        print(f"\n[{seg}] {len(eligible)} זכאים")

        for user in eligible:
            try:
                data = await generate_email(seg, user)
                ok   = send_email(user["email"], data["subject"], data["body_text"],
                                  data["cta_text"], data["cta_url"])
                if ok:
                    mark_sent(user["id"], seg)
                    sent_cnt += 1
                    print(f"  OK   {user['email']} — {data['subject']}")
                else:
                    print(f"  FAIL {user['email']}")
            except Exception as e:
                print(f"  ERR  {user['email']}: {e}")

        stats[seg] = {"eligible": len(eligible), "sent": sent_cnt}

    # דוח טלגרם
    total = sum(v["sent"] for v in stats.values())
    msg   = f"<b>💚 רונה — CS Report | {today}</b>\n\n"
    labels = {
        "new_pro":      "🆕 Pro חדשים",
        "at_risk_pro":  "⚠️ בסיכון לבטל",
        "milestone_10": "🏆 Milestone 10",
        "power_user":   "⚡ Power Users",
        "tip_weekly":   "💡 טיפ שבועי",
    }
    for seg, data in stats.items():
        if data["eligible"] > 0:
            msg += f"{labels[seg]}: {data['sent']}/{data['eligible']}\n"
    msg += f"\n<b>סה\"כ: {total} מיילים</b>\n<i>— רונה, Customer Success</i>"

    if TELEGRAM_TOKEN and ADMIN_CHAT_ID:
        async with httpx.AsyncClient() as http:
            await http.post(
                f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                json={"chat_id": ADMIN_CHAT_ID, "text": msg, "parse_mode": "HTML"},
            )

    print(f"\nסה\"כ: {total} מיילים נשלחו")


if __name__ == "__main__":
    asyncio.run(run())
