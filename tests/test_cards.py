"""Cards: the scenes the studio composes itself, from verified numbers, for 0 credits.

The Nepal film asked a photographic image model for "two vertical bars side by side: the first
fills to the top, the second stops noticeably short" (100 vs 83 billion) and got a woman beside
two abstract bars; it asked for "a black screen, silent and still" and got a woman in a
landscape. Both were paid for. A chart, a title and a black screen are drawn here instead, with
ffmpeg alone and the bundled Inter font, and the numbers on screen are exactly the numbers in
the card spec.

Every ffmpeg test runs the real local encoder (skipped when the machine has none) and reads the
decoded luma plane back, so what is asserted is what a viewer would see. No provider is called:
cards never reach an image or video adapter.
"""

from __future__ import annotations

import ast
import hashlib
import json
import shutil
import subprocess
from pathlib import Path

import pytest
from app.media import cards
from app.media.cards import (
    SAFE_RECT,
    CardError,
    CardSpec,
    FontIntegrityError,
    FontMissingError,
    card_spec_from_json,
    compose_card,
    format_value,
    layout_card,
)
from app.media.toolchain import find_ffmpeg, find_ffprobe

FFMPEG = find_ffmpeg()
FFPROBE = find_ffprobe()
needs_ffmpeg = pytest.mark.skipif(
    FFMPEG is None or FFPROBE is None, reason="no FFmpeg on this machine"
)

W, H = 1080, 1920
X0, Y0, X1, Y1 = SAFE_RECT

#: The bundled fonts, pinned independently of the module so a swapped file fails here even if
#: someone edits the module's table to match it.
PINNED_FONT_SHA256 = {
    "Inter-Bold.ttf": "d4696a6b1da99ba49c9f859a0bab6d79fe3097a5d02ca94b4e6ce31c5a5aeb3c",
    "Inter-Regular.ttf": "dbe264aba627cc75697ae5c27a5aef4b82ffa7c20228042a0886ce44e1afe2e4",
}

NEPAL_CARD = {
    "title": "Promis vs. livrat, pe an",
    "bars": [
        {"label": "Promis", "value": 100, "unit": "mld. USD", "claim_id": "claim-promised"},
        {"label": "Livrat", "value": 83, "unit": "mld. USD", "claim_id": "claim-delivered"},
    ],
    "highlight": 1,
}


# --------------------------------------------------------------------------- helpers


def _luma(path: Path, t: float) -> bytes:
    """The decoded Y plane of the frame at ``t`` seconds, exactly as stored (no range change)."""
    assert FFMPEG is not None
    result = subprocess.run(  # noqa: S603 - argument list, no shell
        [
            FFMPEG,
            "-v",
            "error",
            "-ss",
            f"{t:.3f}",
            "-i",
            str(path),
            "-frames:v",
            "1",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "yuv420p",
            "-",
        ],
        capture_output=True,
        check=True,
        timeout=120,
    )
    assert len(result.stdout) >= W * H, "no frame decoded"
    return result.stdout[: W * H]


def _probe(path: Path) -> dict:
    assert FFPROBE is not None
    result = subprocess.run(  # noqa: S603 - argument list, no shell
        [
            FFPROBE,
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=width,height,pix_fmt,color_range,color_space,color_primaries,"
            "color_transfer,r_frame_rate,nb_frames",
            "-of",
            "json",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=True,
        timeout=60,
    )
    return json.loads(result.stdout)["streams"][0]


def _bar_height(y: bytes, x: int, baseline: int, background: int) -> int:
    """Contiguous bar pixels in column ``x``, counted upward from the row above the baseline."""
    height = 0
    for row in range(baseline - 1, 0, -1):
        if abs(y[row * W + x] - background) > 20:
            height += 1
        else:
            break
    return height


def _outside_safe_rect_extremes(y: bytes) -> tuple[int, int]:
    """The smallest and largest luma of every pixel outside SAFE_RECT."""
    lo, hi = 255, 0
    for row in range(H):
        line = y[row * W : (row + 1) * W]
        if row < Y0 or row >= Y1:
            parts = [line]
        else:
            parts = [line[:X0], line[X1:]]
        for part in parts:
            lo = min(lo, min(part))
            hi = max(hi, max(part))
    return lo, hi


def _region(y: bytes, x0: int, y0: int, x1: int, y1: int) -> list[int]:
    values: list[int] = []
    for row in range(y0, y1):
        values.extend(y[row * W + x0 : row * W + x1])
    return values


# --------------------------------------------------------------------------- fonts


def test_font_files_match_the_pinned_table() -> None:
    assert cards.FONT_SHA256 == PINNED_FONT_SHA256
    for name, pinned in PINNED_FONT_SHA256.items():
        data = (cards.FONTS_DIR / name).read_bytes()
        assert hashlib.sha256(data).hexdigest() == pinned, name
        assert cards.font_path(name) == cards.FONTS_DIR / name
    licence = (cards.FONTS_DIR / "OFL.txt").read_text(encoding="utf-8")
    assert "The Inter Project Authors" in licence
    assert "SIL Open Font License" in licence


def test_a_missing_font_raises_and_never_falls_back(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(cards, "FONTS_DIR", tmp_path)

    def no_encoder(*args, **kwargs):  # pragma: no cover - reaching it is the failure
        raise AssertionError("ffmpeg must not run without the pinned font")

    monkeypatch.setattr(cards.subprocess, "run", no_encoder)
    with pytest.raises(FontMissingError):
        cards.font_path("Inter-Bold.ttf")
    spec = card_spec_from_json("TITLE_CARD", {"title": "Nepal"})
    with pytest.raises(FontMissingError):
        compose_card(spec, tmp_path / "card.mp4", duration=2.0, ffmpeg="ffmpeg")


def test_a_tampered_font_raises(tmp_path, monkeypatch) -> None:
    for name in cards.FONT_SHA256:
        shutil.copyfile(cards.FONTS_DIR / name, tmp_path / name)
    tampered = bytearray((tmp_path / "Inter-Bold.ttf").read_bytes())
    tampered[-1] ^= 0xFF
    (tmp_path / "Inter-Bold.ttf").write_bytes(bytes(tampered))
    monkeypatch.setattr(cards, "FONTS_DIR", tmp_path)
    with pytest.raises(FontIntegrityError):
        cards.font_path("Inter-Bold.ttf")
    assert cards.font_path("Inter-Regular.ttf") == tmp_path / "Inter-Regular.ttf"


def test_an_unknown_font_name_is_refused() -> None:
    with pytest.raises(FontMissingError):
        cards.font_path("Arial.ttf")


def test_every_drawtext_names_the_bundled_font_file() -> None:
    spec = card_spec_from_json("DATA_CARD", NEPAL_CARD)
    graph = cards.build_filtergraph(layout_card(spec), duration=3.0, fps=30, has_still=False)
    drawtexts = [part for part in graph.split(",") if part.startswith("drawtext=")]
    assert drawtexts, graph
    for part in drawtexts:
        assert "fontfile=Inter-" in part
        assert ":font=" not in part and "=font=" not in part
        assert "expansion=none" in part
    # Hex colours live here and only here; the graph never carries a setrange=pc.
    assert "setrange" not in graph
    assert "out_range=tv" in graph


# --------------------------------------------------------------------------- spec


def test_card_spec_reads_the_nepal_numbers_exactly() -> None:
    spec = card_spec_from_json("DATA_CARD", NEPAL_CARD)
    assert isinstance(spec, CardSpec)
    assert [bar.value for bar in spec.bars] == [100, 83]
    assert [bar.claim_id for bar in spec.bars] == ["claim-promised", "claim-delivered"]
    assert spec.highlight == 1
    # A highlight may name a bar by its label.
    by_label = card_spec_from_json("DATA_CARD", {**NEPAL_CARD, "highlight": "Livrat"})
    assert by_label.highlight == 1


@pytest.mark.parametrize(
    ("kind", "card_json"),
    [
        ("LIVE", {"title": "x"}),
        ("CHART", {"title": "x"}),
        ("DATA_CARD", {"title": "x", "bars": []}),
        ("DATA_CARD", {"bars": [{"label": "a", "value": 1, "unit": "u"}]}),  # no claim_id
        ("DATA_CARD", {"bars": [{"label": "a", "value": 0, "unit": "u", "claim_id": "c"}]}),
        ("DATA_CARD", {"bars": [{"label": "a", "value": "83", "unit": "u", "claim_id": "c"}]}),
        (
            "DATA_CARD",
            {"bars": [{"label": "a", "value": float("nan"), "unit": "u", "claim_id": "c"}]},
        ),
        (
            "DATA_CARD",
            {
                "bars": [
                    {"label": "a", "value": 1, "unit": "mld. USD", "claim_id": "c1"},
                    {"label": "b", "value": 2, "unit": "%", "claim_id": "c2"},
                ]
            },
        ),
        ("DATA_CARD", {**NEPAL_CARD, "highlight": 5}),
        ("TITLE_CARD", {"title": "  "}),
    ],
)
def test_an_invalid_card_spec_is_refused(kind: str, card_json: dict) -> None:
    with pytest.raises(CardError):
        card_spec_from_json(kind, card_json)


def test_a_highlight_written_as_a_sentence_names_the_bar_it_mentions() -> None:
    """The Owner's LHC film, 2026-10-03: the writer wrote the highlight as the narration's
    sentence ("Normal matter accounts for only 5% of the content of the universe."), the card
    asked for a bar's exact label, and the whole script was refused at every attempt."""
    universe = {
        "title": "Ce conține universul",
        "bars": [
            {"label": "Normal matter", "value": 5, "unit": "%", "claim_id": "c1"},
            {"label": "Dark matter", "value": 27, "unit": "%", "claim_id": "c2"},
            {"label": "Dark energy", "value": 68, "unit": "%", "claim_id": "c3"},
        ],
    }
    sentence = "Normal matter accounts for only 5% of the content of the universe."

    assert card_spec_from_json("DATA_CARD", {**universe, "highlight": sentence}).highlight == 0
    assert card_spec_from_json("DATA_CARD", {**universe, "highlight": "dark ENERGY"}).highlight == 2


def test_a_highlight_that_names_no_bar_or_several_is_dropped_not_fatal() -> None:
    """The highlight only colours a bar: a word that names none of them, or more than one,
    leaves the chart without a highlight instead of refusing the film's script."""
    nothing = card_spec_from_json("DATA_CARD", {**NEPAL_CARD, "highlight": "Nimic"})
    both = card_spec_from_json("DATA_CARD", {**NEPAL_CARD, "highlight": "Promis și Livrat"})

    assert nothing.highlight is None and both.highlight is None
    assert [bar.value for bar in nothing.bars] == [100, 83]


def test_black_needs_no_spec() -> None:
    spec = card_spec_from_json("BLACK", None)
    assert spec.kind == "BLACK" and spec.cta is None and spec.bars == ()


@pytest.mark.parametrize(
    ("value", "text"),
    [
        (100, "100"),
        (83, "83"),
        (83.5, "83,5"),
        (1000, "1.000"),
        (2.25, "2,25"),
        (1234567, "1.234.567"),
    ],
)
def test_values_are_written_the_romanian_way(value: float, text: str) -> None:
    assert format_value(value) == text


# --------------------------------------------------------------------------- layout


def _inside(box: tuple[int, int, int, int]) -> bool:
    x0, y0, x1, y1 = box
    return X0 <= x0 and y0 >= Y0 and x1 <= X1 and y1 <= Y1


@pytest.mark.parametrize(
    ("kind", "card_json"),
    [
        ("DATA_CARD", NEPAL_CARD),
        (
            "DATA_CARD",
            {
                "title": "Cât a promis lumea țărilor sărace și cât a ajuns cu adevărat la ele",
                "bars": [
                    {
                        "label": f"Finanțare climatică anul {year}",
                        "value": value,
                        "unit": "miliarde de dolari americani",
                        "claim_id": f"c{year}",
                    }
                    for year, value in ((2019, 79.6), (2020, 83.3), (2021, 89.6), (2022, 115.9))
                ],
            },
        ),
        ("TITLE_CARD", {"title": "Nepalul plătește o factură climatică pe care nu a scris-o"}),
        ("TITLE_CARD", {"title": "Nepal", "subtitle": "Cine plătește factura climei?"}),
        ("BLACK", {"cta": "Abonează-te pentru următorul episod"}),
    ],
)
def test_every_layout_box_lies_inside_the_safe_rect(kind: str, card_json: dict) -> None:
    layout = layout_card(card_spec_from_json(kind, card_json))
    assert layout.texts or layout.bars
    for item in layout.texts:
        assert _inside(item.box), (item.text, item.box)
        assert item.size >= cards.MIN_TEXT_SIZE, (item.text, item.size)
    for bar in layout.bars:
        assert _inside((bar.x, bar.baseline - bar.height, bar.x + bar.width, bar.baseline))


def test_nepal_values_are_large_and_labels_are_52_px() -> None:
    layout = layout_card(card_spec_from_json("DATA_CARD", NEPAL_CARD))
    values = [item for item in layout.texts if item.role == "value"]
    labels = [item for item in layout.texts if item.role == "label"]
    assert [item.text for item in values] == ["100", "83"]
    assert all(120 <= item.size <= 150 for item in values)
    assert [item.text for item in labels] == ["Promis", "Livrat"]
    assert all(item.size == 52 for item in labels)
    # Each value appears slightly after its bar has finished growing.
    for value, bar in zip(values, layout.bars, strict=True):
        assert value.appear_at > bar.start + cards.BAR_GROW_SECONDS - 0.2
    assert layout.bars[1].start == pytest.approx(layout.bars[0].start + 0.6)


def test_a_word_too_long_for_the_card_is_refused_not_clipped() -> None:
    spec = card_spec_from_json("TITLE_CARD", {"title": "Ș" * 80})
    with pytest.raises(CardError):
        layout_card(spec)


def test_the_compositor_imports_no_provider() -> None:
    tree = ast.parse(Path(cards.__file__).read_text(encoding="utf-8"))
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.append(node.module or "")
    for name in imported:
        assert "providers" not in name and "httpx" not in name and "requests" not in name, name


# --------------------------------------------------------------------------- real ffmpeg


@needs_ffmpeg
def test_nepal_bars_grow_to_their_true_ratio(tmp_path) -> None:
    spec = card_spec_from_json("DATA_CARD", NEPAL_CARD)
    card = compose_card(spec, tmp_path / "nepal_card.mp4", duration=3.0, fps=30, ffmpeg=FFMPEG)
    assert card.credits == 0 and card.provenance == "composed"
    assert card.path.is_file() and card.frames == 90
    assert card.sha256 == hashlib.sha256(card.path.read_bytes()).hexdigest()

    first, second = card.layout.bars
    background = _luma(card.path, 0.2)[100 * W + 50]

    def heights(t: float) -> tuple[int, int]:
        y = _luma(card.path, t)
        return (
            _bar_height(y, first.x + first.width // 2, first.baseline, background),
            _bar_height(y, second.x + second.width // 2, second.baseline, background),
        )

    assert heights(0.2) == (0, 0)
    rising = [heights(t) for t in (0.6, 1.0, 1.4)]
    assert all(a[0] <= b[0] and a[1] <= b[1] for a, b in zip(rising, rising[1:], strict=False))
    sums = [a + b for a, b in rising]
    assert sums[0] > 0 and sums[0] < sums[1] < sums[2]

    final_first, final_second = heights(2.0)
    assert final_first == first.height
    assert final_second / final_first == pytest.approx(0.83, abs=0.02)


@needs_ffmpeg
@pytest.mark.parametrize(
    ("kind", "card_json"),
    [
        ("DATA_CARD", NEPAL_CARD),
        ("TITLE_CARD", {"title": "Nepalul plătește o factură", "subtitle": "pe care nu a scris-o"}),
    ],
)
def test_every_non_background_pixel_lies_inside_the_safe_rect(tmp_path, kind, card_json) -> None:
    spec = card_spec_from_json(kind, card_json)
    card = compose_card(spec, tmp_path / "card.mp4", duration=3.0, fps=30, ffmpeg=FFMPEG)
    background = _luma(card.path, 0.0)[10 * W + 10]
    for t in (0.5, 1.5, 2.9):
        y = _luma(card.path, t)
        lo, hi = _outside_safe_rect_extremes(y)
        assert background - 1 <= lo <= hi <= background + 1, (t, lo, hi, background)
        # And something is actually drawn inside it.
        assert max(_region(y, X0, Y0, X1, Y1)) > background + 60


@needs_ffmpeg
def test_black_is_limited_range_black(tmp_path) -> None:
    card = compose_card(
        card_spec_from_json("BLACK", None),
        tmp_path / "black.mp4",
        duration=2.0,
        fps=30,
        ffmpeg=FFMPEG,
    )
    stream = _probe(card.path)
    assert (stream["width"], stream["height"]) == (W, H)
    assert stream["pix_fmt"] == "yuv420p"
    assert stream["color_range"] == "tv"
    assert stream["color_space"] == "bt709"
    assert stream["r_frame_rate"] == "30/1"
    for t in (0.0, 0.5, 1.0, 1.5, 1.95):
        y = _luma(card.path, t)
        assert max(y) <= 17 and min(y) >= 16, t


@needs_ffmpeg
def test_black_cta_stays_inside_the_safe_rect(tmp_path) -> None:
    spec = card_spec_from_json("BLACK", {"cta": "Urmărește episodul următor"})
    card = compose_card(spec, tmp_path / "black_cta.mp4", duration=2.5, fps=30, ffmpeg=FFMPEG)
    y = _luma(card.path, 2.0)
    lo, hi = _outside_safe_rect_extremes(y)
    assert 16 <= lo <= hi <= 17
    assert max(_region(y, X0, Y0, X1, Y1)) > 150


@needs_ffmpeg
def test_a_blurred_still_background_keeps_the_text_readable(tmp_path) -> None:
    assert FFMPEG is not None
    # The worst case a scene-1 still can be: bright, busy and near white.
    still = tmp_path / "scene_01.png"
    subprocess.run(  # noqa: S603 - argument list, no shell
        [
            FFMPEG,
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=s=1530x2720,eq=brightness=0.35",
            "-frames:v",
            "1",
            str(still),
        ],
        check=True,
        timeout=120,
    )
    spec = card_spec_from_json("DATA_CARD", NEPAL_CARD)
    card = compose_card(
        spec, tmp_path / "card_on_still.mp4", duration=3.0, background_still=still, ffmpeg=FFMPEG
    )
    y = _luma(card.path, 2.9)
    for item in card.layout.texts:
        if item.role not in {"label", "value"}:
            continue
        x0, y0, x1, y1 = item.box
        region = sorted(_region(y, x0, y0, x1, y1))
        ink = region[int(len(region) * 0.99)]
        ground = region[int(len(region) * 0.30)]
        assert ink - ground >= 100, (item.text, ink, ground)
    # Outside the safe rect the picture is the still, darkened: nothing brighter than the cap.
    _, hi = _outside_safe_rect_extremes(y)
    assert hi <= cards.STILL_LUMA_CAP


def test_card_content_stays_above_the_burnt_caption_band():
    """The zero-credit Nepal rehearsal (2026-10-01) burnt the narration's captions over the
    chart's bar labels: both sat at the bottom of SAFE_RECT. Every card element now ends
    above the band two burnt caption lines can occupy (bottom at y 1500, Inter Bold 66 px)."""
    import math

    from app.media.assembler import CAPTION_BOTTOM_Y, CAPTION_FONT_SIZE
    from app.media.cards import CAPTION_BAND_TOP, line_height_px

    two_lines = 2 * math.ceil(line_height_px("Inter-Bold.ttf", CAPTION_FONT_SIZE))
    assert CAPTION_BAND_TOP <= CAPTION_BOTTOM_Y - two_lines
    specs = [
        card_spec_from_json("DATA_CARD", NEPAL_CARD),
        card_spec_from_json("TITLE_CARD", {"title": "Cine plătește factura climatică?"}),
        card_spec_from_json("BLACK", {"cta": "Urmărește pentru partea a doua"}),
    ]
    for spec in specs:
        layout = layout_card(spec, duration=4.0)
        for item in layout.texts:
            assert item.box[3] <= CAPTION_BAND_TOP, (spec.kind, item.role, item.box)
        for bar in layout.bars:
            assert bar.baseline <= CAPTION_BAND_TOP, (spec.kind, bar)


# --------------------------------------------------------------------------- shorts: endings


def _bright_still(tmp_path: Path) -> Path:
    assert FFMPEG is not None
    still = tmp_path / "hook.png"
    subprocess.run(  # noqa: S603 - argument list, no shell
        [FFMPEG, "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=1024x1536",
         "-frames:v", "1", str(still)],
        check=True,
        timeout=120,
    )  # fmt: skip
    return still


def test_a_short_refuses_pure_black_longer_than_a_beat() -> None:
    spec = card_spec_from_json("BLACK", {"cta": "Urmărește episodul următor"})
    assert cards.MAX_SHORT_BLACK_SECONDS == 1.5
    reason = cards.black_refusal(spec, duration=4.3, short=True, has_still=False)
    assert reason is not None and "1,5" in reason and "negru" in reason
    # A beat is allowed, and so is a long closing card that stands on the hook's picture.
    assert cards.black_refusal(spec, duration=1.5, short=True, has_still=False) is None
    assert cards.black_refusal(spec, duration=4.3, short=True, has_still=True) is None
    # Layout alone is pure and refuses nothing.
    assert layout_card(spec, duration=4.3).texts


def test_the_short_rule_is_the_compositors(tmp_path) -> None:
    spec = card_spec_from_json("BLACK", None)
    with pytest.raises(CardError, match="1,5"):
        compose_card(spec, tmp_path / "x.mp4", duration=2.0, short=True, ffmpeg="unused")
    # Outside a short (the default) the black card is composed as it always was.
    assert not cards.black_refusal(spec, duration=2.0, short=False, has_still=False)


@needs_ffmpeg
def test_a_closing_card_in_a_short_stands_on_the_hook_still_and_moves(tmp_path) -> None:
    spec = card_spec_from_json("BLACK", {"cta": "Cine plătește data viitoare?"})
    card = compose_card(
        spec,
        tmp_path / "closing.mp4",
        duration=3.0,
        fps=24,
        background_still=_bright_still(tmp_path),
        short=True,
        ffmpeg=FFMPEG,
    )
    assert card.closing is True
    early, late = _luma(card.path, 0.3), _luma(card.path, 2.6)
    # Not black: the hook's picture, darkened so the words read.
    assert sum(late) / len(late) > 30
    # And not frozen: the picture pushes in slowly under the words.
    differing = sum(1 for a, b in zip(early, late, strict=True) if abs(a - b) > 8)
    assert differing > len(early) * 0.05
    lo, hi = _outside_safe_rect_extremes(late)
    assert hi <= 255 and lo >= 16
    for item in card.layout.texts:
        assert _inside(item.box), item


# --------------------------------------------------------------------------- the cover


@needs_ffmpeg
def test_a_cover_is_composed_locally_from_the_hero_still_and_the_hook(tmp_path) -> None:
    still = _bright_still(tmp_path)
    cover = cards.compose_cover(
        still, "Cine plătește pentru o criză pe care nu a creat-o?", tmp_path / "cover.png",
        ffmpeg=FFMPEG,
    )  # fmt: skip
    assert cover.path.is_file() and cover.credits == 0 and cover.provenance == "composed"
    stream = _probe(cover.path)
    assert (stream["width"], stream["height"]) == (W, H)
    assert cover.layout.texts and all(item.role == "hook" for item in cover.layout.texts)
    for item in cover.layout.texts:
        assert _inside(item.box), item.box
        assert item.font == cards.BOLD and item.size >= 56
    y = _luma(cover.path, 0.0)
    first = cover.layout.texts[0]
    x0, y0, x1, y1 = first.box
    region = sorted(_region(y, x0, y0, x1, y1))
    assert region[int(len(region) * 0.99)] >= 200, "the hook is drawn bright"
    # The picture below the hook is the still itself, not a card.
    lower = _region(y, X0, 1400, X1, 1500)
    assert max(lower) - min(lower) > 60


def test_a_hook_the_font_cannot_draw_is_refused_not_substituted(tmp_path) -> None:
    with pytest.raises(CardError):
        cards.compose_cover(
            tmp_path / "missing.png", "漢字のフック", tmp_path / "cover.png", ffmpeg="unused"
        )
