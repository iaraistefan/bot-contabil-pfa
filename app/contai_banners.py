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
    if value is None:                           # gardă: câmp lipsă → 0, nu crăpa bannerul
        value = 0
    txt = f"{value:,.2f}"                       # 2,813.17
    return txt.replace(",", "§").replace(".", ",").replace("§", ".")

def _zile_label(days):
    """Zile rămase → etichetă lizibilă (days_left int CU SEMN, neschimbat la mapare):
    >0 → 'ÎN N ZILE', 0 → 'AZI', <0 → 'DEPĂȘIT DE N ZILE'."""
    if days is None:
        return ""
    if days > 0:
        return f"ÎN {days} ZILE"
    if days == 0:
        return "AZI"
    return f"DEPĂȘIT DE {abs(days)} ZILE"

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
        bdg = f"SCADENT {_zile_label(days)}"
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


def _cat_row(d, x, y, w, name, amount, frac, deduct_label, accent):
    h = s(58)
    _rrect(d, [x, y, x + w, y + h], 12, fill=CARD, outline=CARD_LINE, width=1)
    d.text((x + s(20), y + s(9)), name, font=font(POP_L, 17), fill=WHITE)
    # bara proportie
    bar_x0 = x + s(20)
    bar_w = w * 0.42
    by = y + s(40)
    _rrect(d, [bar_x0, by, bar_x0 + bar_w, by + s(7)], 3, fill=(30, 50, 76))
    _rrect(d, [bar_x0, by, bar_x0 + max(s(7), int(bar_w * frac)), by + s(7)], 3, fill=accent)
    # suma dreapta
    amt = fmt_ron(amount)
    aw = d.textlength(amt, font=font(POP_B, 20))
    d.text((x + w - s(20) - aw, y + s(9)), amt, font=font(POP_B, 20), fill=WHITE)
    # tag deductibilitate
    f = font(MONO_R, 11)
    tagw = _tw(d, deduct_label, f, 1)
    _tracked(d, (x + w - s(20) - tagw, y + s(38)), deduct_label, f, MUTED, 1)

def _obl_row(d, x, y, w, title, sub, right_top, right_bottom, accent, warn=False):
    h = s(74)
    _rrect(d, [x, y, x + w, y + h], 14, fill=CARD, outline=CARD_LINE, width=1)
    _rrect(d, [x, y, x + s(6), y + h], 3, fill=accent)
    d.text((x + s(26), y + s(13)), title, font=font(POP_B, 19), fill=WHITE)
    _tracked(d, (x + s(26), y + s(44)), sub.upper(), font(MONO_R, 11), MUTED, 1)
    # dreapta: sus (data/sumă) + jos (zile)
    rt_f = font(POP_B, 18)
    rtw = d.textlength(right_top, font=rt_f)
    d.text((x + w - s(24) - rtw, y + s(13)), right_top, font=rt_f, fill=(AMBER if warn else WHITE))
    if right_bottom:
        rb_f = font(MONO_R, 11)
        rbw = _tw(d, right_bottom, rb_f, 1)
        _tracked(d, (x + w - s(24) - rbw, y + s(46)), right_bottom, rb_f,
                 (AMBER if warn else MUTED), 1)


# ============================================================
#  ECRAN — CHELTUIELI
# ============================================================
def render_cheltuieli(data):
    img, d = _canvas()
    _header(d, "CHELTUIELI")
    d.text((s(56), s(110)), data.get("period", ""), font=font(POP_B, 30), fill=WHITE)
    _tracked(d, (s(58), s(156)), data.get("subtitle", "").upper(), font(MONO_R, 13), MUTED, 1)

    top, gap = s(196), s(20)
    cw = (W * SCALE - s(112) - gap) / 2
    ch = s(120)
    _kpi(d, s(56), top, cw, ch, "TOTAL CHELTUIELI", fmt_ron(data["total"]), "lei", AMBER)
    _kpi(d, s(56) + cw + gap, top, cw, ch, "DIN CARE DEDUCTIBIL", fmt_ron(data["deductibil"]), "lei", GREEN)

    total = max(data["total"], 0.01)
    cy = top + ch + s(28)
    for cat in data.get("categories", [])[:3]:
        _cat_row(d, s(56), cy, W * SCALE - s(112), cat["name"], cat["amount"],
                 cat["amount"] / total, cat.get("deduct", ""), TEAL)
        cy += s(70)

    _footer(d, data.get("cui", "PFA · CUI 53067338 · Bistrița"), data.get("status", "la zi"))
    return _to_image(img)


# ============================================================
#  ECRAN — FOAIE DE PARCURS
# ============================================================
def render_foaie_parcurs(data):
    img, d = _canvas()
    _header(d, "FOAIE DE PARCURS")
    d.text((s(56), s(110)), data.get("period", ""), font=font(POP_B, 30), fill=WHITE)
    _tracked(d, (s(58), s(156)), data.get("subtitle", "").upper(), font(MONO_R, 13), MUTED, 1)

    top, gap = s(196), s(20)
    cw = (W * SCALE - s(112) - gap * 2) / 3
    ch = s(150)
    _kpi(d, s(56), top, cw, ch, "KM BUSINESS", str(data["km_total"]), "km", TEAL)
    _kpi(d, s(56) + cw + gap, top, cw, ch, "CU PASAGER", str(data["km_pasager"]), "km", GREEN)
    _kpi(d, s(56) + (cw + gap) * 2, top, cw, ch, "POZIȚIONARE", str(data["km_pozitionare"]), "km", AMBER)

    # rand vehicul + consum
    ry = top + ch + s(30)
    w = W * SCALE - s(112)
    _rrect(d, [s(56), ry, s(56) + w, ry + s(110)], 14, fill=CARD, outline=CARD_LINE, width=1)
    _tracked(d, (s(56) + s(24), ry + s(18)), "VEHICUL", font(MONO_B, 12), MUTED, 2)
    d.text((s(56) + s(24), ry + s(38)), data.get("vehicul", ""), font=font(POP_B, 20), fill=WHITE)
    _tracked(d, (s(56) + s(24), ry + s(74)),
             f"NORMĂ {data.get('norma','')} · CONSUM TEORETIC {data.get('consum_teoretic','')}",
             font(MONO_R, 12), MUTED, 1)
    # status combustibil dreapta
    # `depasit` lipsă (None) ⇒ NU afișa pill (niciun verdict DEPĂȘIT/ÎN NORMĂ).
    # Verdictul fiscal (mai_poti_lei) e suspectat fals-pozitiv → se repară separat
    # în combustibil.py; până atunci bannerul nu face nicio afirmație de plafon.
    warn = data.get("depasit")
    if warn is not None:
        lbl = "DEPĂȘIT" if warn else "ÎN NORMĂ"
        col = RED if warn else GREEN
        f = font(MONO_B, 12)
        _pill(d, s(56) + w - s(24) - (_tw(d, lbl, f, 2) + s(28)), ry + s(30),
              lbl, f, col, (18, 30, 44) if warn else (16, 40, 36), tracking=2)
    bon = f"{data.get('combustibil_bonuri','')}"
    bw = d.textlength(bon, font=font(POP_B, 18))
    d.text((s(56) + w - s(24) - bw, ry + s(70)), bon, font=font(POP_B, 18), fill=WHITE)

    _footer(d, data.get("cui", "PFA · CUI 53067338 · Bistrița"), data.get("status", "la zi"))
    return _to_image(img)


# ============================================================
#  ECRAN — CALENDAR FISCAL
# ============================================================
def render_calendar(data):
    img, d = _canvas()
    _header(d, "CALENDAR FISCAL")
    d.text((s(56), s(110)), data.get("title", ""), font=font(POP_B, 28), fill=WHITE)
    _tracked(d, (s(58), s(154)), data.get("subtitle", "").upper(), font(MONO_R, 12), MUTED, 1)
    x, w, y = s(56), W * SCALE - s(112), s(190)
    for i, o in enumerate(data.get("obligations", [])[:4]):
        _obl_row(d, x, y + i * s(90), w, o["code"], o["name"],
                 o["date"], _zile_label(o["days_left"]), AMBER if o.get("warn") else TEAL,
                 warn=o.get("warn", False))
    _footer(d, data.get("cui", "PFA · CUI 53067338 · Bistrița"), data.get("status", "la zi"))
    return _to_image(img)


# ============================================================
#  ECRAN — PLĂȚI
# ============================================================
def render_plati(data):
    img, d = _canvas()
    _header(d, "PLĂȚI")
    d.text((s(56), s(110)), data.get("title", "De plată"), font=font(POP_B, 28), fill=WHITE)
    _tracked(d, (s(58), s(154)), "PRIN GHIȘEUL.RO · PE CNP", font(MONO_R, 12), MUTED, 1)
    x, w, y = s(56), W * SCALE - s(112), s(196)
    for i, it in enumerate(data.get("items", [])[:4]):
        _obl_row(d, x, y + i * s(90), w, it["name"], it.get("sub", "vezi SPV"),
                 fmt_ron(it["amount"]) + " lei", it.get("due", ""),
                 AMBER, warn=True)
    _footer(d, data.get("cui", "PFA · CUI 53067338 · Bistrița"), data.get("status", "scadent"),
            AMBER)
    return _to_image(img)


# ============================================================
#  ECRAN — REGISTRU
# ============================================================
def render_registru(data):
    img, d = _canvas()
    _header(d, "REGISTRU")
    d.text((s(56), s(110)), data.get("period", ""), font=font(POP_B, 30), fill=WHITE)
    _tracked(d, (s(58), s(156)), "ÎNCASĂRI ȘI PLĂȚI · OMFP 170/2015", font(MONO_R, 12), MUTED, 1)
    top, gap = s(200), s(20)
    cw = (W * SCALE - s(112) - gap * 2) / 3
    ch = s(150)
    sold = data["sold"]
    _kpi(d, s(56), top, cw, ch, "TOTAL ÎNCASĂRI", fmt_ron(data["incasari"]), "lei", GREEN)
    _kpi(d, s(56) + cw + gap, top, cw, ch, "TOTAL PLĂȚI", fmt_ron(data["plati"]), "lei", AMBER)
    _kpi(d, s(56) + (cw + gap) * 2, top, cw, ch, "SOLD FINAL", fmt_ron(sold), "lei",
         GREEN if sold >= 0 else RED)
    # ultima inregistrare
    if data.get("last"):
        ly = top + ch + s(34)
        _tracked(d, (s(58), ly), "ULTIMA ÎNREGISTRARE", font(MONO_B, 12), MUTED, 2)
        d.text((s(56), ly + s(24)), data["last"], font=font(POP_L, 18), fill=WHITE)
    _footer(d, data.get("cui", "PFA · CUI 53067338 · Bistrița"), data.get("status", "la zi"))
    return _to_image(img)


# ============================================================
#  ECRAN — RAPORT LUNAR (estimare fiscală live)
# ============================================================
def render_raport(data):
    img, d = _canvas()
    _header(d, "RAPORT LUNAR")
    box = [s(56), s(116), W * SCALE - s(56), s(500)]
    _rrect(d, box, 22, fill=CARD, outline=CARD_LINE, width=1)
    _rrect(d, [box[0], box[1], box[0] + s(6), box[3]], 3, fill=TEAL)
    px = box[0] + s(44)

    _tracked(d, (px, box[1] + s(34)), "PROFIT NET · " + data.get("period", "").upper(),
             font(MONO_B, 13), TEAL_SOFT, 2)
    big = font(POP_B, 80)
    val = fmt_ron(data.get("profit", 0))
    d.text((px - s(4), box[1] + s(66)), val, font=big, fill=WHITE)
    bw = d.textlength(val, font=big)
    d.text((px + bw + s(14), box[1] + s(100)), "RON", font=font(POP_L, 28), fill=MUTED)

    # venituri / cheltuieli mini (optionale)
    sy = box[1] + s(168)
    if data.get("venituri") is not None:
        d.ellipse([px, sy + s(4), px + s(11), sy + s(15)], fill=GREEN)
        d.text((px + s(24), sy - s(4)), f"Venituri  {fmt_ron(data['venituri'])} lei",
               font=font(POP_L, 17), fill=WHITE)
    if data.get("cheltuieli") is not None:
        d.ellipse([px + s(360), sy + s(4), px + s(371), sy + s(15)], fill=AMBER)
        d.text((px + s(384), sy - s(4)), f"Cheltuieli  {fmt_ron(data['cheltuieli'])} lei",
               font=font(POP_L, 17), fill=WHITE)

    d.line([(px, box[1] + s(212)), (box[2] - s(44), box[1] + s(212))], fill=CARD_LINE, width=SCALE)

    # estimare fiscala live
    _tracked(d, (px, box[1] + s(232)), data.get("taxe_label", "ESTIMARE TAXE D212 (LA ZI)"),
             font(MONO_B, 12), AMBER, 2)
    ty = box[1] + s(266)
    cells = [("IMPOZIT", data.get("impozit", 0)), ("CAS", data.get("cas", 0)),
             ("CASS", data.get("cass", 0)), ("TOTAL", data.get("total_taxe", 0))]
    cellw = (box[2] - s(44) - px) / 4
    for i, (lbl, v) in enumerate(cells):
        cx = px + i * cellw
        _tracked(d, (cx, ty), lbl, font(MONO_R, 11), MUTED, 1)
        col = AMBER if lbl == "TOTAL" else WHITE
        d.text((cx, ty + s(20)), fmt_ron(v), font=font(POP_B, 26), fill=col)

    _footer(d, data.get("cui", "PFA · CUI 53067338 · Bistrița"),
            data.get("status", "estimare la zi"), TEAL)
    return _to_image(img)


# ============================================================
#  API public
# ============================================================
_RENDERERS = {
    "prezentare": render_prezentare,
    "venituri": render_venituri,
    "declaratii": render_declaratii,
    "cheltuieli": render_cheltuieli,
    "foaie_parcurs": render_foaie_parcurs,
    "calendar": render_calendar,
    "plati": render_plati,
    "registru": render_registru,
    "raport": render_raport,
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
