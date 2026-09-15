"""Small procedural textures for the headquarters scene: monitor interfaces, window views, art.

  python art-source/blender/hq/make_textures.py

Deterministic (seeded) and local: no service, no generated imagery. What a screen shows live is
drawn by the web canvas from backend state; these are the idle pictures baked into the plates.
"""

import math
import os
import random

from PIL import Image, ImageDraw, ImageFilter

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "textures")


def hexrgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i : i + 2], 16) for i in (0, 2, 4))


def mix(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def ui(name, accent, seed, kind, bg="#07101f", w=256, h=160):
    rng = random.Random(seed)
    acc = hexrgb(accent)
    base = hexrgb(bg)
    im = Image.new("RGB", (w, h), base)
    d = ImageDraw.Draw(im)
    d.rectangle([0, 0, w, 14], fill=mix(base, acc, 0.35))
    for i in range(3):
        d.ellipse([6 + i * 10, 4, 12 + i * 10, 10], fill=mix(base, acc, 0.8))
    d.rectangle([0, 14, 46, h], fill=mix(base, acc, 0.12))
    for r in range(7):
        d.rectangle([6, 24 + r * 16, 40, 30 + r * 16], fill=mix(base, acc, 0.45 if r == 1 else 0.25))
    x0 = 54
    if kind == "text":
        y = 24
        while y < h - 8:
            ln = rng.randint(60, w - x0 - 10)
            d.rectangle([x0, y, x0 + ln, y + 4], fill=mix(base, acc, rng.uniform(0.45, 0.95)))
            y += rng.choice((9, 9, 12, 18))
    elif kind == "chart":
        pts = []
        for i in range(12):
            pts.append((x0 + i * (w - x0 - 12) / 11, h - 30 - rng.uniform(10, 90)))
        d.line(pts, fill=acc, width=3)
        for i in range(10):
            bh = rng.uniform(8, 40)
            d.rectangle([x0 + i * 18, h - 8 - bh, x0 + i * 18 + 10, h - 8], fill=mix(base, acc, 0.6))
    elif kind == "daw":
        for t in range(5):
            yc = 30 + t * 26
            d.rectangle([x0, yc - 10, w - 8, yc + 10], fill=mix(base, acc, 0.1))
            for x in range(x0, w - 8, 2):
                amp = abs(math.sin(x * 0.07 + t) * math.sin(x * 0.013 * (t + 1))) * 9 + rng.uniform(0, 2)
                d.line([x, yc - amp, x, yc + amp], fill=mix(base, acc, 0.75))
    elif kind == "timeline":
        colors = ["#60a5fa", "#f59e0b", "#34d399", "#f472b6", "#a78bfa"]
        d.rectangle([x0, 20, w - 8, 80], fill=mix(base, (40, 60, 90), 0.8))
        d.rectangle([x0 + 20, 26, w - 30, 74], fill=(25, 35, 55))
        for t in range(4):
            x = x0
            while x < w - 10:
                ln = rng.randint(18, 60)
                d.rectangle([x, 90 + t * 17, min(x + ln, w - 8), 102 + t * 17], fill=hexrgb(rng.choice(colors)))
                x += ln + rng.randint(2, 8)
        px = x0 + int((w - x0) * 0.62)
        d.line([px, 84, px, h], fill=(255, 80, 80), width=2)
    elif kind == "radar":
        cx, cy, r = (x0 + w) // 2, h // 2 + 6, 62
        for k in range(1, 5):
            d.ellipse([cx - r * k / 4, cy - r * k / 4, cx + r * k / 4, cy + r * k / 4], outline=mix(base, acc, 0.5))
        d.line([cx - r, cy, cx + r, cy], fill=mix(base, acc, 0.35))
        d.line([cx, cy - r, cx, cy + r], fill=mix(base, acc, 0.35))
        d.pieslice([cx - r, cy - r, cx + r, cy + r], -40, 0, fill=mix(base, acc, 0.45))
        for i in range(9):
            a = rng.uniform(0, math.tau)
            rr = rng.uniform(10, r - 4)
            d.ellipse([cx + math.cos(a) * rr - 2, cy + math.sin(a) * rr - 2, cx + math.cos(a) * rr + 2, cy + math.sin(a) * rr + 2], fill=acc)
    elif kind == "ledger":
        for r in range(12):
            y = 22 + r * 11
            d.rectangle([x0, y, w - 8, y + 9], fill=mix(base, acc, 0.14 if r % 2 else 0.06))
            d.rectangle([x0 + 4, y + 3, x0 + 70, y + 6], fill=mix(base, acc, 0.6))
            d.rectangle([w - 60, y + 3, w - 14, y + 6], fill=mix(base, acc, 0.9))
    im = im.filter(ImageFilter.GaussianBlur(0.4))
    im.save(os.path.join(OUT, f"{name}.png"))


def window_view(name, seed, w=256, h=256):
    rng = random.Random(seed)
    im = Image.new("RGB", (w, h))
    d = ImageDraw.Draw(im)
    stops = [(0.0, "#16204a"), (0.35, "#34407a"), (0.62, "#8a6282"), (0.8, "#d98e70")]
    for y in range(h):
        t = y / h
        for i in range(len(stops) - 1):
            if stops[i][0] <= t <= stops[i + 1][0] or (i == len(stops) - 2 and t > stops[-1][0]):
                a, b = stops[i], stops[i + 1]
                k = min(1.0, (t - a[0]) / (b[0] - a[0]))
                d.line([0, y, w, y], fill=mix(hexrgb(a[1]), hexrgb(b[1]), k))
                break
    x = -10
    while x < w:
        bw = rng.randint(18, 46)
        top = rng.randint(int(h * 0.35), int(h * 0.78))
        col = mix(hexrgb("#0d1226"), hexrgb("#2a2c48"), rng.uniform(0, 0.5))
        d.rectangle([x, top, x + bw, h], fill=col)
        for wy in range(top + 6, h, 9):
            for wx in range(x + 4, x + bw - 3, 7):
                if rng.random() < 0.3:
                    d.rectangle([wx, wy, wx + 2, wy + 3], fill=hexrgb(rng.choice(["#ffc26b", "#ffe0a0", "#9cc4ff"])))
        x += bw + rng.randint(-6, 4)
    im.filter(ImageFilter.GaussianBlur(0.6)).save(os.path.join(OUT, f"{name}.png"))


def window_view_day(name, seed, w=256, h=256):
    rng = random.Random(seed)
    im = Image.new("RGB", (w, h))
    d = ImageDraw.Draw(im)
    for y in range(h):
        d.line([0, y, w, y], fill=mix(hexrgb("#4f86cf"), hexrgb("#d6e6f4"), min(1.0, y / (h * 0.7))))
    x = -10
    while x < w:
        bw = rng.randint(18, 46)
        top = rng.randint(int(h * 0.35), int(h * 0.78))
        d.rectangle([x, top, x + bw, h], fill=mix(hexrgb("#7d8ca3"), hexrgb("#a9b6c8"), rng.uniform(0, 1)))
        for wy in range(top + 6, h, 9):
            for wx in range(x + 4, x + bw - 3, 7):
                d.rectangle([wx, wy, wx + 2, wy + 3], fill=hexrgb(rng.choice(["#5b6f8c", "#8fa4c2", "#c9d8ea"])))
        x += bw + rng.randint(-6, 4)
    im.filter(ImageFilter.GaussianBlur(0.6)).save(os.path.join(OUT, f"{name}.png"))


def art(name, seed, palette, w=128, h=160):
    rng = random.Random(seed)
    im = Image.new("RGB", (w, h), hexrgb(palette[0]))
    d = ImageDraw.Draw(im)
    for y in range(h):
        d.line([0, y, w, y], fill=mix(hexrgb(palette[0]), hexrgb(palette[1]), y / h))
    for i in range(6):
        c = hexrgb(rng.choice(palette[1:]))
        r = rng.randint(10, 40)
        cx, cy = rng.randint(0, w), rng.randint(0, h)
        d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=c)
    im.filter(ImageFilter.GaussianBlur(3)).save(os.path.join(OUT, f"{name}.png"))


def snapshot(name, seed, sky, glow, w=96, h=80):
    """A pinned photograph: a dark evening skyline with a lit horizon, the way the reference's
    pinboard reads. `art()`'s blurred pastel blobs came out brighter than the cork they hang on and
    flattened the wall; a photo is dark with one bright band, so each frame reads as a picture."""
    rng = random.Random(seed)
    im = Image.new("RGB", (w, h), hexrgb(sky[0]))
    d = ImageDraw.Draw(im)
    horizon = int(h * rng.uniform(0.55, 0.7))
    for y in range(horizon):
        d.line([0, y, w, y], fill=mix(hexrgb(sky[0]), hexrgb(sky[1]), (y / horizon) ** 1.6))
    # the foreground carries the horizon's light down the picture, so the photo reads as a lit
    # photograph on the board and not as a dark square
    for y in range(horizon, h):
        t = (y - horizon) / max(1, h - horizon)
        d.line([0, y, w, y], fill=mix(mix(hexrgb(sky[1]), hexrgb(sky[2]), 0.45), hexrgb(sky[2]), t))
    # the skyline against the lit sky, and the windows that catch the last light
    x = 0
    while x < w:
        bw = rng.randint(6, 16)
        bh = rng.randint(6, 26)
        d.rectangle([x, horizon - bh, x + bw, horizon], fill=mix(hexrgb(sky[2]), hexrgb(sky[0]), 0.4))
        for _ in range(rng.randint(0, 3)):
            wx = x + rng.randint(1, max(1, bw - 3))
            wy = horizon - bh + rng.randint(1, max(1, bh - 3))
            d.rectangle([wx, wy, wx + 1, wy + 1], fill=hexrgb(glow))
        x += bw + rng.randint(1, 3)
    d.line([0, horizon, w, horizon], fill=hexrgb(glow))
    im = im.filter(ImageFilter.GaussianBlur(0.6))
    im.save(os.path.join(OUT, f"{name}.png"))


FONT_BOLD = "C:/Windows/Fonts/segoeuib.ttf"
FONT_SIGN = "C:/Windows/Fonts/bahnschrift.ttf"


def mark(d, x, y, h, colour):
    """The AMN-AI 'A' mark: two slanted strokes and pixel blocks."""
    w = h * 1.05
    t = h * 0.22
    d.polygon([(x, y + h), (x + t, y + h), (x + w / 2 + t * 0.2, y + t * 0.9), (x + w / 2 - t * 0.35, y)], fill=colour)
    d.polygon([(x + w - t, y + h), (x + w, y + h), (x + w / 2 + t * 0.35, y), (x + w / 2 - t * 0.2, y + t * 0.9)], fill=colour)
    d.rectangle([x + w * 0.6, y + h * 0.84, x + w * 0.72, y + h], fill=colour)


def banner(name, bg_top, bg_bottom, title, subtitle, accent, w=960, h=96, with_mark=False, title_colour="#ffffff"):
    from PIL import ImageFont

    im = Image.new("RGB", (w, h))
    d = ImageDraw.Draw(im)
    for y in range(h):
        d.line([0, y, w, y], fill=mix(hexrgb(bg_top), hexrgb(bg_bottom), y / h))
    x = 28
    if with_mark:
        mark(d, x, 18, 60, hexrgb(accent))
        x += 88
    big = ImageFont.truetype(FONT_BOLD, 44)
    small = ImageFont.truetype(FONT_SIGN, 20)
    d.text((x, 10), title, font=big, fill=hexrgb(title_colour))
    d.text((x + 2, 62), subtitle, font=small, fill=hexrgb(accent))
    d.rectangle([0, h - 6, w, h], fill=hexrgb(accent))
    im.save(os.path.join(OUT, f"{name}.png"))


def main():
    os.makedirs(OUT, exist_ok=True)
    banner("ad_amn_ai", "#0b1430", "#162550", "AMN-AI", "AUTONOMOUS MACHINE NEXUS  ·  IDEAS BUILD A BRIGHTER TOMORROW", "#2dd4bf", with_mark=True)
    banner("ad_nexus_curiosity", "#1d0f3a", "#3b1d6e", "NEXUS CURIOSITY", "SCIENCE STORIES  ·  ON YOUTUBE", "#f0abfc")
    banner("ad_inside_the_nexus", "#07161a", "#0f3a3f", "INSIDE THE NEXUS", "HOW IT IS MADE  ·  ON YOUTUBE", "#5eead4")
    banner("ad_city", "#e5e7eb", "#d1d5db", "CITY LINE 12", "CENTRU  ·  AI DISTRICT  ·  NORD", "#2563eb", title_colour="#1f2937")
    banner("ad_delivery", "#f4f4f5", "#e4e4e7", "SWIFTBOX", "PARCEL DELIVERY", "#ea580c", title_colour="#18181b")
    banner("ad_logistics", "#1e293b", "#334155", "NORTHLINE", "LOGISTICS", "#fbbf24")
    ui("ui_blue", "#5b8cff", 1, "text")
    ui("ui_blue_chart", "#6aa0ff", 2, "chart")
    ui("ui_cyan", "#4fd1e8", 3, "text")
    ui("ui_cyan_chart", "#4fd1e8", 4, "chart")
    ui("ui_daw", "#c084fc", 5, "daw", bg="#120a22")
    ui("ui_waveform", "#5eead4", 6, "daw", bg="#061614")
    ui("ui_timeline", "#60a5fa", 7, "timeline")
    ui("ui_radar", "#4ade80", 8, "radar", bg="#04140a")
    ui("ui_ledger", "#a3e635", 9, "ledger", bg="#0a1206")
    ui("ui_script", "#ffd28a", 10, "text", bg="#140f08")
    window_view("window_city", 11)
    window_view("window_city_b", 12)
    window_view_day("window_city_day", 13)
    art("art_warm", 13, ["#3a2418", "#d89a58", "#f2c27a", "#8a4a2a"])
    art("art_night", 14, ["#0c1020", "#3a4a78", "#8aa0d0", "#e0d0b0"])
    art("art_teal", 15, ["#0a1a1c", "#2a6a6a", "#8ad0c0", "#f0e0c0"])
    for i, (sky, glow) in enumerate(((["#0a1024", "#c07038", "#160f18"], "#ffcf8a"),
                                     (["#08101e", "#4a7ab0", "#0d1620"], "#cfe4ff"),
                                     (["#140a18", "#a85070", "#1a1016"], "#ffb0c0"),
                                     (["#08140f", "#3f8f70", "#0c1712"], "#b9f0d0"))):
        snapshot(f"photo_{i}", 20 + i, sky, glow)
    print("textures written to", OUT)


main()
