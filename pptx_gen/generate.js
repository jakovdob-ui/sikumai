const PptxGenJS = require('pptxgenjs');
const fs = require('fs');

const inputFile = process.argv[2];
const outputFile = process.argv[3];
if (!inputFile || !outputFile) { console.error('Usage: node generate.js input.json output.pptx'); process.exit(1); }

const { title, topics } = JSON.parse(fs.readFileSync(inputFile, 'utf8'));

// ── תמה ──
function detectTheme(topics) {
  const text = topics.map(t => t.title + ' ' + (t.points||[]).join(' ')).join(' ').toLowerCase();
  const tech  = ['ai','טכנולוגיה','tech','software','סייבר','דיגיטל','startup'].filter(w=>text.includes(w)).length;
  const econ  = ['כלכלה','גאופוליטיקה','מסחר','נפט','דולר','ביטחון','מדיניות'].filter(w=>text.includes(w)).length;
  if (tech >= econ) return 'tech';
  if (econ > 0) return 'geo';
  return 'deep';
}

const THEMES = {
  geo:  { a1:'00B4D8', a2:'F4A261', a3:'C1440E', bg:'0D1B2A', hdr:'0A1C2A', card:'142535' },
  tech: { a1:'2563EB', a2:'F97316', a3:'06B6D4', bg:'0A0F1E', hdr:'081525', card:'0F1E35' },
  deep: { a1:'7C3AED', a2:'D4A843', a3:'A855F7', bg:'0D0A1E', hdr:'100A20', card:'1A1030' },
};
const T = THEMES[detectTheme(topics)];
const OFF = 'D8E4ED';
const FONT = 'Arial';
const W = 13.33, H = 7.5;

const pptx = new PptxGenJS();
pptx.layout = 'LAYOUT_WIDE';

function bg(slide) { slide.background = { color: T.bg }; }

function rect(slide, x, y, w, h, fill, opts={}) {
  slide.addShape(pptx.ShapeType.rect, {
    x, y, w, h,
    fill: { color: fill },
    line: opts.line || { type: 'none' },
    shadow: opts.shadow,
  });
}

function rrect(slide, x, y, w, h, fill, opts={}) {
  slide.addShape(pptx.ShapeType.roundRect, {
    x, y, w, h, rectRadius: opts.r || 0.08,
    fill: { color: fill },
    line: opts.border ? { color: opts.border, width: opts.lw||0.8 } : { type:'none' },
    shadow: opts.shadow || { type:'outer', color:'000000', blur:8, offset:3, angle:135, opacity:0.18 },
  });
}

function txt(slide, text, x, y, w, h, size, opts={}) {
  slide.addText(text, {
    x, y, w, h,
    fontSize: size,
    bold: opts.bold||false,
    italic: opts.italic||false,
    color: opts.color||OFF,
    fontFace: FONT,
    align: opts.align||'right',
    rtlMode: true,
    valign: opts.valign||'middle',
    wrap: true,
    lineSpacingMultiple: opts.ls||1.2,
  });
}

function card(slide, x, y, w, h, ctitle, body, accent) {
  rrect(slide, x, y, w, h, T.card, { border: accent, lw: 0.8 });
  rect(slide, x + w - 0.08, y, 0.08, h, accent);
  txt(slide, ctitle, x+0.05, y+0.07, w-0.18, 0.35, 12, { bold:true, color:accent, valign:'top' });
  txt(slide, body,   x+0.05, y+0.45, w-0.18, h-0.52, 11, { valign:'top' });
}

// ─── שקופית פתיחה ───
const s0 = pptx.addSlide();
bg(s0);
rect(s0, 0, 0,    W, 0.07, T.a1);
rect(s0, 0, H-0.07, W, 0.07, T.a2);
txt(s0, title, 0.4, 0.3, W-0.8, 1.2, 40, { bold:true, color:'FFFFFF', valign:'top' });
txt(s0, 'שולחן ארבע  ·  סיכום פרק', 0.4, 1.55, W-0.8, 0.45, 15, { color:T.a2 });
rect(s0, 0.4, 2.05, W-0.8, 0.03, T.a1);

const topN = topics.slice(0,5);
rrect(s0, 0.4, 2.2, W-0.8, topN.length*0.62+0.3, T.card);
topN.forEach((t,i)=>{
  txt(s0, `▸  ${t.title}`, 0.55, 2.3+i*0.62, W-1.1, 0.55, 14, { color:OFF });
});
txt(s0, `${topics.length} נושאים מרכזיים`, 0.4, H-0.55, W-0.8, 0.35, 11, { color:T.a3, align:'right' });

// ─── שקופיות תוכן ───
const ACCS = [T.a1, T.a2, T.a3, T.a1, T.a2, T.a3, T.a1, T.a2];

topics.forEach((topic, idx) => {
  const slide = pptx.addSlide();
  bg(slide);
  const acc = ACCS[idx % ACCS.length];
  const layout = idx % 3;

  // header
  rect(slide, 0, 0, W, 1.15, T.hdr);
  rect(slide, 0, 0, W, 0.06, acc);
  rect(slide, 0, 0, 0.07, 1.15, acc);
  rrect(slide, 0.18, 0.2, 0.72, 0.72, acc, { r:0.06 });
  txt(slide, `${idx+1}`, 0.18, 0.2, 0.72, 0.72, 22, { bold:true, color:'000000', align:'center' });
  txt(slide, topic.title, 1.05, 0.22, W-1.25, 0.72, 22, { bold:true, color:'FFFFFF' });
  rect(slide, 0, H-0.06, W, 0.06, acc);

  const pts = (topic.points||[]).slice(0,4);

  if (layout === 0) {
    // Grid 2×2
    const pos = [[0.2,1.25],[6.8,1.25],[0.2,4.1],[6.8,4.1]];
    pts.forEach((pt,j) => {
      const [px,py] = pos[j]||[0.2,1.25];
      const [h,...rest] = pt.split(/[.,،]/);
      card(slide, px, py, 6.2, 2.7, h.trim(), rest.join(' ').trim()||pt, acc);
    });

  } else if (layout === 1) {
    // עמודות
    const cw = (W-0.4)/Math.max(pts.length,1);
    pts.forEach((pt,j) => {
      const [h,...rest] = pt.split(/[.,،]/);
      card(slide, 0.2+j*cw, 1.25, cw-0.15, H-1.55, h.trim(), rest.join(' ').trim()||pt, acc);
    });

  } else {
    // Stats + רשימה
    const sw = (W-0.4)/Math.max(pts.length,1);
    pts.forEach((pt,j) => {
      rrect(slide, 0.2+j*sw, 1.22, sw-0.12, 1.3, T.card, { border: acc });
      txt(slide, `0${j+1}`, 0.2+j*sw, 1.28, sw-0.12, 0.65, 28, { bold:true, color:acc, align:'center' });
      txt(slide, pt.slice(0,28), 0.2+j*sw, 1.9, sw-0.12, 0.52, 10, { align:'center' });
    });
    pts.forEach((pt,j) => {
      const y = 2.65+j*1.12;
      rrect(slide, 0.2, y, W-0.4, 1.0, T.card, { border: acc, lw:0.6 });
      rect(slide, W-0.28, y, 0.08, 1.0, acc);
      txt(slide, pt, 0.3, y+0.08, W-0.7, 0.82, 13, { valign:'middle' });
    });
  }
});

// ─── שקופית סיום ───
const sf = pptx.addSlide();
bg(sf);

// blob ovals
[[0.5,4.8,4.5,2.5],[8.0,0.4,5.0,3.0],[3.0,2.2,3.2,2.0],[10.0,4.2,3.2,2.5]].forEach(([x,y,w,h],i)=>{
  const cols=[T.a1,T.a2,T.a3,T.a1];
  sf.addShape(pptx.ShapeType.ellipse, {
    x, y, w, h,
    fill: { color: cols[i], transparency: 85 },
    line: { color: cols[i], transparency: 70, width: 0.5 },
  });
});

rect(sf, 0, 0, W, 0.06, T.a1);
txt(sf, `" ${topics[0]?.title||title} "`, 0.8, 0.35, W-1.6, 1.05, 24,
  { italic:true, color:T.a2, align:'center' });
rect(sf, 2.5, 1.5, 8.5, 0.03, T.a1);

rrect(sf, 1.5, 1.72, W-3.0, topics.slice(0,5).length*0.68+0.3, T.card);
topics.slice(0,5).forEach((t,i)=>{
  txt(sf, `◈  ${t.title}`, 1.65, 1.85+i*0.68, W-3.3, 0.6, 13, { color:OFF });
});

txt(sf, 'שולחן ארבע  ·  END OF BRIEFING', 0.4, H-0.5, W-0.8, 0.35,
  12, { italic:true, color:T.a3, align:'center' });
rect(sf, 0, H-0.06, W, 0.06, T.a1);

// ─── שמור ───
pptx.writeFile({ fileName: outputFile })
  .then(()=>{ console.log('OK'); process.exit(0); })
  .catch(e=>{ console.error('ERR:'+e.message); process.exit(1); });
