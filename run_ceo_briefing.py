"""
CEO Morning Briefing — PodSnap
Usage:  python run_ceo_briefing.py
Cron:   0 8 * * *   (כל בוקר ב-08:00 UTC)
"""
import os
import requests
import psycopg2
import psycopg2.extras
from datetime import date, timedelta
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN', '')
ADMIN_CHAT_ID  = os.getenv('ADMIN_CHAT_ID', '')
DATABASE_URL   = os.getenv('DATABASE_URL', '')
PRO_PRICE_ILS  = 29


def _conn():
    return psycopg2.connect(DATABASE_URL, sslmode='require')


def get_stats() -> dict:
    today     = date.today()
    yesterday = today - timedelta(days=1)

    with _conn() as c:
        with c.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:

            cur.execute("SELECT COUNT(*) AS n FROM users")
            total_users = cur.fetchone()['n']

            cur.execute("SELECT COUNT(*) AS n FROM users WHERE plan='pro'")
            pro_users = cur.fetchone()['n']

            cur.execute("SELECT COUNT(*) AS n FROM users WHERE created_at::date = %s", (today,))
            signups_today = cur.fetchone()['n']

            cur.execute("SELECT COUNT(*) AS n FROM users WHERE created_at::date = %s", (yesterday,))
            signups_yesterday = cur.fetchone()['n']

            cur.execute("SELECT COUNT(*) AS n FROM users WHERE created_at >= date_trunc('month', NOW())")
            signups_month = cur.fetchone()['n']

            cur.execute("SELECT COUNT(*) AS n FROM episodes WHERE created_at::date = %s", (yesterday,))
            summaries_yesterday = cur.fetchone()['n']

            cur.execute("SELECT COUNT(*) AS n FROM episodes WHERE created_at >= date_trunc('month', NOW())")
            summaries_month = cur.fetchone()['n']

    return {
        'total_users':       total_users,
        'pro_users':         pro_users,
        'mrr':               pro_users * PRO_PRICE_ILS,
        'signups_today':     signups_today,
        'signups_yesterday': signups_yesterday,
        'signups_month':     signups_month,
        'summaries_yesterday': summaries_yesterday,
        'summaries_month':   summaries_month,
        'date':              str(today),
    }


def build_message(s: dict) -> str:
    trend = '📈' if s['signups_today'] >= s['signups_yesterday'] else '📉'
    return (
        f'☀️ <b>בוקר טוב יעקב — PodSnap | {s["date"]}</b>\n\n'
        f'👥 <b>משתמשים</b>\n'
        f'• סה"כ: {s["total_users"]} | Pro: {s["pro_users"]}\n'
        f'• היום: {trend} {s["signups_today"]} הרשמות\n'
        f'• החודש: {s["signups_month"]} הרשמות\n\n'
        f'💰 <b>הכנסות</b>\n'
        f'• MRR: ₪{s["mrr"]:,} ({s["pro_users"]} × ₪{PRO_PRICE_ILS})\n\n'
        f'🎙 <b>סיכומים</b>\n'
        f'• אתמול: {s["summaries_yesterday"]}\n'
        f'• החודש: {s["summaries_month"]}\n\n'
        f'<i>— PodSnap Auto Briefing</i>'
    )


def send(text: str):
    if not TELEGRAM_TOKEN or not ADMIN_CHAT_ID:
        print('חסרים TELEGRAM_TOKEN / ADMIN_CHAT_ID ב-.env')
        return
    requests.post(
        f'https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage',
        json={'chat_id': ADMIN_CHAT_ID, 'text': text, 'parse_mode': 'HTML'},
        timeout=10,
    )
    print('✅ Briefing נשלח')


if __name__ == '__main__':
    stats = get_stats()
    msg   = build_message(stats)
    print(msg)
    send(msg)
