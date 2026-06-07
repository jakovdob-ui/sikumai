import re
import io
import os
import json
import tempfile
import subprocess
import anthropic
import requests as http_requests
import hmac
import hashlib
from dotenv import load_dotenv
from functools import wraps
from werkzeug.security import generate_password_hash, check_password_hash
from flask import Flask, render_template, request, jsonify, send_file, session, redirect
import db as user_db
# youtube_transcript_api כגיבוי בלבד — גישה ראשית דרך Invidious
try:
    from youtube_transcript_api import YouTubeTranscriptApi
    _YT_API_AVAILABLE = True
except ImportError:
    _YT_API_AVAILABLE = False
from deep_translator import GoogleTranslator
from pptx import Presentation
from pptx.util import Inches, Pt
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN

load_dotenv(os.path.join(os.path.dirname(__file__), '.env'))

app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY', 'shulchan4-secret-2026')

COOKIES_FILE = os.path.join(os.path.dirname(__file__), 'yt_cookies.txt')
RESEND_KEY   = os.getenv('RESEND_API_KEY', '')

LS_API_KEY        = os.getenv('LS_API_KEY', '')
LS_STORE_ID       = os.getenv('LS_STORE_ID', '')
LS_VARIANT_ID     = os.getenv('LS_VARIANT_ID', '')
LS_WEBHOOK_SECRET = os.getenv('LS_WEBHOOK_SECRET', '')
APP_URL           = os.getenv('APP_URL', 'http://localhost:5002')
FREE_LIMIT        = 3

user_db.init()

def current_user():
    uid = session.get('user_id')
    if not uid:
        return None
    return user_db.get_by_id(uid)


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('user_id'):
            return redirect('/login')
        return f(*args, **kwargs)
    return decorated


def pro_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        u = current_user()
        if not u:
            return jsonify({'error': 'לא מחובר', 'upgrade': False}), 401
        if u['plan'] != 'pro':
            return jsonify({'error': 'פיצ\'ר זה זמין לחברי Pro בלבד', 'upgrade': True}), 403
        return f(*args, **kwargs)
    return decorated


@app.route('/login', methods=['GET', 'POST'])
def login():
    if session.get('user_id'):
        return redirect('/')
    error = ''
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        pw    = request.form.get('password', '')
        u = user_db.get_by_email(email)
        if u and check_password_hash(u['password_hash'], pw):
            session['user_id'] = u['id']
            return redirect('/')
        error = 'אימייל או סיסמה שגויים'
    return render_template('login.html', error=error)


@app.route('/register', methods=['GET', 'POST'])
def register():
    if session.get('user_id'):
        return redirect('/')
    error = ''
    if request.method == 'POST':
        name  = request.form.get('name', '').strip()
        email = request.form.get('email', '').strip().lower()
        pw    = request.form.get('password', '')
        if not name or not email or not pw:
            error = 'נא למלא את כל השדות'
        elif len(pw) < 6:
            error = 'הסיסמה חייבת להכיל לפחות 6 תווים'
        elif user_db.get_by_email(email):
            error = 'האימייל כבר רשום במערכת'
        else:
            try:
                uid = user_db.create(email, generate_password_hash(pw), name)
                session['user_id'] = uid
                return redirect('/')
            except Exception:
                error = 'שגיאה בהרשמה, נסה שוב'
    return render_template('register.html', error=error)


@app.route('/logout')
def logout():
    session.clear()
    return redirect('/login')


@app.route('/pricing')
def pricing():
    u = current_user()
    upgraded = request.args.get('upgraded') == '1'
    return render_template('pricing.html', user=u, upgraded=upgraded)


@app.route('/create-checkout-session', methods=['POST'])
@login_required
def create_checkout():
    u = current_user()
    if u['plan'] == 'pro':
        return jsonify({'error': 'כבר מנוי Pro'}), 400
    if not LS_API_KEY:
        return jsonify({'error': 'מערכת התשלום לא מוגדרת עדיין'}), 500
    try:
        resp = http_requests.post(
            'https://api.lemonsqueezy.com/v1/checkouts',
            headers={
                'Authorization': f'Bearer {LS_API_KEY}',
                'Accept': 'application/vnd.api+json',
                'Content-Type': 'application/vnd.api+json',
            },
            json={
                'data': {
                    'type': 'checkouts',
                    'attributes': {
                        'checkout_data': {
                            'email': u['email'],
                            'custom': {'user_id': str(u['id'])},
                        },
                        'product_options': {
                            'redirect_url': APP_URL + '/pricing?upgraded=1',
                        },
                    },
                    'relationships': {
                        'store': {'data': {'type': 'stores', 'id': str(LS_STORE_ID)}},
                        'variant': {'data': {'type': 'variants', 'id': str(LS_VARIANT_ID)}},
                    },
                }
            },
            timeout=10,
        )
        resp.raise_for_status()
        checkout_url = resp.json()['data']['attributes']['url']
        return jsonify({'url': checkout_url})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/ls-webhook', methods=['POST'])
def ls_webhook():
    payload = request.get_data()
    signature = request.headers.get('X-Signature', '')
    if LS_WEBHOOK_SECRET:
        expected = hmac.new(LS_WEBHOOK_SECRET.encode(), payload, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, signature):
            return '', 400

    data = request.json or {}
    event = data.get('meta', {}).get('event_name', '')
    attrs = data.get('data', {}).get('attributes', {})

    if event == 'subscription_created':
        custom = data.get('meta', {}).get('custom_data', {})
        uid = int(custom.get('user_id', 0))
        if uid:
            customer_id = str(attrs.get('customer_id', ''))
            sub_id = str(data.get('data', {}).get('id', ''))
            portal_url = attrs.get('urls', {}).get('customer_portal', '')
            user_db.set_pro(uid, customer_id, sub_id, portal_url)

    elif event in ('subscription_cancelled', 'subscription_expired', 'subscription_paused'):
        customer_id = str(attrs.get('customer_id', ''))
        u = user_db.get_by_payment_customer(customer_id)
        if u:
            user_db.set_free(u['id'])

    return '', 200


@app.route('/billing-portal', methods=['POST'])
@login_required
def billing_portal():
    u = current_user()
    portal_url = u['portal_url'] if u['portal_url'] else None
    if not portal_url:
        return jsonify({'error': 'קישור לניהול מנוי לא זמין, פנה אלינו'}), 400
    return jsonify({'url': portal_url})


# ── yt-dlp availability ────────────────────────────────────
try:
    import yt_dlp
    _YTDLP_AVAILABLE = True
except ImportError:
    _YTDLP_AVAILABLE = False

# ── Invidious instances (ניסיון בסדר הזה) ─────────────────
INVIDIOUS_INSTANCES = [
    'https://inv.nadeko.net',
    'https://invidious.privacydev.net',
    'https://invidious.jing.rocks',
    'https://yewtu.be',
    'https://invidious.fdn.fr',
    'https://yt.cdaut.de',
    'https://invidious.drgns.space',
    'https://inv.zzls.xyz',
    'https://invidious.privacyredirect.com',
    'https://invidious.perennialte.ch',
]

def fetch_via_page_parse(video_id):
    """מחלץ תמלול מדף YouTube — עובד גם מ-cloud עם CONSENT cookie"""
    HEADERS = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
        'Accept-Language': 'en-US,en;q=0.9',
        'Cookie': 'SOCS=CAI; CONSENT=YES+1',
    }

    class Snippet:
        def __init__(self, start, text):
            self.start = start
            self.text  = text

    try:
        r = http_requests.get(f'https://www.youtube.com/watch?v={video_id}', headers=HEADERS, timeout=15)
        if r.status_code != 200:
            return None, None

        page = r.text
        print(f'[page-parse] status={r.status_code} size={len(page)} consent={"SOCS" in page or "consent" in page.lower()}')
        idx = page.find('"captionTracks"')
        if idx == -1:
            print('[page-parse] no captionTracks in page')
            return None, None

        start = page.find('[', idx)
        depth, end = 0, start
        for i, ch in enumerate(page[start:], start):
            if ch == '[': depth += 1
            elif ch == ']':
                depth -= 1
                if depth == 0:
                    end = i
                    break

        tracks = json.loads(page[start:end + 1])
        if not tracks:
            return None, None

        chosen = None
        for lang in ['he', 'iw', 'en']:
            for t in tracks:
                if lang in t.get('languageCode', '').lower():
                    chosen = t
                    break
            if chosen:
                break
        if not chosen:
            chosen = tracks[0]

        base_url = chosen.get('baseUrl', '')
        if not base_url:
            return None, None

        sep = '&' if '?' in base_url else '?'
        for fmt in ['vtt', 'json3']:
            tr = http_requests.get(base_url + sep + f'fmt={fmt}', headers=HEADERS, timeout=10)
            if tr.status_code != 200:
                continue
            if fmt == 'vtt':
                snippets = _parse_vtt(tr.text)
                if snippets:
                    lang_code = chosen.get('languageCode', 'he')
                    print(f'[page-parse vtt] {len(snippets)} snippets ({lang_code})')
                    return snippets, lang_code
            else:
                events = tr.json().get('events', [])
                snippets = []
                for ev in events:
                    if 'segs' not in ev:
                        continue
                    s = ev.get('tStartMs', 0) / 1000
                    txt = ' '.join(sg.get('utf8', '') for sg in ev['segs']).strip()
                    if txt:
                        snippets.append(Snippet(s, txt))
                if snippets:
                    lang_code = chosen.get('languageCode', 'he')
                    print(f'[page-parse json3] {len(snippets)} snippets ({lang_code})')
                    return snippets, lang_code
    except Exception as e:
        print(f'[page-parse] error: {e}')

    return None, None


def fetch_via_timedtext(video_id):
    """YouTube timedtext API ישיר — עובד לסרטונים ציבוריים עם כתוביות"""
    HEADERS = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
        'Accept-Language': 'he-IL,he;q=0.9,en;q=0.8',
        'Referer': 'https://www.youtube.com/',
    }
    for lang in ['iw', 'he', 'en', 'en-US']:
        try:
            url = f'https://www.youtube.com/api/timedtext?v={video_id}&lang={lang}&fmt=vtt'
            r = http_requests.get(url, headers=HEADERS, timeout=10)
            if r.status_code == 200 and len(r.text.strip()) > 100:
                snippets = _parse_vtt(r.text)
                if snippets:
                    print(f"[timedtext] {len(snippets)} snippets ({lang})")
                    return snippets, lang
        except Exception as e:
            print(f"[timedtext] {lang}: {e}")
    return None, None

def _parse_vtt(vtt_text):
    """ממיר WebVTT לרשימת snippets עם .start ו-.text"""
    class Snippet:
        def __init__(self, start, text):
            self.start = start
            self.text  = text

    snippets = []
    lines = vtt_text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        # זיהוי שורת זמן: 00:00:00.000 --> 00:00:03.000
        if '-->' in line:
            time_part = line.split('-->')[0].strip()
            parts = time_part.split(':')
            try:
                if len(parts) == 3:
                    h, m, s = parts
                    start_sec = int(h)*3600 + int(m)*60 + float(s.replace(',', '.'))
                else:
                    m, s = parts
                    start_sec = int(m)*60 + float(s.replace(',', '.'))
            except:
                i += 1
                continue
            # אסוף את שורות הטקסט
            i += 1
            text_lines = []
            while i < len(lines) and lines[i].strip():
                t = lines[i].strip()
                # נקה תגיות HTML כמו <c>, </c>
                import re as _re
                t = _re.sub(r'<[^>]+>', '', t)
                if t:
                    text_lines.append(t)
                i += 1
            if text_lines:
                text = ' '.join(text_lines)
                # הסר כפילויות של הפסקה האחרונה
                if snippets and snippets[-1].text == text:
                    i += 1
                    continue
                snippets.append(Snippet(start_sec, text))
        i += 1
    return snippets

def fetch_via_ytdlp(video_id):
    """מוריד תמלול דרך yt-dlp — הכי אמין, תומך בכתוביות אוטומטיות"""
    if not _YTDLP_AVAILABLE:
        return None, None

    class Snippet:
        def __init__(self, start, text):
            self.start = start
            self.text  = text

    ydl_opts = {
        'skip_download': True,
        'writesubtitles': True,
        'writeautomaticsub': True,
        'subtitleslangs': ['he', 'iw', 'en'],
        'subtitlesformat': 'vtt',
        'quiet': True,
        'no_warnings': True,
    }
    if os.path.exists(COOKIES_FILE):
        ydl_opts['cookiefile'] = COOKIES_FILE

    url = f'https://www.youtube.com/watch?v={video_id}'
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            subs = info.get('subtitles', {})
            auto_subs = info.get('automatic_captions', {})

            chosen_lang = None
            chosen_data = None
            for lang in ['he', 'iw', 'en']:
                if lang in subs:
                    chosen_lang = lang
                    chosen_data = subs[lang]
                    break
            if not chosen_data:
                for lang in ['he', 'iw', 'en']:
                    if lang in auto_subs:
                        chosen_lang = lang
                        chosen_data = auto_subs[lang]
                        break
            if not chosen_data and subs:
                chosen_lang = list(subs.keys())[0]
                chosen_data = subs[chosen_lang]
            if not chosen_data and auto_subs:
                chosen_lang = list(auto_subs.keys())[0]
                chosen_data = auto_subs[chosen_lang]

            if not chosen_data:
                return None, None

            vtt_url = None
            for fmt in chosen_data:
                if fmt.get('ext') == 'vtt':
                    vtt_url = fmt.get('url')
                    break
            if not vtt_url and chosen_data:
                base_url = chosen_data[0].get('url', '')
                if 'youtube.com/api/timedtext' in base_url:
                    sep = '&' if '?' in base_url else '?'
                    vtt_url = base_url + sep + 'fmt=vtt'
                else:
                    vtt_url = base_url

            if not vtt_url:
                return None, None

            rv = http_requests.get(vtt_url, timeout=15)
            if rv.status_code != 200:
                return None, None

            snippets = _parse_vtt(rv.text)
            if snippets:
                print(f"[yt-dlp] {len(snippets)} snippets ({chosen_lang})")
                return snippets, chosen_lang

    except Exception as e:
        print(f"[yt-dlp] error: {e}")

    return None, None


def fetch_via_invidious(video_id):
    """מוריד תמלול דרך Invidious API — עובד מכל IP"""
    HEADERS_INV = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/122.0',
        'Accept': 'application/json',
    }
    lang_priority = ['he', 'iw', 'Hebrew', 'en', 'English']

    for base in INVIDIOUS_INSTANCES:
        try:
            # שלב 1: קבל רשימת כתוביות
            r = http_requests.get(
                f'{base}/api/v1/captions/{video_id}',
                headers=HEADERS_INV, timeout=10)
            if r.status_code != 200:
                continue

            captions = r.json().get('captions', [])
            if not captions:
                continue

            # שלב 2: בחר שפה לפי עדיפות
            chosen = None
            for lang in lang_priority:
                for cap in captions:
                    if lang.lower() in cap.get('language_code','').lower() or \
                       lang.lower() in cap.get('label','').lower():
                        chosen = cap
                        break
                if chosen:
                    break
            if not chosen:
                chosen = captions[0]  # כל שפה שיש

            # שלב 3: הורד את קובץ ה-VTT
            cap_url = chosen.get('url', '')
            if not cap_url.startswith('http'):
                cap_url = base + cap_url
            # הוסף format=vtt
            if '?' in cap_url:
                cap_url += '&format=vtt'
            else:
                cap_url += '?format=vtt'

            rv = http_requests.get(cap_url, headers=HEADERS_INV, timeout=15)
            if rv.status_code != 200:
                continue

            snippets = _parse_vtt(rv.text)
            if snippets:
                lang_code = chosen.get('language_code', 'he')
                print(f"[Invidious] {base} → {len(snippets)} snippets ({lang_code})")
                return snippets, lang_code

        except Exception as e:
            print(f"[Invidious] {base} error: {e}")
            continue

    return None, None

def extract_video_id(url):
    patterns = [
        r'(?:v=)([a-zA-Z0-9_-]{11})',
        r'(?:youtu\.be/)([a-zA-Z0-9_-]{11})',
        r'(?:embed/)([a-zA-Z0-9_-]{11})',
    ]
    for p in patterns:
        m = re.search(p, url)
        if m:
            return m.group(1)
    if len(url) == 11:
        return url
    return None


def seconds_to_time(s):
    s = int(s)
    h = s // 3600
    m = (s % 3600) // 60
    sec = s % 60
    if h:
        return f"{h}:{m:02d}:{sec:02d}"
    return f"{m}:{sec:02d}"


def group_into_sections(snippets, section_minutes=5):
    """קיבוץ קטעי תמלול לפרקי זמן של X דקות"""
    sections = []
    section_seconds = section_minutes * 60
    current_section = []
    current_start = 0

    for snip in snippets:
        t = snip.start
        if t >= current_start + section_seconds and current_section:
            sections.append({
                'start': current_start,
                'start_fmt': seconds_to_time(current_start),
                'end_fmt': seconds_to_time(t),
                'text': ' '.join(current_section),
            })
            current_section = []
            current_start = t
        current_section.append(snip.text)

    if current_section:
        sections.append({
            'start': current_start,
            'start_fmt': seconds_to_time(current_start),
            'end_fmt': '',
            'text': ' '.join(current_section),
        })

    return sections


@app.route('/')
@login_required
def index():
    u = current_user()
    usage = user_db.month_usage(u['id'])
    upgraded = request.args.get('upgraded') == '1'
    return render_template('index.html', user=u, usage=usage, free_limit=FREE_LIMIT, upgraded=upgraded)


@app.route('/api/transcript', methods=['POST'])
@login_required
def get_transcript():
    u = current_user()
    if u['plan'] == 'free' and user_db.month_usage(u['id']) >= FREE_LIMIT:
        return jsonify({
            'error': f'הגעת למגבלת {FREE_LIMIT} סיכומים חינמיים החודש',
            'upgrade': True,
        }), 403
    data = request.json or {}
    url = data.get('url', '').strip()
    if not url:
        return jsonify({'error': 'נא להזין קישור'}), 400

    vid = extract_video_id(url)
    if not vid:
        return jsonify({'error': 'קישור יוטיוב לא תקין'}), 400

    # ── נסה parse של דף YouTube (עיקרי — עובד מ-cloud) ──────
    snippets, lang = fetch_via_page_parse(vid)

    # ── גיבוי: timedtext API ישיר ────────────────────────────
    if not snippets:
        snippets, lang = fetch_via_timedtext(vid)

    # ── גיבוי: youtube-transcript-api ───────────────────────
    if not snippets and _YT_API_AVAILABLE:
        try:
            api = YouTubeTranscriptApi()
            for _langs in [['iw', 'he'], ['en']]:
                try:
                    transcript = api.fetch(vid, languages=_langs)
                    snippets = list(transcript)
                    if snippets:
                        lang = _langs[0]
                        break
                except Exception:
                    continue
        except Exception as e:
            print(f"[yt-api] {e}")
            snippets = None

    # ── גיבוי: Invidious ─────────────────────────────────────
    if not snippets:
        snippets, lang = fetch_via_invidious(vid)

    # ── גיבוי: yt-dlp ────────────────────────────────────────
    if not snippets:
        snippets, lang = fetch_via_ytdlp(vid)

    if not snippets:
        return jsonify({'error': f'לא ניתן להוריד תמלול — ytdlp={_YTDLP_AVAILABLE}'}), 502

    sections = group_into_sections(snippets, section_minutes=5)
    full_text = ' '.join(s['text'] for s in sections)

    user_db.inc_usage(u['id'])

    return jsonify({
        'video_id': vid,
        'sections': sections,
        'total_sections': len(sections),
        'duration': seconds_to_time(snippets[-1].start) if snippets else '0:00',
        'full_text': full_text,
        'lang': lang,
        'translated': False,
    })


@app.route('/api/translate', methods=['POST'])
@login_required
def translate_sections():
    data = request.json or {}
    sections = data.get('sections', [])
    if not sections:
        return jsonify({'error': 'אין קטעים לתרגום'}), 400

    try:
        translator = GoogleTranslator(source='auto', target='iw')
        for sec in sections:
            chunk = sec['text'][:4500]
            sec['text'] = translator.translate(chunk) or sec['text']
    except Exception as e:
        return jsonify({'error': f'שגיאת תרגום: {str(e)}'}), 502

    full_text = ' '.join(s['text'] for s in sections)
    return jsonify({'sections': sections, 'full_text': full_text})


@app.route('/api/pptx', methods=['POST'])
@login_required
def make_pptx():
    from pptx.util import Emu
    from lxml import etree

    data = request.json or {}
    sections = data.get('sections', [])
    title = data.get('title', 'סיכום פרק')
    if not sections:
        return jsonify({'error': 'אין קטעים'}), 400

    # צבעים
    NAVY    = RGBColor(11, 20, 50)
    NAVY2   = RGBColor(18, 32, 75)
    ACCENT  = RGBColor(0, 180, 216)
    RED     = RGBColor(233, 69, 96)
    WHITE   = RGBColor(255, 255, 255)
    LGRAY   = RGBColor(200, 210, 230)
    GOLD    = RGBColor(255, 193, 7)
    BOX_BG  = RGBColor(25, 40, 90)

    prs = Presentation()
    prs.slide_width  = Inches(13.33)
    prs.slide_height = Inches(7.5)

    def set_bg(slide, color=NAVY):
        fill = slide.background.fill
        fill.solid()
        fill.fore_color.rgb = color

    def add_rect(slide, l, t, w, h, fill_color, line_color=None, line_width=0):
        shape = slide.shapes.add_shape(1, Inches(l), Inches(t), Inches(w), Inches(h))
        shape.fill.solid()
        shape.fill.fore_color.rgb = fill_color
        if line_color:
            shape.line.color.rgb = line_color
            shape.line.width = Pt(line_width)
        else:
            shape.line.fill.background()
        return shape

    def add_tb(slide, text, l, t, w, h, size, bold=False, color=WHITE,
               align=PP_ALIGN.RIGHT, italic=False, font='Calibri'):
        tb = slide.shapes.add_textbox(Inches(l), Inches(t), Inches(w), Inches(h))
        tf = tb.text_frame
        tf.word_wrap = True
        p = tf.paragraphs[0]
        p.alignment = align
        run = p.add_run()
        run.text = text
        run.font.size = Pt(size)
        run.font.bold = bold
        run.font.italic = italic
        run.font.color.rgb = color
        run.font.name = font
        return tb

    def text_to_bullets(text, max_bullets=5):
        sentences = [s.strip() for s in re.split(r'[.!?।]', text) if len(s.strip()) > 15]
        return sentences[:max_bullets]

    # ── שקף כותרת ──
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    set_bg(slide, NAVY)

    # פס עליון צבעוני
    add_rect(slide, 0, 0, 13.33, 0.12, ACCENT)
    # פס תחתון
    add_rect(slide, 0, 7.38, 13.33, 0.12, RED)

    # קו קישוט אנכי שמאלי
    add_rect(slide, 0.3, 1.5, 0.06, 4.5, ACCENT)

    # כותרת
    add_tb(slide, f'"{title}"', 0.6, 1.6, 12.0, 2.0, 38, bold=True,
           color=WHITE, align=PP_ALIGN.CENTER, italic=True)
    add_tb(slide, '— שולחן ארבע —', 0.6, 3.7, 12.0, 0.8, 20,
           color=ACCENT, align=PP_ALIGN.CENTER)

    # מידע
    add_rect(slide, 4.5, 4.7, 4.33, 0.8, BOX_BG)
    add_tb(slide, f'📌  {len(sections)} קטעים', 4.5, 4.75, 4.33, 0.7, 18,
           color=GOLD, align=PP_ALIGN.CENTER, bold=True)

    # ── שקף לכל קטע ──
    for i, sec in enumerate(sections):
        slide = prs.slides.add_slide(prs.slide_layouts[6])
        set_bg(slide, NAVY)

        # פסים עיצוביים
        add_rect(slide, 0, 0, 13.33, 0.10, ACCENT)
        add_rect(slide, 0, 7.40, 13.33, 0.10, RED)
        add_rect(slide, 0, 0.10, 13.33, 1.0, NAVY2)

        # מספר קטע + זמן
        time_range = f"{sec['start_fmt']} – {sec['end_fmt']}" if sec.get('end_fmt') else sec['start_fmt']
        add_rect(slide, 0.3, 0.22, 1.0, 0.55, ACCENT)
        add_tb(slide, f'{i+1}', 0.3, 0.22, 1.0, 0.55, 22, bold=True,
               color=NAVY, align=PP_ALIGN.CENTER)
        add_tb(slide, f'⏱  {time_range}', 1.5, 0.25, 5.0, 0.5, 14,
               color=LGRAY, align=PP_ALIGN.RIGHT)

        # תצוגת תוכן כ-bullets
        bullets = text_to_bullets(sec['text'], max_bullets=5)
        if not bullets:
            bullets = [sec['text'][:200]]

        bullet_icons = ['🔹', '🔸', '💡', '📌', '▶']
        box_h = 1.0
        for j, bullet in enumerate(bullets):
            y = 1.3 + j * box_h
            add_rect(slide, 0.3, y, 12.73, 0.85, BOX_BG, line_color=ACCENT, line_width=0.5)
            text_short = bullet[:140] + ('...' if len(bullet) > 140 else '')
            add_tb(slide, f'{bullet_icons[j % 5]}  {text_short}',
                   0.45, y + 0.05, 12.43, 0.75, 15,
                   color=WHITE, align=PP_ALIGN.RIGHT)

    buf = io.BytesIO()
    prs.save(buf)
    buf.seek(0)
    safe_title = re.sub(r'[^\w\s-]', '', title)[:40].strip() or 'presentation'
    return send_file(buf, as_attachment=True,
                     download_name=f'{safe_title}.pptx',
                     mimetype='application/vnd.openxmlformats-officedocument.presentationml.presentation')


def _build_smart_pptx_bytes(full_text, title):
    """יוצר PPTX ומחזיר bytes + שם קובץ בטוח"""
    from pptx.util import Emu
    import json as _json

    api_key = os.getenv('ANTHROPIC_API_KEY')
    if not api_key:
        raise ValueError('חסר API key')

    client = anthropic.Anthropic(api_key=api_key)
    prompt = f"""קרא את התמלול הבא וזהה את הנושאים המרכזיים שנדונו.
לכל נושא תן:
1. כותרת קצרה (עד 8 מילים)
2. 3-4 נקודות עיקריות (כל אחת עד 20 מילים)

החזר בפורמט JSON בלבד, ללא הסברים נוספים:
{{
  "topics": [
    {{
      "title": "כותרת הנושא",
      "points": ["נקודה 1", "נקודה 2", "נקודה 3"]
    }}
  ]
}}

זהה עד 8 נושאים מרכזיים.

התמלול:
{full_text[:12000]}"""

    msg = client.messages.create(
        model='claude-haiku-4-5-20251001',
        max_tokens=2000,
        messages=[{'role': 'user', 'content': prompt}]
    )
    raw = msg.content[0].text.strip()
    json_match = re.search(r'\{.*\}', raw, re.DOTALL)
    if not json_match:
        raise ValueError('לא נמצא JSON')
    topics_data = _json.loads(json_match.group())['topics']

    BG      = RGBColor(2,  8, 18)
    BG2     = RGBColor(4, 14, 32)
    CYAN    = RGBColor(0, 255, 255)
    CYAN2   = RGBColor(0, 180, 220)
    CYAN3   = RGBColor(0,  45,  60)
    GREEN   = RGBColor(0, 255, 120)
    WHITE   = RGBColor(220, 240, 255)
    DIM     = RGBColor(80, 140, 160)
    NEONS   = [
        RGBColor(0,255,255), RGBColor(255,0,200), RGBColor(0,255,120),
        RGBColor(255,220,0), RGBColor(100,180,255), RGBColor(255,100,100),
        RGBColor(180,255,100), RGBColor(200,100,255)
    ]

    prs = Presentation()
    prs.slide_width  = Inches(13.33)
    prs.slide_height = Inches(7.5)

    def set_bg(slide):
        fill = slide.background.fill
        fill.solid()
        fill.fore_color.rgb = BG

    def add_rect(slide, l, t, w, h, fc, lc=None, lw=0):
        s = slide.shapes.add_shape(1, Inches(l), Inches(t), Inches(w), Inches(h))
        s.fill.solid()
        s.fill.fore_color.rgb = fc
        if lc:
            s.line.color.rgb = lc
            s.line.width = Pt(lw)
        else:
            s.line.fill.background()
        return s

    def add_tb(slide, text, l, t, w, h, size, bold=False, color=WHITE,
               align=PP_ALIGN.RIGHT, italic=False, font='Consolas'):
        tb = slide.shapes.add_textbox(Inches(l), Inches(t), Inches(w), Inches(h))
        tf = tb.text_frame
        tf.word_wrap = True
        p = tf.paragraphs[0]
        p.alignment = align
        run = p.add_run()
        run.text = text
        run.font.size = Pt(size)
        run.font.bold = bold
        run.font.italic = italic
        run.font.color.rgb = color
        run.font.name = font
        return tb

    def draw_grid(slide, step=0.7):
        x = 0.0
        while x <= 13.33:
            add_rect(slide, x, 0, 0.01, 7.5, CYAN3)
            x += step
        y = 0.0
        while y <= 7.5:
            add_rect(slide, 0, y, 13.33, 0.01, CYAN3)
            y += step

    def draw_corners(slide, color, sz=0.45, th=0.045):
        m = 0.2
        for lx, ly, dx, dy in [
            (m, m, 1, 1), (13.33-m-sz, m, -1, 1),
            (m, 7.5-m-th, 1, -1), (13.33-m-sz, 7.5-m-th, -1, -1)
        ]:
            add_rect(slide, lx, ly if dy==1 else ly, sz, th, color)
            add_rect(slide, lx if dx==1 else lx+sz-th, m if dy==1 else 7.5-m-sz, th, sz, color)

    def glow_box(slide, l, t, w, h, color):
        c1 = RGBColor(color[0]//5, color[1]//5, color[2]//5)
        c2 = RGBColor(color[0]//2, color[1]//2, color[2]//2)
        add_rect(slide, l-0.05, t-0.05, w+0.10, h+0.10, BG, lc=c1, lw=3)
        add_rect(slide, l-0.025, t-0.025, w+0.05, h+0.05, BG, lc=c2, lw=2)
        add_rect(slide, l, t, w, h, BG2, lc=color, lw=1.5)

    slide = prs.slides.add_slide(prs.slide_layouts[6])
    set_bg(slide)
    draw_grid(slide)
    draw_corners(slide, CYAN)
    add_rect(slide, 0, 3.55, 13.33, 0.025, CYAN)
    add_tb(slide, 'BRIEFING  //  CLASSIFIED', 0.5, 0.45, 12.33, 0.55, 11,
           color=DIM, align=PP_ALIGN.CENTER)
    add_tb(slide, f'// {title} //', 0.5, 1.15, 12.33, 2.3, 30,
           bold=True, color=CYAN, align=PP_ALIGN.CENTER)
    add_tb(slide, '━' * 52, 0.5, 3.25, 12.33, 0.4, 10,
           color=CYAN2, align=PP_ALIGN.CENTER)
    add_tb(slide, f'[ שולחן ארבע ]   TOPICS: {len(topics_data):02d}   STATUS: ACTIVE',
           0.5, 3.7, 12.33, 0.6, 14, color=GREEN, align=PP_ALIGN.CENTER)
    add_rect(slide, 0, 6.82, 13.33, 0.02, CYAN2)
    add_tb(slide, 'SYSTEM ONLINE  ◈  AUDIO PROCESSED  ◈  READY',
           0.5, 6.86, 12.33, 0.45, 10, color=DIM, align=PP_ALIGN.CENTER)

    for i, topic in enumerate(topics_data):
        neon = NEONS[i % len(NEONS)]
        slide = prs.slides.add_slide(prs.slide_layouts[6])
        set_bg(slide)
        draw_grid(slide, step=0.85)
        draw_corners(slide, neon)
        add_rect(slide, 0, 1.25, 13.33, 0.02, neon)
        add_rect(slide, 0, 0, 13.33, 1.22, BG2)
        add_rect(slide, 0, 0, 0.07, 1.22, neon)
        glow_box(slide, 0.2, 0.2, 0.78, 0.78, neon)
        add_tb(slide, f'{i+1:02d}', 0.2, 0.22, 0.78, 0.72, 26,
               bold=True, color=neon, align=PP_ALIGN.CENTER)
        add_tb(slide, f'SEGMENT_{i+1:02d}.DAT', 0.12, 0.06, 5.0, 0.35, 8,
               color=DIM, align=PP_ALIGN.LEFT)
        add_tb(slide, f'◈  {topic["title"]}', 1.1, 0.24, 12.0, 0.75, 22,
               bold=True, color=WHITE, align=PP_ALIGN.RIGHT, font='Calibri')

        points = topic.get('points', [])
        n = max(len(points), 1)
        box_h = min(1.18, (7.5 - 1.42) / n)
        for j, point in enumerate(points):
            y = 1.35 + j * box_h
            glow_box(slide, 0.22, y, 12.89, box_h - 0.12, neon)
            add_rect(slide, 0.22, y, 0.06, box_h - 0.12, neon)
            add_tb(slide, f'{j+1:02d}', 0.3, y+0.06, 0.55, box_h-0.2, 11,
                   color=neon, align=PP_ALIGN.CENTER)
            tc = WHITE if j % 2 == 0 else RGBColor(
                min(255, neon[0]+60), min(255, neon[1]+60), min(255, neon[2]+60))
            add_tb(slide, point, 0.95, y+0.07, 12.0, box_h-0.2, 15,
                   color=tc, align=PP_ALIGN.RIGHT, font='Calibri')

    buf = io.BytesIO()
    prs.save(buf)
    buf.seek(0)
    safe = re.sub(r'[^\w\s-]', '', title)[:40].strip() or 'summary'
    return buf.getvalue(), safe


@app.route('/api/smart_pptx', methods=['POST'])
@login_required
@pro_required
def smart_pptx():
    data = request.json or {}
    full_text = data.get('full_text', '').strip()
    title = data.get('title', 'סיכום פרק')
    if not full_text:
        return jsonify({'error': 'אין תמלול'}), 400
    try:
        pptx_bytes, safe = _build_smart_pptx_bytes(full_text, title)
    except Exception as e:
        return jsonify({'error': str(e)}), 502
    return send_file(io.BytesIO(pptx_bytes), as_attachment=True,
                     download_name=f'{safe}_topics.pptx',
                     mimetype='application/vnd.openxmlformats-officedocument.presentationml.presentation')


@app.route('/api/smart_pptx_base64', methods=['POST'])
@login_required
@pro_required
def smart_pptx_base64():
    import base64
    data = request.json or {}
    full_text = data.get('full_text', '').strip()
    title = data.get('title', 'סיכום פרק')
    if not full_text:
        return jsonify({'error': 'אין תמלול'}), 400
    try:
        pptx_bytes, safe = _build_smart_pptx_bytes(full_text, title)
    except Exception as e:
        return jsonify({'error': str(e)}), 502
    return jsonify({
        'filename': f'{safe}_topics.pptx',
        'base64': base64.b64encode(pptx_bytes).decode('utf-8')
    })


@app.route('/api/js_pptx', methods=['POST'])
@login_required
@pro_required
def js_pptx():
    data = request.json or {}
    full_text = data.get('full_text', '').strip()
    title = data.get('title', 'סיכום פרק')

    if not full_text:
        return jsonify({'error': 'אין תמלול'}), 400

    api_key = os.getenv('ANTHROPIC_API_KEY')
    if not api_key:
        return jsonify({'error': 'חסר API key'}), 500

    client = anthropic.Anthropic(api_key=api_key)
    prompt = f"""קרא את התמלול וזהה עד 8 נושאים מרכזיים.
לכל נושא תן כותרת קצרה (עד 8 מילים) ו-4 נקודות (כל אחת משפט אחד עד 25 מילים).
החזר JSON בלבד:
{{"topics":[{{"title":"...","points":["...","...","...","..."]}}]}}

התמלול:
{full_text[:12000]}"""

    try:
        msg = client.messages.create(
            model='claude-haiku-4-5-20251001',
            max_tokens=2000,
            messages=[{'role': 'user', 'content': prompt}]
        )
        raw = msg.content[0].text.strip()
        m = re.search(r'\{.*\}', raw, re.DOTALL)
        topics_data = json.loads(m.group())['topics']
    except Exception as e:
        return jsonify({'error': f'שגיאת Claude: {str(e)}'}), 502

    # כתוב JSON זמני
    gen_dir = os.path.join(os.path.dirname(__file__), 'pptx_gen')
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False,
                                     encoding='utf-8', dir=gen_dir) as f:
        json.dump({'title': title, 'topics': topics_data}, f, ensure_ascii=False)
        tmp_json = f.name

    tmp_pptx = tmp_json.replace('.json', '.pptx')

    try:
        result = subprocess.run(
            ['node', 'generate.js', tmp_json, tmp_pptx],
            cwd=gen_dir, capture_output=True, text=True, timeout=60
        )
        if result.returncode != 0 or not os.path.exists(tmp_pptx):
            return jsonify({'error': result.stderr or 'שגיאה ב-Node.js'}), 502

        with open(tmp_pptx, 'rb') as f:
            pptx_bytes = f.read()
    finally:
        for p in [tmp_json, tmp_pptx]:
            try: os.remove(p)
            except: pass

    safe = re.sub(r'[^\w\s-]', '', title)[:40].strip() or 'briefing'
    return send_file(
        io.BytesIO(pptx_bytes),
        as_attachment=True,
        download_name=f'{safe}.pptx',
        mimetype='application/vnd.openxmlformats-officedocument.presentationml.presentation'
    )




@app.route('/api/summary', methods=['POST'])
@login_required
@pro_required
def ai_summary():
    data = request.json or {}
    full_text = data.get('full_text', '').strip()
    if not full_text:
        return jsonify({'error': 'אין תמלול'}), 400

    api_key = os.getenv('ANTHROPIC_API_KEY')
    if not api_key:
        return jsonify({'error': 'חסר API key'}), 500

    client = anthropic.Anthropic(api_key=api_key)
    prompt = f"""קרא את התמלול הבא וכתוב סיכום קצר ומסודר בעברית.
הסיכום צריך להיות:
- 5-8 נקודות עיקריות
- כל נקודה משפט אחד ברור
- מה הנושא הכללי של הפרק
- מה המסקנות או הרעיונות החשובים

החזר בפורמט הזה בלבד:
**נושא הפרק:** [נושא קצר]

**נקודות עיקריות:**
• [נקודה 1]
• [נקודה 2]
• [נקודה 3]
...

**מסקנה:** [משפט סיכום אחד]

התמלול:
{full_text[:15000]}"""

    try:
        msg = client.messages.create(
            model='claude-haiku-4-5-20251001',
            max_tokens=1000,
            messages=[{'role': 'user', 'content': prompt}]
        )
        return jsonify({'summary': msg.content[0].text.strip()})
    except Exception as e:
        return jsonify({'error': str(e)}), 502


@app.route('/api/opportunities', methods=['POST'])
@login_required
@pro_required
def business_opportunities():
    data = request.json or {}
    full_text = data.get('full_text', '').strip()
    if not full_text:
        return jsonify({'error': 'אין תמלול'}), 400

    api_key = os.getenv('ANTHROPIC_API_KEY')
    if not api_key:
        return jsonify({'error': 'חסר API key'}), 500

    client = anthropic.Anthropic(api_key=api_key)
    prompt = f"""קרא את התמלול הבא וזהה הזדמנויות עסקיות.
לכל הזדמנות ציין:
1. שם ההזדמנות
2. תיאור קצר
3. קהל יעד
4. איך לממש אותה
5. פוטנציאל הכנסה משוער

החזר בפורמט הזה:

🚀 הזדמנות 1: [שם]
📌 תיאור: [תיאור קצר]
👥 קהל יעד: [מי יקנה]
⚙️ מימוש: [איך עושים את זה]
💰 פוטנציאל: [הערכת הכנסה]

---

זהה 3-5 הזדמנויות עסקיות מהתוכן.
התמלול:
{full_text[:15000]}"""

    try:
        msg = client.messages.create(
            model='claude-haiku-4-5-20251001',
            max_tokens=1500,
            messages=[{'role': 'user', 'content': prompt}]
        )
        return jsonify({'opportunities': msg.content[0].text.strip()})
    except Exception as e:
        return jsonify({'error': str(e)}), 502


@app.route('/api/upload_cookies', methods=['POST'])
@login_required
def upload_cookies():
    """העלאת קובץ cookies של YouTube — מאפשר גישה מהשרת הענן"""
    if 'file' not in request.files:
        return jsonify({'error': 'לא נבחר קובץ'}), 400
    f = request.files['file']
    if not f.filename.endswith('.txt'):
        return jsonify({'error': 'הקובץ חייב להיות .txt'}), 400
    f.save(COOKIES_FILE)
    return jsonify({'success': True, 'message': 'Cookies הועלו בהצלחה!'})


@app.route('/api/send_email', methods=['POST'])
@login_required
@pro_required
def send_email():
    """שלח סיכום למייל דרך Resend"""
    data = request.json or {}
    to_email = data.get('email', '').strip()
    summary  = data.get('summary', '').strip()
    title    = data.get('title', 'סיכום פרק').strip()

    if not to_email or not summary:
        return jsonify({'error': 'חסר מייל או סיכום'}), 400

    if not RESEND_KEY:
        return jsonify({'error': 'מפתח Resend לא מוגדר'}), 500

    # המר סיכום ל-HTML פשוט
    html_lines = []
    for line in summary.split('\n'):
        line = line.strip()
        if not line:
            html_lines.append('<br>')
        elif line.startswith('**') and line.endswith('**'):
            html_lines.append(f'<h3 style="color:#1a1a2e">{line[2:-2]}</h3>')
        elif line.startswith('•'):
            html_lines.append(f'<li style="margin:6px 0">{line[1:].strip()}</li>')
        else:
            html_lines.append(f'<p>{line}</p>')

    html_body = f"""
    <div dir="rtl" style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto;padding:24px">
      <div style="background:linear-gradient(135deg,#1a0533,#2d1060);padding:20px;border-radius:10px;margin-bottom:20px">
        <h1 style="color:#fff;margin:0;font-size:1.4rem">שולחן ארבע</h1>
        <p style="color:#a78bfa;margin:4px 0 0">סיכום אוטומטי</p>
      </div>
      <h2 style="color:#1a0533">{title}</h2>
      {''.join(html_lines)}
      <hr style="border:none;border-top:1px solid #eee;margin:24px 0">
      <p style="color:#999;font-size:0.75rem">נוצר על ידי שולחן ארבע · AI Summary</p>
    </div>"""

    try:
        resp = http_requests.post(
            'https://api.resend.com/emails',
            headers={
                'Authorization': f'Bearer {RESEND_KEY}',
                'Content-Type': 'application/json'
            },
            json={
                'from': 'שולחן ארבע <onboarding@resend.dev>',
                'to': [to_email],
                'subject': f'סיכום: {title}',
                'html': html_body
            },
            timeout=15
        )
        if resp.status_code == 200:
            return jsonify({'success': True})
        return jsonify({'error': resp.text}), resp.status_code
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.errorhandler(500)
def server_error(e):
    return jsonify({'error': f'Server error: {str(e)}'}), 500


@app.errorhandler(Exception)
def unhandled(e):
    import traceback
    print(traceback.format_exc())
    return jsonify({'error': str(e)}), 500


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5002))
    print(f"SikumAI -> http://localhost:{port}")
    app.run(debug=False, host='0.0.0.0', port=port)
