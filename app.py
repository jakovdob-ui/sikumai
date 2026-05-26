import re
import io
import os
import json
import tempfile
import subprocess
import anthropic
from dotenv import load_dotenv
from flask import Flask, render_template, request, jsonify, send_file
from youtube_transcript_api import YouTubeTranscriptApi
from deep_translator import GoogleTranslator
from pptx import Presentation
from pptx.util import Inches, Pt
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN

load_dotenv(os.path.join(os.path.dirname(__file__), '.env'))

app = Flask(__name__)


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
def index():
    return render_template('index.html')


@app.route('/api/transcript', methods=['POST'])
def get_transcript():
    data = request.json or {}
    url = data.get('url', '').strip()
    if not url:
        return jsonify({'error': 'נא להזין קישור'}), 400

    vid = extract_video_id(url)
    if not vid:
        return jsonify({'error': 'קישור יוטיוב לא תקין'}), 400

    try:
        api = YouTubeTranscriptApi()
        lang = 'iw'
        try:
            transcript = api.fetch(vid, languages=['iw', 'he'])
        except Exception:
            try:
                transcript = api.fetch(vid, languages=['en'])
                lang = 'en'
            except Exception:
                transcript = api.fetch(vid)
                lang = 'other'
        snippets = list(transcript)
    except Exception as e:
        return jsonify({'error': f'לא ניתן להוריד תמלול: {str(e)}'}), 502

    sections = group_into_sections(snippets, section_minutes=5)
    full_text = ' '.join(s['text'] for s in sections)

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


if __name__ == '__main__':
    print("SikumAI - סיכום פרקים -> http://localhost:5002")
    app.run(debug=False, host='0.0.0.0', port=5002)
