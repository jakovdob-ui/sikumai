"""
LinkedIn Autonomous Marketing Agent
Runs daily via cron. Checks configured YouTube channels for new videos,
generates LinkedIn posts via Claude, and publishes automatically.
"""
import os
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv

load_dotenv()

import requests
from ai_utils import ask_ai
import db

LINKEDIN_ADMIN_TOKEN = os.getenv('LINKEDIN_ADMIN_TOKEN', '')
LINKEDIN_ADMIN_URN   = os.getenv('LINKEDIN_ADMIN_URN', '')
YOUTUBE_CHANNELS     = os.getenv('YOUTUBE_CHANNELS', '')
ANTHROPIC_API_KEY    = os.getenv('ANTHROPIC_API_KEY', '')
TELEGRAM_TOKEN       = os.getenv('TELEGRAM_TOKEN', '')
ADMIN_CHAT_ID        = os.getenv('ADMIN_CHAT_ID', '')
TELEGRAM_CHANNELS    = os.getenv('TELEGRAM_CHANNELS', '')
FACEBOOK_PAGE_ID     = os.getenv('FACEBOOK_PAGE_ID', '')
FACEBOOK_PAGE_TOKEN  = os.getenv('FACEBOOK_PAGE_TOKEN', '')
MAKE_WEBHOOK_URL     = os.getenv('MAKE_WEBHOOK_URL', '')
SUPADATA_API_KEY     = os.getenv('SUPADATA_API_KEY', '')
LOOKBACK_HOURS       = int(os.getenv('AGENT_LOOKBACK_HOURS', '72'))
MAX_POSTS_PER_RUN    = int(os.getenv('AGENT_MAX_POSTS', '3'))


def log(msg):
    print(f'[{datetime.now().strftime("%H:%M:%S")}] {msg}', flush=True)


def notify_telegram(text):
    if not TELEGRAM_TOKEN or not ADMIN_CHAT_ID:
        return
    try:
        requests.post(
            f'https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage',
            json={'chat_id': ADMIN_CHAT_ID, 'text': text, 'parse_mode': 'HTML'},
            timeout=10
        )
    except Exception as e:
        log(f'Telegram error: {e}')


def get_channel_videos(channel_id, since_hours=48):
    url = f'https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}'
    try:
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()
    except Exception as e:
        log(f'RSS fetch failed for {channel_id}: {e}')
        return []

    ns = {
        'atom': 'http://www.w3.org/2005/Atom',
        'yt': 'http://www.youtube.com/xml/schemas/2015',
        'media': 'http://search.yahoo.com/mrss/',
    }
    try:
        root = ET.fromstring(resp.text)
    except Exception as e:
        log(f'RSS parse failed: {e}')
        return []

    cutoff = datetime.now(timezone.utc) - timedelta(hours=since_hours)
    videos = []
    for entry in root.findall('atom:entry', ns):
        video_id_el = entry.find('yt:videoId', ns)
        title_el    = entry.find('atom:title', ns)
        published_el= entry.find('atom:published', ns)
        if video_id_el is None or title_el is None or published_el is None:
            continue
        try:
            pub = datetime.fromisoformat(published_el.text.replace('Z', '+00:00'))
        except Exception:
            continue
        if pub >= cutoff:
            videos.append({'video_id': video_id_el.text, 'title': title_el.text, 'published': pub})
    return videos


def get_transcript(video_id):
    if not SUPADATA_API_KEY:
        return None
    try:
        resp = requests.get(
            'https://api.supadata.ai/v1/youtube/transcript',
            params={'url': f'https://www.youtube.com/watch?v={video_id}', 'text': 'false'},
            headers={'x-api-key': SUPADATA_API_KEY},
            timeout=30
        )
        if resp.status_code == 200:
            data = resp.json()
            segments = data.get('content', [])
            if isinstance(segments, list) and segments:
                return ' '.join(s.get('text', '') for s in segments if isinstance(s, dict))
    except Exception as e:
        log(f'Transcript error for {video_id}: {e}')
    return None


def _detect_lang(text):
    if not text:
        return 'he'
    sample = text[:300]
    non_ascii = sum(1 for c in sample if ord(c) > 127)
    return 'he' if non_ascii > len(sample) * 0.1 else 'en'


def generate_post(title, transcript):
    content_snippet = transcript[:3000] if transcript else f'פרק: {title}'
    lang = _detect_lang(transcript or title)
    if lang == 'en':
        prompt = f'''Write a LinkedIn post in English marketing PodSnap (getpodsnap.com).

PodSnap serves TWO audiences from one YouTube link, in under 60 seconds:
• 💼 Business owners → 3-5 business opportunities per episode (target audience, how to execute, revenue potential)
• 🎬 Content creators → ready-to-post content for 6 platforms: Instagram, TikTok, X/Twitter, LinkedIn, YouTube, WhatsApp

Use this episode as proof it works:
Title: {title}
Content: {content_snippet}

Structure:
1. Open with a HOOK — a problem that business owners OR content creators feel (too much content, no time to extract value, spending hours creating posts that could take seconds)
2. Introduce PodSnap: "One YouTube link. Two types of output." — briefly mention both business opportunities AND the 6-platform content
3. ONE specific result from THIS episode (1 sentence — e.g. what business idea or content angle this episode would produce)
4. CTA: "First 3 analyses free → getpodsnap.com"
5. 3-4 hashtags: #AI #ContentCreation #BusinessGrowth #Productivity

Length: 150-200 words. Write only the post, no title or explanation.'''
        footer = "\n\n🎙️ First 3 free → getpodsnap.com"
    else:
        prompt = f'''כתוב פוסט LinkedIn בעברית שמשווק את PodSnap (getpodsnap.com).

PodSnap משרת שני קהלים מקישור YouTube אחד, תוך 60 שניות:
• 💼 בעלי עסקים ← 3-5 הזדמנויות עסקיות מכל פרק (קהל יעד, דרך מימוש, פוטנציאל הכנסה)
• 🎬 יוצרי תוכן ← תוכן מוכן ל-6 פלטפורמות: Instagram, TikTok, X/Twitter, LinkedIn, YouTube, WhatsApp

השתמש בפרק הזה כהוכחה שזה עובד:
כותרת: {title}
תוכן: {content_snippet}

מבנה:
1. פתח עם HOOK — בעיה שבעל עסק או יוצר תוכן מרגיש (יותר מדי תוכן, אין זמן להפיק ממנו ערך, שעות על יצירת פוסטים שיכלו לקחת שניות)
2. הצג את PodSnap: "קישור YouTube אחד. שני סוגי פלט." — ציין בקצרה גם הזדמנויות עסקיות וגם תוכן ל-6 פלטפורמות
3. תוצאה ספציפית אחת מהפרק הזה (משפט אחד — למשל איזו הזדמנות עסקית או זווית תוכן הפרק הזה היה מייצר)
4. CTA: "3 ניתוחים ראשונים חינם ← getpodsnap.com"
5. 3-4 hashtags: #AI #יוצריתוכן #עסקים #פרודוקטיביות

אורך: 150-200 מילים. כתוב רק את הפוסט, ללא כותרת או הסבר.'''
        footer = "\n\n🎙️ 3 ניתוחים ראשונים חינם ← getpodsnap.com"
    return ask_ai(prompt, max_tokens=600) + footer


def generate_telegram_post(title, transcript):
    content_snippet = transcript[:2000] if transcript else f'פרק: {title}'
    lang = _detect_lang(transcript or title)
    if lang == 'en':
        prompt = f'''Write a short Telegram post in English marketing PodSnap (getpodsnap.com).

PodSnap gives TWO types of people exactly what they need from any YouTube video in 60 seconds:
💼 Business owners → business opportunities extracted
🎬 Content creators → posts for 6 platforms ready to publish

Episode used as example:
Title: {title}
Content: {content_snippet}

Structure (3-4 sentences only):
1. Hook — a pain that business owners OR creators feel (too much to watch, no time to create content from it)
2. Introduce PodSnap — mention both audiences and what each gets
3. ONE concrete result from this episode (1 sentence)
4. "First 3 analyses free → getpodsnap.com"

Write only the post.'''
        footer = ""
    else:
        prompt = f'''כתוב פוסט קצר לטלגרם בעברית שמשווק את PodSnap (getpodsnap.com).

PodSnap נותן לשני סוגי אנשים בדיוק מה שהם צריכים מכל סרטון YouTube תוך 60 שניות:
💼 בעלי עסקים ← הזדמנויות עסקיות שחולצו מהפרק
🎬 יוצרי תוכן ← פוסטים ל-6 פלטפורמות מוכנים לפרסום

פרק לדוגמה:
כותרת: {title}
תוכן: {content_snippet}

מבנה (3-4 משפטים בלבד):
1. Hook — כאב שבעל עסק או יוצר תוכן מרגיש (יותר מדי תוכן לצרוך, אין זמן ליצור תוכן ממנו)
2. הצג את PodSnap — ציין שני הקהלים ומה כל אחד מקבל
3. תוצאה קונקרטית אחת מהפרק הזה (משפט אחד)
4. "3 ניתוחים ראשונים חינם ← getpodsnap.com"

כתוב רק את הפוסט.'''
        footer = ""
    return ask_ai(prompt, max_tokens=400) + footer


def publish_to_telegram_channels(post_text):
    """מפרסם לכל ערוצי Telegram שהוגדרו ב-TELEGRAM_CHANNELS."""
    if not TELEGRAM_TOKEN or not TELEGRAM_CHANNELS:
        log('TELEGRAM_CHANNELS not configured — skipping Telegram publish')
        return 0
    channels = [c.strip() for c in TELEGRAM_CHANNELS.split(',') if c.strip()]
    published = 0
    for chat_id in channels:
        try:
            resp = requests.post(
                f'https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage',
                json={
                    'chat_id': chat_id,
                    'text': post_text,
                    'parse_mode': 'HTML',
                    'disable_web_page_preview': False,
                },
                timeout=10
            )
            if resp.status_code == 200:
                log(f'  Telegram OK: {chat_id}')
                published += 1
            else:
                log(f'  Telegram error {chat_id}: {resp.text[:100]}')
        except Exception as e:
            log(f'  Telegram exception {chat_id}: {e}')
    return published


def generate_facebook_post(title, transcript):
    content_snippet = transcript[:2000] if transcript else f'פרק: {title}'
    prompt = f'''כתוב פוסט קצר בעברית לעמוד Facebook שמשווק את PodSnap — כלי AI לבעלי עסקים ויוצרי תוכן.

כותרת הפרק: {title}
תוכן: {content_snippet}

הנחיות:
- 3-4 משפטים, קריא ומושך
- פנה לאחד משני הקהלים: בעל עסק שמחפש הזדמנויות עסקיות, או יוצר תוכן שרוצה לפרסם ל-6 פלטפורמות בבת אחת
- תובנה אחת חזקה מהפרק שרלוונטית לקהל היעד שבחרת
- CTA קצר: "getpodsnap.com"
- כתוב רק את הפוסט'''
    post_text = ask_ai(prompt, max_tokens=400)
    post_text += "\n\n🎙️ ניתוח AI מלא של פודקאסטים → getpodsnap.com"
    return post_text


def publish_to_facebook(post_text):
    if not FACEBOOK_PAGE_ID or not FACEBOOK_PAGE_TOKEN:
        log('FACEBOOK_PAGE_ID/TOKEN not configured — skipping Facebook')
        return False
    try:
        resp = requests.post(
            f'https://graph.facebook.com/v19.0/{FACEBOOK_PAGE_ID}/feed',
            data={
                'message': post_text,
                'access_token': FACEBOOK_PAGE_TOKEN,
            },
            timeout=15
        )
        if resp.status_code == 200:
            post_id = resp.json().get('id', '')
            log(f'  Facebook OK: {post_id}')
            return True
        else:
            log(f'  Facebook error: {resp.text[:150]}')
            return False
    except Exception as e:
        log(f'  Facebook exception: {e}')
        return False


def publish_to_make(post_text, title, video_id):
    if not MAKE_WEBHOOK_URL:
        return False
    try:
        resp = requests.post(MAKE_WEBHOOK_URL, json={
            'message': post_text,
            'title': title,
            'video_url': f'https://youtube.com/watch?v={video_id}',
        }, timeout=10)
        if resp.status_code == 200:
            log('  Make webhook OK')
            return True
        else:
            log(f'  Make webhook error: {resp.status_code}')
            return False
    except Exception as e:
        log(f'  Make webhook exception: {e}')
        return False


def publish_to_linkedin(post_text):
    if not LINKEDIN_ADMIN_TOKEN or not LINKEDIN_ADMIN_URN:
        log('LinkedIn token or URN missing — skipping publish')
        return None
    try:
        resp = requests.post(
            'https://api.linkedin.com/v2/ugcPosts',
            headers={
                'Authorization': f'Bearer {LINKEDIN_ADMIN_TOKEN}',
                'Content-Type': 'application/json',
                'X-Restli-Protocol-Version': '2.0.0',
            },
            json={
                'author': LINKEDIN_ADMIN_URN,
                'lifecycleState': 'PUBLISHED',
                'specificContent': {
                    'com.linkedin.ugc.ShareContent': {
                        'shareCommentary': {'text': post_text},
                        'shareMediaCategory': 'NONE',
                    }
                },
                'visibility': {'com.linkedin.ugc.MemberNetworkVisibility': 'PUBLIC'},
            },
            timeout=15
        )
        if resp.status_code in (200, 201):
            return resp.headers.get('X-RestLi-Id', 'published')
        else:
            log(f'LinkedIn API error {resp.status_code}: {resp.text[:200]}')
            return None
    except Exception as e:
        log(f'LinkedIn publish error: {e}')
        return None


def run():
    if not YOUTUBE_CHANNELS:
        log('YOUTUBE_CHANNELS not configured — nothing to do')
        return

    channel_ids = [c.strip() for c in YOUTUBE_CHANNELS.split(',') if c.strip()]
    log(f'Checking {len(channel_ids)} channel(s), lookback={LOOKBACK_HOURS}h')
    db.init()

    total_posted = 0
    for channel_id in channel_ids:
        if total_posted >= MAX_POSTS_PER_RUN:
            log(f'הגענו למקסימום {MAX_POSTS_PER_RUN} פוסטים — הנותרים יישלחו מחר')
            break
        log(f'Channel: {channel_id}')
        videos = get_channel_videos(channel_id, LOOKBACK_HOURS)
        log(f'  Found {len(videos)} recent video(s)')

        for video in videos:
            if total_posted >= MAX_POSTS_PER_RUN:
                break
            vid = video['video_id']
            title = video['title']

            if db.was_auto_posted(vid):
                log(f'  Skip (already posted): {title}')
                continue

            log(f'  Processing: {title} ({vid})')
            transcript = get_transcript(vid)
            log(f'  Transcript: {"OK" if transcript else "missing — using title only"}')

            try:
                li_post = generate_post(title, transcript)
                tg_post = generate_telegram_post(title, transcript)
                fb_post = generate_facebook_post(title, transcript)
            except Exception as e:
                log(f'  Claude error: {e}')
                continue

            post_urn  = publish_to_linkedin(li_post)
            tg_count  = publish_to_telegram_channels(tg_post)
            fb_ok     = publish_to_facebook(fb_post)
            make_ok   = publish_to_make(fb_post, title, vid)

            if post_urn or tg_count or fb_ok or make_ok:
                db.mark_auto_posted(vid, channel_id, title, li_post)
                total_posted += 1
                log(f'  Published! LinkedIn={bool(post_urn)} Telegram={tg_count} Facebook={fb_ok}')
                notify_telegram(
                    f'📢 <b>Auto-Post</b>\n'
                    f'📺 {title}\n'
                    f'🔗 youtube.com/watch?v={vid}\n'
                    f'LinkedIn: {"✅" if post_urn else "❌"} | '
                    f'Telegram: {tg_count} | '
                    f'Facebook: {"✅" if fb_ok else "❌"}\n\n'
                    f'{li_post[:200]}...'
                )
            else:
                log(f'  Publish failed on all platforms')

    log(f'Done. Posted {total_posted} new item(s).')
    if total_posted == 0:
        log('No new posts today.')


if __name__ == '__main__':
    run()
