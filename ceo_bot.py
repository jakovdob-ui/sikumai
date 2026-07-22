"""
CEO Bot — תבנית אוטונומיה לכל אפליקציה
========================================
העתק קובץ זה לכל פרויקט חדש.

משתני סביבה נדרשים ב-.env:
  TELEGRAM_TOKEN=...
  ADMIN_CHAT_ID=...

שימוש:
  import ceo_bot
  ceo_bot.notify("משהו קרה")
  ceo_bot.ask_approval("משתמש ביקש החזר", action_yes="refund:123", action_no="deny:123")
  ceo_bot.daily_briefing({"total": 47, "pro": 8, "new_today": 3, "mrr": 232})

Webhook (רישום חד-פעמי):
  python ceo_bot.py --register
"""
import os
import sys
import json
import requests as _http
from dotenv import load_dotenv

load_dotenv()

TOKEN    = os.getenv('TELEGRAM_TOKEN', '')
CHAT_ID  = os.getenv('ADMIN_CHAT_ID', '')
APP_URL  = os.getenv('APP_URL', '')          # https://getpodsnap.com
WEBHOOK_PATH = '/telegram-webhook'


# ─── שליחת הודעות ────────────────────────────────────────────────────────────

def notify(text: str, parse_mode: str = 'HTML') -> bool:
    """שולח הודעה פשוטה למנכ"ל."""
    if not TOKEN or not CHAT_ID:
        return False
    try:
        r = _http.post(
            f'https://api.telegram.org/bot{TOKEN}/sendMessage',
            json={'chat_id': CHAT_ID, 'text': text, 'parse_mode': parse_mode},
            timeout=8,
        )
        return r.status_code == 200
    except Exception:
        return False


def ask_approval(text: str, action_yes: str, action_no: str) -> bool:
    """
    שולח הודעה עם כפתורי ✅ אשר / ❌ דחה.
    action_yes / action_no = מחרוזת שתגיע ב-callback_data כשלוחצים.
    """
    if not TOKEN or not CHAT_ID:
        return False
    keyboard = {
        'inline_keyboard': [[
            {'text': '✅ אשר', 'callback_data': action_yes},
            {'text': '❌ דחה', 'callback_data': action_no},
        ]]
    }
    try:
        r = _http.post(
            f'https://api.telegram.org/bot{TOKEN}/sendMessage',
            json={
                'chat_id': CHAT_ID,
                'text': text,
                'parse_mode': 'HTML',
                'reply_markup': keyboard,
            },
            timeout=8,
        )
        return r.status_code == 200
    except Exception:
        return False


def answer_callback(callback_query_id: str, text: str = '✅') -> None:
    """מאשר ללחיצה על כפתור (מונע טעינה בממשק)."""
    try:
        _http.post(
            f'https://api.telegram.org/bot{TOKEN}/answerCallbackQuery',
            json={'callback_query_id': callback_query_id, 'text': text},
            timeout=5,
        )
    except Exception:
        pass


def edit_message(chat_id, message_id: int, new_text: str) -> None:
    """מעדכן הודעה קיימת (להסיר כפתורים אחרי לחיצה)."""
    try:
        _http.post(
            f'https://api.telegram.org/bot{TOKEN}/editMessageText',
            json={
                'chat_id': chat_id,
                'message_id': message_id,
                'text': new_text,
                'parse_mode': 'HTML',
            },
            timeout=5,
        )
    except Exception:
        pass


# ─── Briefing יומי ───────────────────────────────────────────────────────────

def daily_briefing(stats: dict, app_name: str = 'האפליקציה') -> bool:
    """
    שולח briefing בוקר סטנדרטי.
    stats צריך לכלול: total, pro, free, new_today, mrr
    שדות אופציונליים: new_yesterday, summaries_today, summaries_month
    """
    from datetime import date
    today = str(date.today())

    new_today     = stats.get('new_today', 0)
    new_yesterday = stats.get('new_yesterday', 0)
    trend = '📈' if new_today >= new_yesterday else '📉'

    lines = [
        f'☀️ <b>בוקר טוב יעקב — {app_name} | {today}</b>\n',
        f'👥 <b>משתמשים</b>',
        f'• סה"כ: {stats.get("total", 0)} | Pro: {stats.get("pro", 0)}',
        f'• היום: {trend} {new_today} הרשמות',
    ]

    if 'mrr' in stats:
        lines += [
            '',
            f'💰 <b>הכנסות</b>',
            f'• MRR: ₪{stats["mrr"]:,}',
        ]

    if 'summaries_today' in stats:
        lines += [
            '',
            f'🎙 <b>פעילות</b>',
            f'• סיכומים היום: {stats["summaries_today"]}',
            f'• החודש: {stats.get("summaries_month", 0)}',
        ]

    lines.append('\n<i>— Auto Briefing</i>')
    return notify('\n'.join(lines))


# ─── רישום Webhook ───────────────────────────────────────────────────────────

def register_webhook(app_url: str | None = None) -> bool:
    """
    מרשום את ה-webhook אצל Telegram.
    קורא פעם אחת; אחרי כן Telegram שולח callback לכל לחיצת כפתור.

    python ceo_bot.py --register
    """
    url = (app_url or APP_URL).rstrip('/') + WEBHOOK_PATH
    if not url.startswith('https'):
        print(f'APP_URL חייב להיות HTTPS: {url}')
        return False
    r = _http.post(
        f'https://api.telegram.org/bot{TOKEN}/setWebhook',
        json={'url': url},
        timeout=10,
    )
    ok = r.json().get('ok', False)
    print('Webhook רשום:' if ok else 'שגיאה:', r.json())
    return ok


# ─── Handler לשימוש ב-Flask / FastAPI ────────────────────────────────────────

def handle_webhook_payload(payload: dict, actions: dict) -> str:
    """
    מעבד payload שהגיע מ-Telegram webhook.

    actions = מילון { callback_data: callable }
    דוגמה:
      actions = {
          'refund:123': lambda: refund_user(123),
          'deny:123':   lambda: notify_user(123, 'נדחה'),
      }

    מחזיר: תשובה לשלוח ל-Telegram (מחרוזת לאישור).
    """
    cb = payload.get('callback_query')
    if not cb:
        return 'ok'

    cid       = cb['id']
    data      = cb.get('data', '')
    chat_id   = cb['message']['chat']['id']
    msg_id    = cb['message']['message_id']
    orig_text = cb['message'].get('text', '')

    handler = actions.get(data)
    if handler:
        try:
            result = handler()
            answer_callback(cid, '✅ בוצע')
            edit_message(chat_id, msg_id, f'{orig_text}\n\n✅ <b>בוצע</b>')
        except Exception as e:
            answer_callback(cid, f'❌ שגיאה: {e}')
    else:
        answer_callback(cid, '❓ פעולה לא מוכרת')

    return 'ok'


# ─── CLI ─────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    if '--register' in sys.argv:
        register_webhook()
    elif '--test' in sys.argv:
        notify('🔧 <b>CEO Bot — בדיקת חיבור</b>\nהכל עובד!')
        print('הודעת בדיקה נשלחה')
    else:
        print(__doc__)
