"""
CMO Agent — מיה
================
מייצרת תוכן שיווקי שבועי ל-PodSnap.
Usage: python run_cmo.py
Cron: 0 8 * * 1  (כל שני ב-8:00 — תחילת שבוע עבודה)
"""
import asyncio
import json
import httpx
import os
from datetime import date, datetime
from dotenv import load_dotenv
load_dotenv()

from ai_utils import ask_ai_with_system_async
TELEGRAM_TOKEN    = os.getenv("TELEGRAM_TOKEN")
ADMIN_CHAT_ID     = os.getenv("ADMIN_CHAT_ID")

# ── הכרת המוצר ───────────────────────────────────────────────
PRODUCT_BRIEF = """
שם מוצר: PodSnap
תיאור: כלי AI שמסכם פודקאסטים ביוטיוב לעברית — בשניות.
קהל יעד: דוברי עברית בישראל שמאזינים לפודקאסטים אבל אין להם זמן.

תכונות חינמיות:
• 3 סיכומים בחודש
• תמלול + תרגום לעברית
• צפייה בקטעים לפי טיימקוד
• מצגת PowerPoint בסיסית

Pro — ₪29/חודש:
• סיכומים ללא הגבלה
• סיכום AI חכם
• מצגת AI + Futuristic
• זיהוי הזדמנויות עסקיות מהפודקאסט
• שליחה למייל

יתרון תחרותי: היחיד שעושה את זה בעברית, כולל מצגות AI.
מחיר נמוך ביחס לערך — ₪29 = פחות מכוס קפה ביום.
"""

SYSTEM = """שמך מיה — CMO של PodSnap.
אתה מומחית שיווק דיגיטלי לשוק הישראלי.
את יודעת:
- מה עובד בפייסבוק/אינסטגרם/טיקטוק בעברית
- איך לדבר עם הישראלי הממוצע
- איך להמיר גולשים ללקוחות בתקציב 0
- וויראל מרקטינג, growth hacks, community building

את יוצרת תוכן שאנשים באמת ישתפו — לא פרסומות יבשות.
תמיד ענה בעברית. חתום: — מיה, CMO

CRITICAL: Return ONLY a raw JSON object. No markdown, no backticks, no code blocks.
Every string value must be a single line — use \\n for line breaks within text, never real newlines.
Never use unescaped double-quotes inside string values."""

WEEKLY_PROMPT = """תאריך: {date}
שבוע: {week_num} של 2026

""" + PRODUCT_BRIEF + """

צרי תוכנית שיווקית שבועית ל-PodSnap.

ענה JSON בלבד (ללא markdown, ללא backticks):
{
  "weekly_theme": "נושא/זווית שיווקית אחת שמרכזת את השבוע",
  "target_this_week": "סגמנט ספציפי לפנות אליו השבוע",
  "social_posts": [
    {
      "platform": "Facebook",
      "format": "פוסט",
      "hook": "השורה הראשונה שגורמת לעצור גלילה",
      "content": "טקסט הפוסט המלא (השתמש ב-\\n לשורות חדשות)",
      "hashtags": ["#PodSnap", "#פודקאסט"],
      "best_time": "מתי לפרסם"
    },
    {
      "platform": "Instagram",
      "format": "רילס",
      "hook": "...",
      "content": "...",
      "hashtags": ["#PodSnap"],
      "best_time": "..."
    },
    {
      "platform": "TikTok",
      "format": "סרטון",
      "hook": "...",
      "content": "...",
      "hashtags": ["#PodSnap"],
      "best_time": "..."
    }
  ],
  "video_idea": {
    "platform": "TikTok",
    "title": "כותרת הסרטון",
    "hook_seconds": "מה קורה ב-3 השניות הראשונות",
    "script_outline": "נקודות התסריט מופרדות ב-\\n",
    "why_viral": "למה זה יתפשט"
  },
  "growth_hack": {
    "tactic": "שם הטקטיקה",
    "description": "שלבים מופרדים ב-\\n",
    "cost": "0",
    "expected_result": "מה מצפים לקבל"
  },
  "community_play": {
    "where": "איפה יש קהל רלוונטי",
    "action": "מה לעשות שם",
    "message": "הודעה לדוגמה"
  },
  "email_subject": "נושא למייל",
  "week_goal": "KPI מספרי ומדיד לשבוע",
  "summary": "שני משפטים: פוקוס ולמה"
}"""


async def send_telegram(text: str):
    if not TELEGRAM_TOKEN or not ADMIN_CHAT_ID:
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    async with httpx.AsyncClient() as http:
        try:
            await http.post(url, json={
                "chat_id": ADMIN_CHAT_ID,
                "text": text[:4000],
                "parse_mode": "HTML"
            })
        except Exception as e:
            print(f"Telegram error: {e}")


def format_telegram_report(plan: dict, today: str) -> list[str]:
    """מחזיר רשימת הודעות (מפוצלות כי טלגרם 4096 תווים)."""
    msgs = []

    # הודעה 1 — כותרת + פוקוס
    m1 = f"<b>📣 מיה — תוכנית שיווק שבועית | {today}</b>\n\n"
    m1 += f"🎯 <b>נושא השבוע:</b> {plan.get('weekly_theme','')}\n"
    m1 += f"👥 <b>קהל יעד:</b> {plan.get('target_this_week','')}\n"
    m1 += f"📊 <b>יעד:</b> {plan.get('week_goal','')}\n\n"
    m1 += f"<b>📝 סיכום:</b> {plan.get('summary','')}"
    msgs.append(m1)

    # הודעה 2 — פוסטים
    posts = plan.get("social_posts", [])
    if posts:
        m2 = "<b>📱 פוסטים לשבוע:</b>\n\n"
        for i, post in enumerate(posts, 1):
            m2 += f"<b>{i}. {post.get('platform','')} — {post.get('format','')}</b>\n"
            m2 += f"🎣 Hook: <i>{post.get('hook','')}</i>\n"
            m2 += f"{post.get('content','')[:300]}\n"
            tags = " ".join(post.get("hashtags", [])[:4])
            m2 += f"{tags}\n"
            m2 += f"⏰ {post.get('best_time','')}\n\n"
        msgs.append(m2)

    # הודעה 3 — Growth Hack + Video + Community
    m3 = ""
    gh = plan.get("growth_hack", {})
    if gh:
        m3 += f"<b>🚀 Growth Hack:</b> {gh.get('tactic','')}\n"
        m3 += f"{gh.get('description','')}\n"
        m3 += f"💰 עלות: {gh.get('cost','')} | תוצאה: {gh.get('expected_result','')}\n\n"

    vid = plan.get("video_idea", {})
    if vid:
        m3 += f"<b>🎬 רעיון סרטון ({vid.get('platform','')}):</b>\n"
        m3 += f"כותרת: {vid.get('title','')}\n"
        m3 += f"Hook 3 שניות: {vid.get('hook_seconds','')}\n"
        m3 += f"למה viral: {vid.get('why_viral','')}\n\n"

    comm = plan.get("community_play", {})
    if comm:
        m3 += f"<b>🤝 Community:</b> {comm.get('where','')}\n"
        m3 += f"{comm.get('action','')}\n"

    email_subj = plan.get("email_subject","")
    if email_subj:
        m3 += f"\n<b>📧 נושא מייל:</b> {email_subj}"

    m3 += "\n\n<i>— מיה, CMO</i>"
    if m3.strip():
        msgs.append(m3)

    return msgs


async def run_cmo():
    today    = str(date.today())
    week_num = datetime.now().isocalendar()[1]

    print(f"\nמיה — CMO | {today} (שבוע {week_num})")
    print("=" * 50)

    prompt = WEEKLY_PROMPT.replace("{date}", today).replace("{week_num}", str(week_num))

    print("Gemini thinking...")
    text = await ask_ai_with_system_async(SYSTEM, prompt, max_tokens=4096)

    # Strip markdown code fences
    if "```json" in text:
        text = text.split("```json")[1].split("```")[0].strip()
    elif "```" in text:
        text = text.split("```")[1].split("```")[0].strip()

    start = text.find("{")
    end   = text.rfind("}") + 1
    raw   = text[start:end]

    # Fix literal newlines inside JSON string values (state machine)
    fixed = []
    in_str = False
    i = 0
    while i < len(raw):
        ch = raw[i]
        prev = raw[i-1] if i > 0 else ''
        if ch == '"' and prev != '\\':
            in_str = not in_str
            fixed.append(ch)
        elif in_str and ch == '\n':
            fixed.append('\\n')
        elif in_str and ch == '\r':
            pass
        else:
            fixed.append(ch)
        i += 1
    raw = ''.join(fixed)

    try:
        plan = json.loads(raw)
    except json.JSONDecodeError as e:
        # Save raw for debugging
        with open("data/cmo_debug.txt", "w", encoding="utf-8") as dbg:
            dbg.write(raw)
        print(f"JSON parse error at char {e.pos}: {e.msg}")
        print("Saved raw to data/cmo_debug.txt")
        # Minimal fallback
        plan = {
            "weekly_theme": "השקה ראשונית",
            "target_this_week": "יזמים ישראלים",
            "week_goal": "10 הרשמות חדשות",
            "summary": "שבוע ראשון — בניית מודעות",
            "social_posts": [],
            "growth_hack": {"tactic": "לא זמין", "description": "", "cost": "", "expected_result": ""},
            "video_idea": {},
            "community_play": {},
            "email_subject": "",
        }
        print("Using fallback plan")

    # שמור לקובץ
    os.makedirs("data", exist_ok=True)
    plan_path = f"data/cmo_plan_{today}.json"
    with open(plan_path, "w", encoding="utf-8") as f:
        json.dump(plan, f, ensure_ascii=False, indent=2)
    print(f"Plan saved: {plan_path}")

    # שלח לטלגרם
    msgs = format_telegram_report(plan, today)
    for msg in msgs:
        await send_telegram(msg)
        await asyncio.sleep(0.5)

    print(f"Sent {len(msgs)} messages to Telegram")
    print(f"Theme: {plan.get('weekly_theme','')}")
    print(f"Target: {plan.get('target_this_week','')}")
    gh = plan.get("growth_hack", {})
    if gh:
        print(f"Growth Hack: {gh.get('tactic','')}")


if __name__ == "__main__":
    asyncio.run(run_cmo())
