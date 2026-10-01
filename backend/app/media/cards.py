"""Cards: the scenes the studio draws itself, from verified numbers, for 0 credits.

A bar chart, a title and a black screen are not photographs, and a photographic model asked
for one returns a photograph anyway. On the Nepal film scene 5 asked the image model for "two
vertical bars side by side: the first fills to the top, the second stops noticeably short" (100
vs 83 billion dollars) and got a woman beside two abstract bars; scene 6 asked for "a black
screen, silent and still" and got a woman in a landscape. Both were paid for, both failed
quality control. This module composes those scenes locally with ffmpeg alone:

- ``DATA_CARD``: bars that grow with an ease-out, one after the other, and stop at their true
  ratio; each value is written above its bar exactly as the card spec states it (and the spec's
  values come from SUPPORTED factual claims, which the story gate checks - not this module).
- ``TITLE_CARD``: a title and an optional subtitle.
- ``BLACK``: pure black (Y = 16, limited range) with an optional call to action.

Every glyph is drawn with the bundled Inter (OFL), verified against a pinned SHA-256 before a
single frame is made; a missing or altered font raises, it never falls back to whatever the
system has. Every pixel that is not background lies inside ``SAFE_RECT``, clear of the platform's
own buttons and captions. Hex colours are used here and only here: the prompts sent to a model
never carry them.

Nothing here imports a provider: a card has provenance ``composed`` and costs 0 credits.
"""

from __future__ import annotations

import hashlib
import math
import re
import shutil
import struct
import subprocess
import tempfile
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.media.toolchain import find_ffmpeg

# --------------------------------------------------------------------------- constants

FRAME_WIDTH = 1080
FRAME_HEIGHT = 1920

#: (x0, y0, x1, y1), exclusive of x1/y1. Everything a card draws lies inside this rectangle:
#: 90 px from each side, clear of the top bar above y 300 and of the platform's caption and
#: button zone below y 1540.
SAFE_RECT: tuple[int, int, int, int] = (90, 300, 990, 1540)

#: Card content ends above this row: the narration's burnt captions (two lines of Inter Bold
#: 66 px, bottom at y 1500, outline included) occupy the band below it. The Nepal rehearsal
#: of 2026-10-01 showed captions written over the chart's bar labels.
CAPTION_BAND_TOP = 1320

#: Text keeps this far inside the safe rect, so antialiased edges and shaping never touch it.
TEXT_INSET = 12

CARD_KINDS = ("DATA_CARD", "TITLE_CARD", "BLACK")
MAX_BARS = 4

#: The film's timeline rate: the vendor's native 24 fps (TIMELINE_24_CAPTIONS). A card is drawn
#: at it, so it joins the generated clips with no frame-rate conversion.
CARD_FPS = 24

FONTS_DIR = Path(__file__).resolve().parent / "fonts"
BOLD = "Inter-Bold.ttf"
REGULAR = "Inter-Regular.ttf"

#: The bundled fonts: static instances (wght 700 / 400, opsz 14) of Inter Variable 4.001, the
#: copy Blender 5.2 ships, licensed OFL 1.1 (fonts/OFL.txt). A file that does not hash to its
#: row here is not used.
FONT_SHA256: dict[str, str] = {
    BOLD: "d4696a6b1da99ba49c9f859a0bab6d79fe3097a5d02ca94b4e6ce31c5a5aeb3c",
    REGULAR: "dbe264aba627cc75697ae5c27a5aef4b82ffa7c20228042a0886ce44e1afe2e4",
}

#: Bar animation: the first bar starts growing here, each next one this much later, and each
#: grows for this long with an ease-out cubic. Values fade in just after their bar settles.
BAR_START_SECONDS = 0.3
BAR_STAGGER_SECONDS = 0.6
BAR_GROW_SECONDS = 1.0
VALUE_DELAY_SECONDS = 0.1
LABEL_DELAY_SECONDS = 0.15
TEXT_FADE_SECONDS = 0.25
#: Time the finished card holds on screen before the cut, when the duration allows it.
HOLD_SECONDS = 0.3
MIN_DURATION_SECONDS = 1.0

#: A still background is blurred and every channel multiplied by this, so no pixel of it is
#: brighter than ``STILL_LUMA_CAP`` (limited-range luma) and white text always reads over it.
STILL_DARKEN = 0.42
STILL_BLUR_SIGMA = 30
STILL_LUMA_CAP = 110

#: The legibility floor for any text on a 1080 px wide phone frame.
MIN_TEXT_SIZE = 36

_HEX = re.compile(r"^#[0-9A-Fa-f]{6}$")
_LIVE_KIND = "LIVE"


class CardError(ValueError):
    """A card that cannot be composed honestly. The message is for the Owner, in Romanian."""


class FontMissingError(CardError):
    """A bundled font is absent (or not one of the pinned fonts)."""


class FontIntegrityError(CardError):
    """A bundled font's bytes do not hash to the pinned value."""


# --------------------------------------------------------------------------- palette


@dataclass(frozen=True)
class CardPalette:
    """The card's colours, as hex. The only place in the studio hex colours are drawn."""

    background: str = "#10161F"
    text: str = "#F4F1EA"
    muted: str = "#AEB6C2"
    bar: str = "#8FA3B8"
    highlight: str = "#E8A33D"
    axis: str = "#5B6675"

    def __post_init__(self) -> None:
        for name in ("background", "text", "muted", "bar", "highlight", "axis"):
            value = getattr(self, name)
            if not isinstance(value, str) or not _HEX.match(value):
                raise CardError(f"Culoare invalidă pentru card ({name}): {value!r}")


BLACK_PALETTE = CardPalette(background="#000000")


def _ff_color(hex_colour: str) -> str:
    return "0x" + hex_colour[1:].upper()


# --------------------------------------------------------------------------- fonts


def font_path(name: str) -> Path:
    """The verified path of a bundled font, or an error. Never a fallback."""
    return _verified_font(name)[0]


def _verified_font(name: str) -> tuple[Path, bytes]:
    pinned = FONT_SHA256.get(name)
    if pinned is None:
        raise FontMissingError(f"Fontul {name} nu face parte din fonturile studioului.")
    path = FONTS_DIR / name
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise FontMissingError(
            f"Fontul {name} lipsește din {FONTS_DIR}; cardul nu se compune cu alt font."
        ) from exc
    if hashlib.sha256(data).hexdigest() != pinned:
        raise FontIntegrityError(
            f"Fontul {name} nu corespunde amprentei SHA-256 fixate; cardul nu se compune."
        )
    return path, data


@dataclass(frozen=True)
class _Metrics:
    """Horizontal and vertical metrics read from a TrueType file: enough to measure a line."""

    units_per_em: int
    ascent: int
    descent: int
    cmap: dict[int, int]
    advances: tuple[int, ...]

    def covers(self, char: str) -> bool:
        return char.isspace() or ord(char) in self.cmap

    def width(self, text: str, size: float) -> float:
        last = self.advances[-1]
        units = 0
        for char in text:
            glyph = self.cmap.get(ord(char), 0)
            units += self.advances[glyph] if glyph < len(self.advances) else last
        return units * size / self.units_per_em

    def line_height(self, size: float) -> float:
        return (self.ascent - self.descent) * size / self.units_per_em


def _tables(data: bytes) -> dict[bytes, tuple[int, int]]:
    (count,) = struct.unpack_from(">H", data, 4)
    tables: dict[bytes, tuple[int, int]] = {}
    for index in range(count):
        tag, _checksum, offset, length = struct.unpack_from(">4sIII", data, 12 + 16 * index)
        tables[tag] = (offset, length)
    return tables


def _parse_cmap(data: bytes, offset: int) -> dict[int, int]:
    _version, count = struct.unpack_from(">HH", data, offset)
    subtables: dict[tuple[int, int], int] = {}
    for index in range(count):
        platform, encoding, sub = struct.unpack_from(">HHI", data, offset + 4 + 8 * index)
        subtables[(platform, encoding)] = offset + sub
    mapping: dict[int, int] = {}
    if (3, 10) in subtables:
        start = subtables[(3, 10)]
        (fmt,) = struct.unpack_from(">H", data, start)
        if fmt == 12:
            (groups,) = struct.unpack_from(">I", data, start + 12)
            for group in range(groups):
                first, last, glyph = struct.unpack_from(">III", data, start + 16 + 12 * group)
                for code in range(first, last + 1):
                    mapping[code] = glyph + code - first
            return mapping
    if (3, 1) not in subtables:
        raise FontIntegrityError("Fontul nu are o tabelă Unicode (cmap 3/1).")
    start = subtables[(3, 1)]
    fmt, _length, _language, seg_x2 = struct.unpack_from(">HHHH", data, start)
    if fmt != 4:
        raise FontIntegrityError("Fontul are o tabelă cmap într-un format necunoscut.")
    segs = seg_x2 // 2
    ends = struct.unpack_from(f">{segs}H", data, start + 14)
    starts = struct.unpack_from(f">{segs}H", data, start + 16 + seg_x2)
    deltas = struct.unpack_from(f">{segs}h", data, start + 16 + 2 * seg_x2)
    range_base = start + 16 + 3 * seg_x2
    offsets = struct.unpack_from(f">{segs}H", data, range_base)
    for seg in range(segs):
        for code in range(starts[seg], ends[seg] + 1):
            if code == 0xFFFF:
                continue
            if offsets[seg] == 0:
                glyph = (code + deltas[seg]) & 0xFFFF
            else:
                where = range_base + 2 * seg + offsets[seg] + 2 * (code - starts[seg])
                (glyph,) = struct.unpack_from(">H", data, where)
                if glyph:
                    glyph = (glyph + deltas[seg]) & 0xFFFF
            if glyph:
                mapping[code] = glyph
    return mapping


@lru_cache(maxsize=4)
def _metrics_for(digest: str, data: bytes) -> _Metrics:
    del digest  # the cache key; the bytes were verified against it by the caller
    tables = _tables(data)
    try:
        head, _ = tables[b"head"]
        hhea, _ = tables[b"hhea"]
        hmtx, _ = tables[b"hmtx"]
        maxp, _ = tables[b"maxp"]
        cmap, _ = tables[b"cmap"]
    except KeyError as exc:
        raise FontIntegrityError("Fontul nu are tabelele de metrici necesare.") from exc
    (units_per_em,) = struct.unpack_from(">H", data, head + 18)
    ascent, descent = struct.unpack_from(">hh", data, hhea + 4)
    (long_metrics,) = struct.unpack_from(">H", data, hhea + 34)
    (glyphs,) = struct.unpack_from(">H", data, maxp + 4)
    advances = [struct.unpack_from(">H", data, hmtx + 4 * i)[0] for i in range(long_metrics)]
    advances.extend([advances[-1]] * max(0, glyphs - long_metrics))
    return _Metrics(
        units_per_em=units_per_em,
        ascent=ascent,
        descent=descent,
        cmap=_parse_cmap(data, cmap),
        advances=tuple(advances),
    )


def _metrics(name: str) -> _Metrics:
    _path, data = _verified_font(name)
    return _metrics_for(FONT_SHA256[name], data)


def line_height_px(font: str, size: float) -> float:
    """One line's height at ``size`` px (the em) in a bundled font, from its own metrics."""
    return _metrics(font).line_height(size)


def text_width(text: str, size: float, font: str = BOLD) -> float:
    """How wide ``text`` is set at ``size`` px (the em) in a bundled font, from its own metrics.

    The burnt captions are laid out with this, so a caption line is measured with the font
    that draws it, not guessed from a character count.
    """
    return _metrics(font).width(text, size)


def em_for_cell(cell: float, font: str = BOLD) -> float:
    """The em size that fills a line ``cell`` px tall (ascent to descent).

    An ASS font size is that cell height, not the em (the VSFilter convention libass keeps):
    Inter Bold at ASS size 66 is set at an em of about 54.5 px, measured on a burnt frame.
    """
    metrics = _metrics(font)
    return cell * metrics.units_per_em / float(metrics.ascent - metrics.descent)


def uncovered_characters(text: str, font: str = BOLD) -> list[str]:
    """The characters of ``text`` the bundled font has no glyph for (each once, in order)."""
    metrics = _metrics(font)
    missing: list[str] = []
    for char in text:
        if not metrics.covers(char) and char not in missing:
            missing.append(char)
    return missing


def font_family(font: str = BOLD) -> str:
    """The family name inside a bundled font file (name ID 1, Windows Unicode).

    A caption style names the family, and the renderer matches it against the file it is
    handed; reading it from the file means the style can never name a font that is not there.
    """
    _path, data = _verified_font(font)
    tables = _tables(data)
    if b"name" not in tables:
        raise FontIntegrityError(f"Fontul {font} nu are tabela de nume.")
    offset, _length = tables[b"name"]
    _format, count, strings = struct.unpack_from(">HHH", data, offset)
    for index in range(count):
        platform, encoding, _language, name_id, length, at = struct.unpack_from(
            ">HHHHHH", data, offset + 6 + 12 * index
        )
        if platform == 3 and encoding in (1, 10) and name_id == 1:
            start = offset + strings + at
            return data[start : start + length].decode("utf-16-be")
    raise FontIntegrityError(f"Fontul {font} nu își spune familia (name ID 1).")


# --------------------------------------------------------------------------- spec


@dataclass(frozen=True)
class CardBar:
    label: str
    value: float
    unit: str
    claim_id: str


@dataclass(frozen=True)
class CardSpec:
    """What a card shows. For a DATA_CARD every value comes from a SUPPORTED claim."""

    kind: str
    title: str | None = None
    subtitle: str | None = None
    bars: tuple[CardBar, ...] = ()
    highlight: int | None = None
    cta: str | None = None


def _clean(value: Any, what: str, *, required: bool) -> str | None:
    if value is None:
        if required:
            raise CardError(f"Cardul nu are {what}.")
        return None
    if not isinstance(value, str):
        raise CardError(f"Câmpul {what} al cardului trebuie să fie text.")
    text = " ".join(value.split())
    if not text:
        if required:
            raise CardError(f"Cardul nu are {what}.")
        return None
    return text


def _bar(raw: Any, index: int) -> CardBar:
    if not isinstance(raw, dict):
        raise CardError(f"Bara {index + 1} a cardului nu este descrisă corect.")
    value = raw.get("value")
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise CardError(f"Bara {index + 1}: valoarea trebuie să fie un număr, nu {value!r}.")
    if not math.isfinite(value) or value <= 0:
        raise CardError(f"Bara {index + 1}: valoarea {value!r} nu poate fi desenată ca bară.")
    return CardBar(
        label=_clean(raw.get("label"), f"eticheta barei {index + 1}", required=True) or "",
        value=value,
        unit=_clean(raw.get("unit"), f"unitatea barei {index + 1}", required=True) or "",
        claim_id=_clean(raw.get("claim_id"), f"sursa barei {index + 1}", required=True) or "",
    )


def card_spec_from_json(kind: str, card_json: dict[str, Any] | None) -> CardSpec:
    """Read a scene's ``card_json`` into a spec, refusing anything that cannot be drawn truly."""
    if kind == _LIVE_KIND:
        raise CardError("O scenă LIVE nu se compune local; ea merge la etapa de imagini.")
    if kind not in CARD_KINDS:
        raise CardError(f"Tip de card necunoscut: {kind!r}.")
    raw = card_json or {}
    if not isinstance(raw, dict):
        raise CardError("Specificația cardului trebuie să fie un obiect.")

    if kind == "BLACK":
        return CardSpec(kind=kind, cta=_clean(raw.get("cta"), "îndemnul final", required=False))

    if kind == "TITLE_CARD":
        return CardSpec(
            kind=kind,
            title=_clean(raw.get("title"), "titlu", required=True),
            subtitle=_clean(raw.get("subtitle"), "subtitlu", required=False),
        )

    raw_bars = raw.get("bars")
    if not isinstance(raw_bars, list) or not raw_bars:
        raise CardError("Graficul nu are nicio bară.")
    if len(raw_bars) > MAX_BARS:
        raise CardError(f"Graficul are {len(raw_bars)} bare; cel mult {MAX_BARS} încap lizibil.")
    bars = tuple(_bar(item, index) for index, item in enumerate(raw_bars))
    units = {bar.unit for bar in bars}
    if len(units) > 1:
        raise CardError(
            "Barele au unități diferite ("
            + ", ".join(sorted(units))
            + "); un grafic compară doar mărimi de același fel."
        )

    highlight = raw.get("highlight")
    index: int | None
    if highlight is None:
        index = None
    elif isinstance(highlight, bool):
        raise CardError("Evidențierea graficului trebuie să numească o bară.")
    elif isinstance(highlight, int):
        if not 0 <= highlight < len(bars):
            raise CardError(f"Evidențierea {highlight} nu corespunde niciunei bare.")
        index = highlight
    elif isinstance(highlight, str):
        labels = [bar.label for bar in bars]
        wanted = " ".join(highlight.split())
        if wanted not in labels:
            raise CardError(f"Evidențierea „{wanted}” nu corespunde niciunei bare.")
        index = labels.index(wanted)
    else:
        raise CardError("Evidențierea graficului trebuie să numească o bară.")

    return CardSpec(
        kind=kind,
        title=_clean(raw.get("title"), "titlu", required=False),
        bars=bars,
        highlight=index,
    )


def format_value(value: float) -> str:
    """A number as a Romanian reader writes it: 1.000 for thousands, 83,5 for decimals.

    The digits are the spec's own; nothing is rounded beyond six decimals.
    """
    if isinstance(value, int) or float(value).is_integer():
        whole, fraction = f"{int(value):,}", ""
    else:
        text = f"{value:,.6f}".rstrip("0")
        whole, _, fraction = text.partition(".")
    whole = whole.replace(",", ".")
    return f"{whole},{fraction}" if fraction else whole


# --------------------------------------------------------------------------- layout


@dataclass(frozen=True)
class TextItem:
    """One drawn line of text. ``y`` is the top of the font's ascent (drawtext y_align=font)."""

    role: str
    text: str
    font: str
    size: int
    center_x: int
    y: int
    width: int
    height: int
    appear_at: float
    color: str

    @property
    def x(self) -> int:
        return self.center_x - (self.width + 1) // 2

    @property
    def box(self) -> tuple[int, int, int, int]:
        return (self.x, self.y, self.x + self.width, self.y + self.height)


@dataclass(frozen=True)
class BarGeometry:
    """A bar's final rectangle: ``x..x+width`` by ``baseline-height..baseline``."""

    x: int
    width: int
    baseline: int
    height: int
    start: float
    color: str


@dataclass(frozen=True)
class CardLayout:
    kind: str
    palette: CardPalette
    texts: tuple[TextItem, ...]
    bars: tuple[BarGeometry, ...] = ()
    axis: tuple[int, int, int, int] | None = None  # x, y, w, h
    grow_seconds: float = BAR_GROW_SECONDS


def _wrap(text: str, metrics: _Metrics, size: int, width: float) -> list[str] | None:
    lines: list[str] = []
    current = ""
    for word in text.split():
        candidate = f"{current} {word}" if current else word
        if metrics.width(candidate, size) <= width:
            current = candidate
            continue
        if metrics.width(word, size) > width:
            return None
        if current:
            lines.append(current)
        current = word
    if current:
        lines.append(current)
    return lines


def _fit(
    text: str, font: str, *, largest: int, smallest: int, width: float, max_lines: int
) -> tuple[int, list[str]]:
    """The largest size (in steps of 2 px) at which ``text`` wraps into ``max_lines``."""
    metrics = _metrics(font)
    missing = sorted({char for char in text if not metrics.covers(char)})
    if missing:
        raise CardError(f"Fontul cardului nu are caracterele: {' '.join(missing)}")
    size = largest
    while size >= smallest:
        lines = _wrap(text, metrics, size, width)
        if lines is not None and len(lines) <= max_lines:
            return size, lines
        size -= 2
    raise CardError(f"Textul „{text[:60]}” nu încape în zona sigură a cardului.")


def _lines(
    role: str,
    lines: list[str],
    font: str,
    size: int,
    *,
    center_x: int,
    top: float,
    appear_at: float,
    color: str,
) -> tuple[list[TextItem], float]:
    metrics = _metrics(font)
    height = math.ceil(metrics.line_height(size))
    advance = round(height * 1.02)
    items: list[TextItem] = []
    y = top
    for line in lines:
        items.append(
            TextItem(
                role=role,
                text=line,
                font=font,
                size=size,
                center_x=center_x,
                y=round(y),
                width=math.ceil(metrics.width(line, size)),
                height=height,
                appear_at=round(appear_at, 3),
                color=color,
            )
        )
        y += advance
    return items, y - advance + height if items else top


def _time_scale(duration: float, bars: int) -> float:
    needed = (
        BAR_START_SECONDS
        + BAR_STAGGER_SECONDS * max(0, bars - 1)
        + BAR_GROW_SECONDS
        + VALUE_DELAY_SECONDS
        + TEXT_FADE_SECONDS
        + HOLD_SECONDS
    )
    return min(1.0, duration / needed)


def layout_card(
    spec: CardSpec, *, duration: float = 4.0, palette: CardPalette | None = None
) -> CardLayout:
    """Where every bar and line of text goes, inside ``SAFE_RECT``. Pure: no encoder runs."""
    if duration < MIN_DURATION_SECONDS:
        raise CardError(f"Un card durează cel puțin {MIN_DURATION_SECONDS:.0f} secundă.")
    if palette is None:
        palette = BLACK_PALETTE if spec.kind == "BLACK" else CardPalette()
    x0, y0, x1, y1 = SAFE_RECT
    left, right = x0 + TEXT_INSET, x1 - TEXT_INSET
    width = right - left
    center = (x0 + x1) // 2

    if spec.kind == "DATA_CARD":
        return _layout_data(spec, duration, palette, left, width)

    blocks: list[tuple[str, str, str, int, int, int, str, float]] = []
    if spec.kind == "TITLE_CARD":
        blocks.append(("title", spec.title or "", BOLD, 96, 56, 4, palette.text, 0.1))
        if spec.subtitle:
            blocks.append(("subtitle", spec.subtitle, REGULAR, 52, 40, 3, palette.muted, 0.4))
    elif spec.cta:
        blocks.append(("cta", spec.cta, BOLD, 64, 44, 3, palette.text, 0.3))

    fitted = []
    for role, text, font, largest, smallest, max_lines, color, appear in blocks:
        size, lines = _fit(
            text, font, largest=largest, smallest=smallest, width=width, max_lines=max_lines
        )
        height = math.ceil(_metrics(font).line_height(size))
        block_height = round(height * 1.02) * (len(lines) - 1) + height
        fitted.append((role, lines, font, size, color, appear, block_height))
    gap = 32
    total = sum(item[-1] for item in fitted) + gap * max(0, len(fitted) - 1)
    bottom_limit = min(y1, CAPTION_BAND_TOP)
    top = (y0 + bottom_limit) / 2 - total / 2
    scale = min(1.0, duration / (0.4 + TEXT_FADE_SECONDS + HOLD_SECONDS))
    texts: list[TextItem] = []
    for role, lines, font, size, color, appear, block_height in fitted:
        items, _bottom = _lines(
            role,
            lines,
            font,
            size,
            center_x=center,
            top=top,
            appear_at=appear * scale,
            color=color,
        )
        texts.extend(items)
        top += block_height + gap
    return CardLayout(kind=spec.kind, palette=palette, texts=tuple(texts))


def _layout_data(
    spec: CardSpec, duration: float, palette: CardPalette, left: int, width: int
) -> CardLayout:
    x0, y0, x1, y1 = SAFE_RECT
    center = (x0 + x1) // 2
    bars = spec.bars
    count = len(bars)
    scale = _time_scale(duration, count)
    stagger = BAR_STAGGER_SECONDS * scale
    grow = BAR_GROW_SECONDS * scale
    texts: list[TextItem] = []

    top = float(y0 + 40)
    if spec.title:
        size, lines = _fit(spec.title, BOLD, largest=72, smallest=52, width=width, max_lines=3)
        items, bottom = _lines(
            "title", lines, BOLD, size, center_x=center, top=top, appear_at=0.0, color=palette.text
        )
        texts.extend(items)
        top = bottom + 8
    unit = bars[0].unit
    size, lines = _fit(unit, REGULAR, largest=44, smallest=36, width=width, max_lines=2)
    items, bottom = _lines(
        "unit",
        lines,
        REGULAR,
        size,
        center_x=center,
        top=top,
        appear_at=0.1 * scale,
        color=palette.muted,
    )
    texts.extend(items)
    top_limit = bottom + 32

    column = width / count
    bar_width = min(240, int(column * 0.6))
    label_fits = [
        _fit(bar.label, BOLD, largest=52, smallest=40, width=column - 16, max_lines=3)
        for bar in bars
    ]
    label_block = max(
        round(_metrics(BOLD).line_height(size) * 1.02) * (len(lines) - 1)
        + math.ceil(_metrics(BOLD).line_height(size))
        for size, lines in label_fits
    )
    baseline = min(y1, CAPTION_BAND_TOP) - TEXT_INSET - label_block - 28
    value_texts = [format_value(bar.value) for bar in bars]
    value_size = min(
        _fit(text, BOLD, largest=136, smallest=56, width=column - 12, max_lines=1)[0]
        for text in value_texts
    )
    value_height = math.ceil(_metrics(BOLD).line_height(value_size))
    value_gap = 16
    tallest = baseline - value_gap - value_height - top_limit
    if tallest < 200:
        raise CardError("Titlul și etichetele lasă prea puțin loc pentru bare.")
    largest_value = max(bar.value for bar in bars)

    geometry: list[BarGeometry] = []
    for index, bar in enumerate(bars):
        column_center = round(left + column * (index + 0.5))
        height = max(4, round(tallest * bar.value / largest_value))
        start = round(BAR_START_SECONDS * scale + stagger * index, 3)
        geometry.append(
            BarGeometry(
                x=column_center - bar_width // 2,
                width=bar_width,
                baseline=baseline,
                height=height,
                start=start,
                color=palette.highlight if spec.highlight == index else palette.bar,
            )
        )
        value_items, _ = _lines(
            "value",
            [value_texts[index]],
            BOLD,
            value_size,
            center_x=column_center,
            top=baseline - height - value_gap - value_height,
            appear_at=start + grow + VALUE_DELAY_SECONDS * scale,
            color=palette.text,
        )
        label_size, label_lines = label_fits[index]
        label_items, _ = _lines(
            "label",
            label_lines,
            BOLD,
            label_size,
            center_x=column_center,
            top=baseline + 28,
            appear_at=start + LABEL_DELAY_SECONDS * scale,
            color=palette.text,
        )
        texts.extend(value_items)
        texts.extend(label_items)
    return CardLayout(
        kind=spec.kind,
        palette=palette,
        texts=tuple(texts),
        bars=tuple(geometry),
        axis=(left, baseline, width, 4),
        grow_seconds=grow,
    )


# --------------------------------------------------------------------------- filtergraph


def _alpha(appear_at: float) -> str:
    return f"'clip((t-{appear_at:.3f})/{TEXT_FADE_SECONDS:.3f},0,1)'"


def _text_file(index: int) -> str:
    return f"text_{index:02d}.txt"


def build_filtergraph(layout: CardLayout, *, duration: float, fps: int, has_still: bool) -> str:
    """The ffmpeg filtergraph for a card. Fonts and texts are named relative to the work dir.

    Composition happens in RGBA; the one conversion to video is BT.709 limited range at the
    end, tagged as such, so black is Y = 16 and the card sits beside a graded clip without a
    step in its blacks.
    """
    frames = max(1, round(duration * fps))
    palette = layout.palette
    size = f"{FRAME_WIDTH}x{FRAME_HEIGHT}"
    chains: list[str] = []
    if has_still:
        chains.append(
            f"[0:v]scale={FRAME_WIDTH}:{FRAME_HEIGHT}:force_original_aspect_ratio=increase"
            f":flags=lanczos,crop={FRAME_WIDTH}:{FRAME_HEIGHT},gblur=sigma={STILL_BLUR_SIGMA},"
            f"eq=saturation=0.75,format=rgba,colorchannelmixer=rr={STILL_DARKEN}"
            f":gg={STILL_DARKEN}:bb={STILL_DARKEN},loop=loop={frames - 1}:size=1:start=0,"
            f"setpts=N/({fps}*TB)[base0]"
        )
    else:
        chains.append(
            f"color=c={_ff_color(palette.background)}:s={size}:r={fps}:d={duration:.3f},"
            "format=rgba[base0]"
        )
    current = "base0"
    for index, bar in enumerate(layout.bars):
        box = f"{bar.width}x{bar.height}"
        ease = f"clip((t-{bar.start:.3f})/{layout.grow_seconds:.3f},0,1)"
        chains.append(
            f"color=c=black@0.0:s={box}:r={fps}:d={duration:.3f},format=rgba[canvas{index}]"
        )
        chains.append(
            f"color=c={_ff_color(bar.color)}:s={box}:r={fps}:d={duration:.3f},"
            f"format=rgba[fill{index}]"
        )
        chains.append(
            f"[canvas{index}][fill{index}]overlay=x=0:y='h*pow(1-{ease},3)'"
            f":eval=frame:format=auto[bar{index}]"
        )
        chains.append(
            f"[{current}][bar{index}]overlay=x={bar.x}:y={bar.baseline - bar.height}"
            f":eval=init:format=auto[base{index + 1}]"
        )
        current = f"base{index + 1}"

    steps: list[str] = []
    if layout.axis is not None:
        ax, ay, aw, ah = layout.axis
        steps.append(f"drawbox=x={ax}:y={ay}:w={aw}:h={ah}:color={_ff_color(palette.axis)}:t=fill")
    for index, item in enumerate(layout.texts):
        steps.append(
            f"drawtext=fontfile={item.font}:textfile={_text_file(index)}:expansion=none"
            f":fontsize={item.size}:fontcolor={_ff_color(item.color)}"
            f":x='{item.center_x}-text_w/2':y={item.y}:y_align=font"
            f":alpha={_alpha(item.appear_at)}"
        )
    steps.append(
        "scale=out_color_matrix=bt709:out_range=tv,format=yuv420p,"
        "setparams=range=tv:color_primaries=bt709:color_trc=bt709:colorspace=bt709"
    )
    chains.append(f"[{current}]" + ",".join(steps) + "[card]")
    return ";".join(chains)


# --------------------------------------------------------------------------- compose


@dataclass(frozen=True)
class ComposedCard:
    """A card clip on disk. Composed locally: 0 credits, no adapter touched."""

    path: Path
    kind: str
    duration: float
    fps: int
    frames: int
    sha256: str
    layout: CardLayout
    filtergraph: str
    provenance: str = "composed"
    credits: int = 0
    fonts: dict[str, str] = field(default_factory=dict)


def compose_card(
    spec: CardSpec,
    out_path: Path | str,
    *,
    duration: float,
    fps: int = CARD_FPS,
    background_still: Path | str | None = None,
    palette: CardPalette | None = None,
    ffmpeg: str | None = None,
) -> ComposedCard:
    """Draw ``spec`` into a 1080x1920 H.264 clip (lossless intermediate) at ``out_path``.

    ``background_still`` is the film's approved scene-1 still, blurred and darkened behind a
    DATA_CARD or TITLE_CARD; a BLACK card is always pure black. The fonts are verified before
    anything else, so a missing font fails before the encoder is started.
    """
    fonts = {name: _verified_font(name)[1] for name in (BOLD, REGULAR)}
    if fps <= 0:
        raise CardError("Cadența cardului trebuie să fie pozitivă.")
    has_still = background_still is not None and spec.kind != "BLACK"
    if has_still and not Path(str(background_still)).is_file():
        raise CardError(f"Imaginea de fundal a cardului lipsește: {background_still}")
    layout = layout_card(spec, duration=duration, palette=palette)
    graph = build_filtergraph(layout, duration=duration, fps=fps, has_still=has_still)
    frames = max(1, round(duration * fps))

    binary = ffmpeg or find_ffmpeg()
    if not binary:
        raise CardError("FFmpeg lipsește; cardul nu poate fi compus.")
    target = Path(out_path).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="amn_card_") as work:
        workdir = Path(work)
        # The verified bytes themselves are what the encoder reads: no second look at the disk.
        for name, data in fonts.items():
            (workdir / name).write_bytes(data)
        for index, item in enumerate(layout.texts):
            (workdir / _text_file(index)).write_text(item.text, encoding="utf-8", newline="")
        partial = workdir / "card.mp4"
        command = [binary, "-v", "error", "-nostdin", "-y"]
        if has_still:
            command += ["-i", str(Path(str(background_still)).resolve())]
        command += [
            "-filter_complex",
            graph,
            "-map",
            "[card]",
            "-frames:v",
            str(frames),
            "-r",
            str(fps),
            "-an",
            # The shot intermediate's encode (assembler.INTERMEDIATE_VIDEO_ARGS, measured
            # 2026-10-01): x264 High at CRF 4, visually lossless for the one final encode, at
            # 0.06 MB a second for a chart over a blurred still (0.10 lossless).
            "-c:v",
            "libx264",
            "-profile:v",
            "high",
            "-preset",
            "veryfast",
            "-crf",
            "4",
            "-pix_fmt",
            "yuv420p",
            "-color_range",
            "tv",
            "-colorspace",
            "bt709",
            "-color_primaries",
            "bt709",
            "-color_trc",
            "bt709",
            "-movflags",
            "+faststart",
            str(partial),
        ]
        try:
            result = subprocess.run(  # noqa: S603 - argument list, no shell
                command,
                cwd=workdir,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=600,
                check=False,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise CardError(f"FFmpeg nu a putut compune cardul: {exc}") from exc
        if result.returncode != 0 or not partial.is_file():
            detail = (result.stderr or "").strip()[-500:]
            raise CardError(f"FFmpeg nu a putut compune cardul: {detail}")
        # The temp dir may be on another drive than the media folder: move, not rename.
        shutil.move(str(partial), str(target))

    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    return ComposedCard(
        path=target,
        kind=spec.kind,
        duration=duration,
        fps=fps,
        frames=frames,
        sha256=digest,
        layout=layout,
        filtergraph=graph,
        fonts=dict(FONT_SHA256),
    )
