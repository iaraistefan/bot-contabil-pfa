#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
contai_banners.py — generator de bannere premium pentru interfața Telegram Contai.

Fiecare ecran are o funcție `render_*(data)` care întoarce un obiect PIL.Image.
`build_banner(screen, data)` întoarce un BytesIO PNG gata pentru bot.send_photo.

IDENTITATE: navy + teal + auriu (tema 0, aprobată).
FONTURI: Poppins (titluri/cifre) + Geist Mono (etichete). Se caută în:
  - $CONTAI_FONTS_DIR
  - <dir modul>/assets/fonts
  - <dir modul>/fonts
  - fonturi sistem (fallback DejaVu) dacă lipsesc.

Dependență: Pillow  (pip install Pillow)

Exemplu de folosire în bot (python-telegram-bot):

    from contai_banners import build_banner
    png = build_banner("prezentare", {
        "amount": 2813.17, "decl": "D212 · Declarația Unică (impozit + CAS + CASS)",
        "due_label": "Termen: 25 Mai 2027", "due_sub": "Plata se face pe CNP, prin ghișeul.ro",
        "days_left": 349, "secondary": "D207 — fără plată",
        "secondary_sub": "TERMEN 28 FEB 2027",
        "cui": "PFA · CUI 53067338 · Bistrița", "status": "la zi",
    })
    await update.message.reply_photo(photo=png, reply_markup=keyboard, caption="📊 Prezentare")
"""
import os
import io
from PIL import Image, ImageDraw, ImageFont

# ============================================================
#  TEMA CONTAI (navy + teal + auriu)
# ============================================================
NAVY_TOP   = (10, 24, 44)
NAVY_BOT   = (15, 33, 56)
CARD       = (19, 38, 63)
CARD_LINE  = (38, 62, 92)
TEAL       = (45, 212, 191)
TEAL_SOFT  = (130, 224, 211)
AMBER      = (245, 185, 69)
WHITE      = (244, 248, 252)
MUTED      = (126, 147, 171)
MUTED_DIM  = (92, 112, 138)
GREEN      = (74, 210, 150)
RED        = (240, 110, 110)

SCALE = 2
W, H = 1080, 675

# ------------------------------------------------------------
#  Fonturi (cu fallback)
# ------------------------------------------------------------
_HERE = os.path.dirname(os.path.abspath(__file__))
_FONT_DIRS = [
    os.environ.get("CONTAI_FONTS_DIR", ""),
    os.path.join(_HERE, "assets", "fonts"),
    os.path.join(_HERE, "fonts"),
    "/usr/share/fonts/truetype/google-fonts",
    "/usr/share/fonts/truetype/dejavu",
]
_FALLBACK = {
    "Poppins-Bold.ttf": "DejaVuSans-Bold.ttf",
    "Poppins-Light.ttf": "DejaVuSans.ttf",
    "GeistMono-Bold.ttf": "DejaVuSansMono-Bold.ttf",
    "GeistMono-Regular.ttf": "DejaVuSansMono.ttf",
}
_cache = {}

def _find(name):
    for d in _FONT_DIRS:
        if d and os.path.exists(os.path.join(d, name)):
            return os.path.join(d, name)
    fb = _FALLBACK.get(name)
    if fb:
        for d in _FONT_DIRS:
            if d and os.path.exists(os.path.join(d, fb)):
                return os.path.join(d, fb)
    return None

def font(name, size):
    key = (name, size)
    if key in _cache:
        return _cache[key]
    path = _find(name)
    f = ImageFont.truetype(path, size * SCALE) if path else ImageFont.load_default()
    _cache[key] = f
    return f

POP_B, POP_L = "Poppins-Bold.ttf", "Poppins-Light.ttf"
MONO_B, MONO_R = "GeistMono-Bold.ttf", "GeistMono-Regular.ttf"

# ------------------------------------------------------------
#  Primitive de desen
# ------------------------------------------------------------
def s(v):
    return int(v * SCALE)

def fmt_ron(value):
    """2813.17 -> '2.813,17' (format RO)."""
    txt = f"{value:,.2f}"                       # 2,813.17
    return txt.replace(",", "§").replace(".", ",").replace("§", ".")

def _canvas():
    img = Image.new("RGB", (W * SCALE, H * SCALE), NAVY_TOP)
    d = ImageDraw.Draw(img)
    for y in range(H * SCALE):
        t = y / (H * SCALE)
        d.line([(0, y), (W * SCALE, y)],
               fill=tuple(int(NAVY_TOP[i] + (NAVY_BOT[i] - NAVY_TOP[i]) * t) for i in range(3)))
    glow = Image.new("RGBA", (W * SCALE, H * SCALE), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    cx, cy = int(W * SCALE * 0.86), int(H * SCALE * 0.14)
    for rad in range(s(420), 0, -s(6)):
        a = int(16 * (1 - rad / s(420)))
        gd.ellipse([cx - rad, cy - rad, cx + rad, cy + rad], fill=(45, 212, 191, a))
    img = Image.alpha_composite(img.convert("RGBA"), glow).convert("RGB")
    return img, ImageDraw.Draw(img)

def _tracked(d, xy, text, fnt, fill, tracking=0):
    tr = tracking * SCALE
    x, y = xy
    for ch in text:
        d.text((x, y), ch, font=fnt, fill=fill)
        x += d.textlength(ch, font=fnt) + tr
    return x

def _tw(d, text, fnt, tracking=0):
    return sum(d.textlength(c, font=fnt) + tracking * SCALE for c in text) - tracking * SCALE

def _rrect(d, box, radius, fill=None, outline=None, width=1):
    d.rounded_rectangle(box, radius=radius * SCALE, fill=fill, outline=outline, width=width * SCALE)

def _pill(d, x, y, text, fnt, fg, bg, padx=14, pady=7, tracking=2):
    tw = _tw(d, text, fnt, tracking)
    w = tw + padx * 2 * SCALE
    h = fnt.size + pady * 2 * SCALE
    _rrect(d, [x, y, x + w, y + h], radius=h / SCALE / 2, fill=bg)
    _tracked(d, (x + padx * SCALE, y + pady * SCALE - s(1)), text, fnt, fg, tracking)
    return w

def _header(d, section):
    d.ellipse([s(56), s(50), s(74), s(68)], fill=TEAL)
    d.text((s(86), s(44)), "Contai", font=font(POP_B, 22), fill=WHITE)
    f = font(MONO_B, 13)
    _pill(d, W * SCALE - s(56) - (_tw(d, section, f, 2) + s(28)), s(48),
          section, f, TEAL, (16, 46, 64), tracking=2)

def _footer(d, cui="PFA · CUI 53067338 · Bistrița", status="la zi", color=TEAL):
    y = H * SCALE - s(58)
    _tracked(d, (s(56), y), cui.upper(), font(MONO_R, 12), MUTED, tracking=1)
    f = font(MONO_B, 12)
    label = status.upper()
    dx = W * SCALE - s(56) - _tw(d, label, f, 1) - s(20)
    d.ellipse([dx, y + s(3), dx + s(10), y + s(13)], fill=color)
    _tracked(d, (dx + s(20), y), label, f, color, tracking=1)

def _to_image(img):
    return img.resize((W, H), Image.LANCZOS)

def _kpi(d, x, y, w, h, label, value, unit, accent):
    _rrect(d, [x, y, x + w, y + h], 16, fill=CARD, outline=CARD_LINE, width=1)
    _rrect(d, [x + s(20), y + s(20), x + s(48), y + s(24)], 2, fill=accent)
    _tracked(d, (x + s(20), y + s(36)), label, font(MONO_B, 12), MUTED, tracking=2)
    d.text((x + s(18), y + s(58)), value, font=font(POP_B, 38), fill=WHITE)
    vw = d.textlength(value, font=font(POP_B, 38))
    if unit:
        d.text((x + s(18) + vw + s(8), y + s(78)), unit, font=font(POP_L, 16), fill=MUTED)

def _decl_row(d, x, y, w, code, name, status, accent):
    h = s(74)
    _rrect(d, [x, y, x + w, y + h], 14, fill=CARD, outline=CARD_LINE, width=1)
    _rrect(d, [x, y, x + s(6), y + h], 3, fill=accent)
    d.text((x + s(28), y + s(14)), code, font=font(POP_B, 22), fill=WHITE)
    _tracked(d, (x + s(28), y + s(46)), name.upper(), font(MONO_R, 11), MUTED, tracking=1)
    f = font(MONO_B, 11)
    _pill(d, x + w - s(24) - (_tw(d, status, f, 2) + s(24)), y + s(22),
          status, f, accent, (16, 40, 56), padx=12, pady=6, tracking=2)


# ============================================================
#  ECRANE
# ============================================================
def render_prezentare(data):
    img, d = _canvas()
    _header(d, "PREZENTARE")
    box = [s(56), s(120), W * SCALE - s(56), s(496)]
    _rrect(d, box, 22, fill=CARD, outline=CARD_LINE, width=1)
    _rrect(d, [box[0], box[1], box[0] + s(6), box[3]], 3, fill=AMBER)
    px = box[0] + s(44)

    _tracked(d, (px, box[1] + s(36)), "CÂT PLĂTESC ȘI CÂND?", font(MONO_B, 14), TEAL_SOFT, 3)
    days = data.get("days_left")
    if days is not None:
        bdg = f"SCADENT ÎN {days} ZILE"
        f = font(MONO_B, 12)
        _pill(d, box[2] - s(34) - (_tw(d, bdg, f, 2) + s(28)), box[1] + s(30),
              bdg, f, (26, 20, 8), AMBER, tracking=2)

    big = font(POP_B, 88)
    amt = fmt_ron(data["amount"])
    d.text((px - s(4), box[1] + s(72)), amt, font=big, fill=WHITE)
    bw = d.textlength(amt, font=big)
    d.text((px + bw + s(14), box[1] + s(112)), "RON", font=font(POP_L, 30), fill=MUTED)

    _tracked(d, (px, box[1] + s(184)), data.get("decl", "").upper(), font(MONO_R, 13), MUTED, 1)
    d.line([(px, box[1] + s(222)), (box[2] - s(44), box[1] + s(222))], fill=CARD_LINE, width=SCALE)

    ly = box[1] + s(250)
    d.ellipse([px, ly + s(5), px + s(11), ly + s(16)], fill=AMBER)
    d.text((px + s(26), ly - s(4)), data.get("due_label", ""), font=font(POP_B, 20), fill=WHITE)
    d.text((px + s(26), ly + s(28)), data.get("due_sub", ""), font=font(POP_L, 16), fill=MUTED)

    if data.get("secondary"):
        ly2 = box[1] + s(322)
        d.ellipse([px, ly2 + s(5), px + s(11), ly2 + s(16)], fill=MUTED_DIM)
        d.text((px + s(26), ly2 - s(2)), data["secondary"], font=font(POP_L, 18), fill=MUTED)
        if data.get("secondary_sub"):
            offx = px + s(26) + d.textlength(data["secondary"] + "  ", font=font(POP_L, 18))
            _tracked(d, (offx, ly2 + s(2)), data["secondary_sub"], font(MONO_R, 12), MUTED_DIM, 1)

    _footer(d, data.get("cui", "PFA · CUI 53067338 · Bistrița"), data.get("status", "la zi"))
    return _to_image(img)


def render_venituri(data):
    img, d = _canvas()
    _header(d, "VENITURI BOLT")
    d.text((s(56), s(110)), data.get("period", ""), font=font(POP_B, 30), fill=WHITE)
    _tracked(d, (s(58), s(156)), data.get("subtitle", "").upper(), font(MONO_R, 13), MUTED, 1)

    top, gap = s(196), s(20)
    cw = (W * SCALE - s(112) - gap * 2) / 3
    ch = s(150)
    _kpi(d, s(56), top, cw, ch, "ÎNCASĂRI BRUT", fmt_ron(data["brut"]), "lei", TEAL)
    _kpi(d, s(56) + cw + gap, top, cw, ch, "COMISION BOLT", fmt_ron(data["comision"]), "lei", AMBER)
    _kpi(d, s(56) + (cw + gap) * 2, top, cw, ch, "VENIT NET", fmt_ron(data["net"]), "lei", GREEN)

    by = top + ch + s(40)
    _tracked(d, (s(58), by), "STRUCTURA ÎNCASĂRILOR", font(MONO_B, 12), MUTED, 2)
    bar_y, bar_h = by + s(30), s(26)
    bx0, bx1 = s(56), W * SCALE - s(56)
    full = bx1 - bx0
    brut = max(data["brut"], 0.01)
    alte = max(brut - data["net"] - data["comision"], 0)
    segs = [("Net", data["net"], GREEN), ("Comision", data["comision"], AMBER),
            ("Alte costuri", alte, MUTED_DIM)]
    gap2, x = s(6), bx0
    for i, (lbl, val, col) in enumerate(segs):
        seg_w = int(full * (val / brut)) - (gap2 if i < len(segs) - 1 else 0)
        if seg_w > 0:
            _rrect(d, [x, bar_y, x + seg_w, bar_y + bar_h], 7, fill=col)
            x += seg_w + gap2
    leg_y, lx = bar_y + bar_h + s(28), bx0
    for lbl, val, col in segs:
        d.ellipse([lx, leg_y + s(3), lx + s(12), leg_y + s(15)], fill=col)
        d.text((lx + s(22), leg_y - s(3)), lbl, font=font(POP_L, 16), fill=WHITE)
        _tracked(d, (lx + s(22), leg_y + s(22)), fmt_ron(val) + " LEI", font(MONO_R, 12), MUTED, 1)
        lx += d.textlength(lbl, font=font(POP_L, 16)) + s(150)

    _footer(d, data.get("cui", "PFA · CUI 53067338 · Bistrița"),
            data.get("status", "sincronizat Bolt"))
    return _to_image(img)


def render_declaratii(data):
    img, d = _canvas()
    _header(d, "TVA & DECLARAȚII")
    d.text((s(56), s(110)), data.get("title", "De depus"), font=font(POP_B, 28), fill=WHITE)
    _tracked(d, (s(58), s(154)), data.get("subtitle", "").upper(), font(MONO_R, 12), MUTED, 1)
    x, w, y = s(56), W * SCALE - s(112), s(190)
    for i, row in enumerate(data.get("rows", [])):
        accent = AMBER if row.get("warn") else TEAL
        _decl_row(d, x, y + i * s(90), w, row["code"], row["name"],
                  row.get("status", "DE DEPUS"), accent)
    _footer(d, data.get("cui", "PFA · CUI 53067338 · Bistrița"),
            data.get("status", "generează în SPV"), TEAL_SOFT)
    return _to_image(img)


# ============================================================
#  API public
# ============================================================
_RENDERERS = {
    "prezentare": render_prezentare,
    "venituri": render_venituri,
    "declaratii": render_declaratii,
}

def build_banner(screen, data):
    """Întoarce un BytesIO PNG gata pentru bot.send_photo / reply_photo."""
    if screen not in _RENDERERS:
        raise ValueError(f"Ecran necunoscut: {screen}. Disponibile: {list(_RENDERERS)}")
    img = _RENDERERS[screen](data)
    buf = io.BytesIO()
    img.save(buf, "PNG", optimize=True)
    buf.seek(0)
    buf.name = f"contai_{screen}.png"
    return buf


if __name__ == "__main__":
    # DEMO — generează cele 3 ecrane cu date de test
    demos = {
        "prezentare": {
            "amount": 2813.17, "decl": "D212 · Declarația Unică (impozit + CAS + CASS)",
            "due_label": "Termen: 25 Mai 2027", "due_sub": "Plata se face pe CNP, prin ghișeul.ro",
            "days_left": 349, "secondary": "D207 — fără plată", "secondary_sub": "TERMEN 28 FEB 2027",
        },
        "venituri": {
            "period": "Iunie 2026", "subtitle": "9 curse · 602,6 km cu pasager",
            "brut": 2869.60, "comision": 712.65, "net": 1703.08,
        },
        "declaratii": {
            "title": "De depus — Iunie 2026",
            "subtitle": "Taxare inversă pe comisionul Bolt (EE) · termen 25",
            "rows": [
                {"code": "D301", "name": "Decont special TVA"},
                {"code": "D390", "name": "Declarație recapitulativă VIES"},
                {"code": "D100", "name": "Impozit nerezident · 2%", "warn": True},
            ],
        },
    }
    for scr, dat in demos.items():
        png = build_banner(scr, dat)
        with open(f"/home/claude/contai_banners/prod_{scr}.png", "wb") as fp:
            fp.write(png.read())
        print("OK", scr)
