"""
Product Manager Bot — אורי
============================
מנתח שימוש שבועי ומייצר דוח product insights.
Usage: python run_pm_bot.py
Cron: 0 9 * * 0  (כל ראשון ב-9:00)
"""
import asyncio
import json
import os
import httpx
import psycopg2
import psycopg2.extras
from datetime import date, datetime, timedelta
from dotenv import load_dotenv
load_dotenv()

from ai_utils import ask_ai_with_system_async

DATABASE_URL   = os.getenv("DATABASE_URL", "")
ANTHROPIC_KEY  = os.getenv("ANTHROPIC_API_KEY", "")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
ADMIN_CHAT_ID  = os.getenv("ADMIN_CHAT_ID", "")

SYSTEM = """שמך אורי — Product Manager של PodSnap.
אתה מנתח נתוני שימוש ומחפש patterns.
אתה שואל: למה? ומה מכאן?
ענה בעברית. חתום: — אורי, PM"""


def _conn():
    return psycopg2.connect(DATABASE_URL, sslmode="require")


def collect_metrics() -> dict:
    now    = datetime.now()
    month  = now.strftime("%Y-%m")
    prev_m = (now.replace(day=1) - timedelta(days=1)).strftime("%Y-%m")
    week_ago = (now - timedelta(days=7)).date()

    with _conn() as c:
        with c.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:

            # סה"כ משתמשים
            cur.execute("SELECT COUNT(*) AS total FROM users")
            total_users = cur.fetchone()["total"]

            # משתמשי Pro
            cur.execute("SELECT COUNT(*) AS cnt FROM users WHERE plan='pro'")
            pro_users = cur.fetchone()["cnt"]

            # הרשמות החודש
            cur.execute("SELECT COUNT(*) AS cnt FROM users WHERE created_at::date >= %s", (now.replace(day=1).date(),))
            new_this_month = cur.fetchone()["cnt"]

            # הרשמות בשבוע האחרון
            cur.execute("SELECT COUNT(*) AS cnt FROM users WHERE created_at::date >= %s", (week_ago,))
            new_this_week = cur.fetchone()["cnt"]

            # סיכומים החודש
            cur.execute("SELECT COALESCE(SUM(transcript_count),0) AS cnt FROM usage_log WHERE month=%s", (month,))
            summaries_month = cur.fetchone()["cnt"]

            # סיכומים חודש קודם
            cur.execute("SELECT COALESCE(SUM(transcript_count),0) AS cnt FROM usage_log WHERE month=%s", (prev_m,))
            summaries_prev = cur.fetchone()["cnt"]

            # משתמשים פעילים החודש (לפחות סיכום אחד)
            cur.execute("SELECT COUNT(DISTINCT user_id) AS cnt FROM usage_log WHERE month=%s AND transcript_count > 0", (month,))
            active_users = cur.fetchone()["cnt"]

            # פעילים free vs pro
            cur.execute("""
                SELECT u.plan, COUNT(DISTINCT ul.user_id) AS cnt
                FROM usage_log ul
                JOIN users u ON u.id = ul.user_id
                WHERE ul.month = %s AND ul.transcript_count > 0
                GROUP BY u.plan
            """, (month,))
            plan_breakdown = {row["plan"]: row["cnt"] for row in cur.fetchall()}

            # Top users החודש
            cur.execute("""
                SELECT u.name, u.plan, ul.transcript_count
                FROM usage_log ul
                JOIN users u ON u.id = ul.user_id
                WHERE ul.month = %s
                ORDER BY ul.transcript_count DESC
                LIMIT 5
            """, (month,))
            top_users = [dict(r) for r in cur.fetchall()]

            # התפלגות שימוש (histogram buckets)
            cur.execute("""
                SELECT
                    COUNT(CASE WHEN transcript_count = 1 THEN 1 END) AS bucket_1,
                    COUNT(CASE WHEN transcript_count BETWEEN 2 AND 5 THEN 1 END) AS bucket_2_5,
                    COUNT(CASE WHEN transcript_count BETWEEN 6 AND 10 THEN 1 END) AS bucket_6_10,
                    COUNT(CASE WHEN transcript_count > 10 THEN 1 END) AS bucket_10plus
                FROM usage_log
                WHERE month = %s
            """, (month,))
            dist = dict(cur.fetchone())

            # Conversion rate: free שהפכו Pro (בעלי stripe_customer_id) מתוך כלל הרשומים
            cur.execute("SELECT COUNT(*) AS cnt FROM users WHERE stripe_customer_id IS NOT NULL")
            ever_pro = cur.fetchone()["cnt"]
            conversion_rate = round(ever_pro / max(total_users, 1) * 100, 1)

            # משתמשים שהגיעו למגבלת free (3 סיכומים) ועדיין free
            cur.execute("""
                SELECT COUNT(*) AS cnt
                FROM usage_log ul
                JOIN users u ON u.id = ul.user_id
                WHERE ul.month = %s AND ul.transcript_count >= 3 AND u.plan = 'free'
            """, (month,))
            hit_limit_free = cur.fetchone()["cnt"]

    return {
        "date": str(date.today()),
        "month": month,
        "total_users": total_users,
        "pro_users": pro_users,
        "free_users": total_users - pro_users,
        "new_this_month": new_this_month,
        "new_this_week": new_this_week,
        "conversion_rate_pct": conversion_rate,
        "summaries_this_month": summaries_month,
        "summaries_prev_month": summaries_prev,
        "summaries_growth_pct": round((summaries_month - summaries_prev) / max(summaries_prev, 1) * 100, 1),
        "active_users_month": active_users,
        "active_free": plan_breakdown.get("free", 0),
        "active_pro": plan_breakdown.get("pro", 0),
        "top_users": top_users,
        "usage_distribution": dist,
        "hit_limit_still_free": hit_limit_free,
    }


PM_PROMPT = """שבוע: {date}

נתוני שימוש של PodSnap:
━━━━━━━━━━━━━━━━━━━━━━
משתמשים: {total_users} סה"כ | {pro_users} Pro | {free_users} Free
הרשמות: {new_this_month} החודש | {new_this_week} השבוע
Conversion rate (free→Pro): {conversion_rate_pct}%

סיכומים: {summaries_this_month} החודש | {summaries_prev_month} חודש קודם | {summaries_growth_pct:+.1f}%
משתמשים פעילים: {active_users_month} | Free: {active_free} | Pro: {active_pro}
הגיעו למגבלת 3 ועדיין free: {hit_limit_still_free}

התפלגות שימוש:
  1 סיכום: {bucket_1} משתמשים
  2-5: {bucket_2_5} משתמשים
  6-10: {bucket_6_10} משתמשים
  10+: {bucket_10plus} משתמשים

Top 5 משתמשים החודש:
{top_users_str}
━━━━━━━━━━━━━━━━━━━━━━

ענה JSON בלבד:
{{"weekly_headline": "כותרת אחת שמסכמת את השבוע (עד 10 מילים)", "insights": ["insight 1 — תצפית + משמעות", "insight 2", "insight 3"], "friction_point": "איפה משתמשים נתקעים או עוזבים — ולמה", "feature_suggestions": ["פיצ'ר 1 עם נימוק", "פיצ'ר 2 עם נימוק"], "north_star_this_week": "מדד אחד שחשוב לשפר השבוע ולמה", "summary": "2 משפטים: מה הגדול ומה הצעד הבא"}}"""


async def analyze(metrics: dict) -> dict:
    top_str = "\n".join(
        f"  {u['name']} ({u['plan']}): {u['transcript_count']} סיכומים"
        for u in metrics["top_users"]
    ) or "  אין נתונים"

    dist = metrics["usage_distribution"]
    prompt = PM_PROMPT.format(
        date=metrics["date"],
        total_users=metrics["total_users"],
        pro_users=metrics["pro_users"],
        free_users=metrics["free_users"],
        new_this_month=metrics["new_this_month"],
        new_this_week=metrics["new_this_week"],
        conversion_rate_pct=metrics["conversion_rate_pct"],
        summaries_this_month=metrics["summaries_this_month"],
        summaries_prev_month=metrics["summaries_prev_month"],
        summaries_growth_pct=metrics["summaries_growth_pct"],
        active_users_month=metrics["active_users_month"],
        active_free=metrics["active_free"],
        active_pro=metrics["active_pro"],
        hit_limit_still_free=metrics["hit_limit_still_free"],
        bucket_1=dist.get("bucket_1", 0),
        bucket_2_5=dist.get("bucket_2_5", 0),
        bucket_6_10=dist.get("bucket_6_10", 0),
        bucket_10plus=dist.get("bucket_10plus", 0),
        top_users_str=top_str,
    )

    text = await ask_ai_with_system_async(SYSTEM, prompt, max_tokens=1500)
    if "```json" in text:
        text = text.split("```json")[1].split("```")[0].strip()
    elif "```" in text:
        text = text.split("```")[1].split("```")[0].strip()

    # fix newlines in strings
    fixed, in_str, i = [], False, 0
    while i < len(text):
        ch = text[i]
        if ch == '"' and (i == 0 or text[i-1] != '\\'):
            in_str = not in_str
        if in_str and ch == '\n':
            fixed.append('\\n')
        elif in_str and ch == '\r':
            pass
        else:
            fixed.append(ch)
        i += 1
    return json.loads(''.join(fixed)[text.find("{"):])


async def send_telegram(report: dict, metrics: dict, today: str):
    if not TELEGRAM_TOKEN or not ADMIN_CHAT_ID:
        return

    m = metrics
    r = report

    msg  = f"<b>📊 אורי — PM Weekly Report | {today}</b>\n\n"
    msg += f"<b>{r.get('weekly_headline','')}</b>\n\n"
    msg += f"👥 {m['total_users']} משתמשים | {m['pro_users']} Pro | Conv: {m['conversion_rate_pct']}%\n"
    msg += f"📈 סיכומים: {m['summaries_this_month']} ({m['summaries_growth_pct']:+.1f}% מחודש קודם)\n"
    msg += f"🔥 פעילים: {m['active_users_month']} | הגיעו למגבלה ועדיין free: {m['hit_limit_still_free']}\n\n"

    msg += "<b>Insights:</b>\n"
    for ins in r.get("insights", []):
        msg += f"• {ins}\n"

    msg += f"\n<b>Friction:</b> {r.get('friction_point','')}\n\n"

    msg += "<b>Feature Suggestions:</b>\n"
    for feat in r.get("feature_suggestions", []):
        msg += f"• {feat}\n"

    msg += f"\n<b>North Star השבוע:</b> {r.get('north_star_this_week','')}\n\n"
    msg += f"<b>סיכום:</b> {r.get('summary','')}\n\n"
    msg += "<i>— אורי, PM</i>"

    async with httpx.AsyncClient() as http:
        await http.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={"chat_id": ADMIN_CHAT_ID, "text": msg[:4000], "parse_mode": "HTML"},
        )


async def run():
    today = str(date.today())
    print(f"\nאורי — PM Bot | {today}")
    print("=" * 50)

    print("אוסף מדדים...")
    metrics = collect_metrics()

    print(f"  {metrics['total_users']} משתמשים | {metrics['pro_users']} Pro")
    print(f"  {metrics['summaries_this_month']} סיכומים החודש ({metrics['summaries_growth_pct']:+.1f}%)")

    print("Claude מנתח...")
    report = await analyze(metrics)

    print(f"  כותרת: {report.get('weekly_headline','')}")

    # שמור דוח
    os.makedirs("data", exist_ok=True)
    path = f"data/pm_report_{today}.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"metrics": metrics, "report": report}, f, ensure_ascii=False, indent=2)
    print(f"  נשמר: {path}")

    await send_telegram(report, metrics, today)
    print("  נשלח לטלגרם")


if __name__ == "__main__":
    asyncio.run(run())
