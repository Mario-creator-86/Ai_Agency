"""The Owner's quality-control report, written from what was measured and nothing else.

The Nepal film (2026-09-26) failed quality control and the Owner was told neither what it had
cost nor what it would take to fix: the books showed 0.74 USD while the balance had moved 966
credits, a letter said the audio had been re-rendered when nothing had happened, and the only
remedy anyone proposed was to render the whole film again, which is how a second full film
was bought. This module is pure (no database, no network, no provider) and deterministic:

* ``measured_spend`` reads only balance deltas (``before`` and ``after``, as
  ``app.economy.credits.credit_spend`` records them). An estimate, a quote or a ``spent`` with
  no balances is not a cost; an unmeasured spend reads "necunoscut", never 0.
* ``redo_proposals`` turns a report into what can be redone, per scene: ``audio`` and
  ``encode`` (0 credits, from the files already paid for), ``card`` (a chart, title or black
  screen composed locally, 0 credits), and ``still`` / ``motion`` for a LIVE scene, priced
  from a shooting sheet (``app.media.cost_plan.plan_film``'s shape) when there is one. There
  is no whole-film proposal: a scene that passed is never bought again.
* ``qc_summary_ro`` writes the Owner's report in Romanian: what failed, with the measured
  evidence; the credits measured; what is fixed for free; what needs credits, scene by scene.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from typing import Any

from app.media.cost_plan import credits_to_micros

UNKNOWN = "necunoscut"
FREE_HEADING = "Se repară gratuit (0 credite):"
PAID_HEADING = "Necesită credite (doar cu aprobarea Proprietarului pe foaia de filmare):"
NOTHING = "- nimic"

#: The publish gate, unchanged: PASSED and a score of at least this.
PUBLISH_SCORE = 0.90

LIVE = "LIVE"
DATA_CARD = "DATA_CARD"
TITLE_CARD = "TITLE_CARD"
BLACK = "BLACK"
CARD_KINDS = frozenset({DATA_CARD, TITLE_CARD, BLACK})

#: What can be redone. Nothing else is ever proposed; in particular not the whole film.
REDO_KINDS = ("audio", "encode", "card", "still", "motion")

_CARD_WORDS = {
    DATA_CARD: "grafic compus local din cifrele verificate",
    TITLE_CARD: "titlu compus local",
    BLACK: "ecran negru compus local",
}

#: A deterministic reading of what a scene asked for, for reports made before scenes carried
#: their own kind (the Nepal film). A chart first: the Nepal chart scene also "fades to black".
_KIND_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        DATA_CARD,
        re.compile(
            r"\b(?:bars?|bar chart|charts?|graphs?|infographics?|percent\w*|grafic\w*|"
            r"procent\w*)\b",
            re.IGNORECASE,
        ),
    ),
    (
        BLACK,
        re.compile(r"black screen|fades? to black|ecran(?:ul)? negru|pure black", re.IGNORECASE),
    ),
    (TITLE_CARD, re.compile(r"title card|on-screen title|\btitlu\b", re.IGNORECASE)),
)

#: Checks with a handler of their own below; any other failing check is still named.
_KNOWN_CHECKS = frozenset(
    {
        "technical_qc",
        "audio_qc",
        "captions_qc",
        "picture_qc",
        "motion_qc",
        "content_integrity_qc",
        "character_drift_qc",
        "factual_qc",
        "rights_qc",
        "content_source_qc",
    }
)


@dataclass(frozen=True)
class RedoProposal:
    """One thing to redo: what, for which scene (None for the whole soundtrack or encode),
    why (Romanian, quoting the measurement) and what it costs (0 free, None unpriced)."""

    redo: str
    scene_index: int | None
    reason: str
    credits: int | None
    usd_micros: int | None = None
    price_source: str | None = None
    model_id: str | None = None
    resolution: str | None = None

    @property
    def free(self) -> bool:
        return self.credits == 0

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


# ------------------------------------------------------------------------------ formatting


def ro_number(value: float, decimals: int = 0) -> str:
    """A number the Romanian way: 1.636, 9,66, −0,93 (a true minus sign)."""
    rounded = round(float(value), decimals)
    text = f"{abs(rounded):,.{decimals}f}".replace(",", " ").replace(".", ",").replace(" ", ".")
    return ("−" if rounded < 0 else "") + text


def ro_count(count: float, singular_plural: str) -> str:
    """'18 credite', '200 de credite', '218 credite': Romanian puts 'de' after 20..99 and
    after round hundreds (the last two digits decide)."""
    whole = int(round(float(count)))
    tail = abs(whole) % 100
    joiner = " de " if whole != 0 and (tail == 0 or tail >= 20) else " "
    return f"{ro_number(whole)}{joiner}{singular_plural}"


def _usd(micros: int | None) -> str | None:
    return None if micros is None else f"{ro_number(micros / 1_000_000, 2)} USD"


def _quote(text: Any, limit: int = 160) -> str:
    # The sentence around a quote supplies its own full stop.
    words = " ".join(str(text or "").split()).rstrip(" .")
    return words if len(words) <= limit else words[: limit - 1].rstrip() + "…"


# ------------------------------------------------------------------------- measured spend


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value)


def measured_spend(spend: Mapping[str, Any] | None) -> dict[str, float | None]:
    """What the vendors' own balances say was spent, from ``production['credits_measured']``.

    Only an item with a numeric balance before and after is a measurement; its ``spent`` must
    agree with them. USD is read only when it was recorded with the measurement.
    """
    runway: float | None = None
    runway_usd: float | None = None
    voice: float | None = None
    for item in (spend or {}).values() if isinstance(spend, Mapping) else ():
        if not isinstance(item, Mapping):
            continue
        before, after = _number(item.get("before")), _number(item.get("after"))
        if before is None or after is None:
            continue
        kind = str(item.get("kind") or "")
        delta = before - after if kind == "runway" else after - before
        stated = _number(item.get("spent"))
        if stated is not None and abs(stated - delta) > 1e-6:
            continue
        if kind == "runway" and str(item.get("unit") or "credits") == "credits":
            runway = (runway or 0.0) + delta
            usd = _number(item.get("usd"))
            if usd is not None:
                runway_usd = (runway_usd or 0.0) + usd
        elif kind == "elevenlabs":
            voice = (voice or 0.0) + delta
    return {"runway_credits": runway, "runway_usd": runway_usd, "voice_characters": voice}


def _credits_line(spend: Mapping[str, Any] | None) -> str:
    measured = measured_spend(spend)
    runway = measured["runway_credits"]
    if runway is None and measured["voice_characters"] is None:
        return (
            f"Credite măsurate: {UNKNOWN} (soldul furnizorilor nu a fost citit înainte și "
            "după această randare)."
        )
    parts: list[str] = []
    if runway is None:
        parts.append(f"Runway {UNKNOWN}")
    else:
        usd = measured["runway_usd"]
        parts.append(
            f"Runway {ro_count(runway, 'credite')}"
            + (f" ({ro_number(usd, 2)} USD)" if usd is not None else "")
        )
    if measured["voice_characters"] is not None:
        parts.append(f"ElevenLabs {ro_count(measured['voice_characters'], 'caractere')}")
    return "Credite măsurate: " + "; ".join(parts) + "."


# ------------------------------------------------------------------------------ scene kinds


def kind_from_text(text: str | None) -> str | None:
    """DATA_CARD, BLACK or TITLE_CARD when the words ask for one; None otherwise."""
    for kind, pattern in _KIND_PATTERNS:
        if text and pattern.search(text):
            return kind
    return None


def _sheet_rows(sheet: Mapping[str, Any] | None) -> dict[int, Mapping[str, Any]]:
    rows: dict[int, Mapping[str, Any]] = {}
    for row in (sheet or {}).get("scenes") or [] if isinstance(sheet, Mapping) else []:
        if isinstance(row, Mapping) and row.get("scene_index") is not None:
            rows[int(row["scene_index"])] = row
    return rows


def _kind_of(
    scene: int, evidence: str, rows: Mapping[int, Mapping[str, Any]], kinds: Mapping[int, str]
) -> str:
    row = rows.get(scene)
    if row is not None and row.get("kind"):
        return str(row["kind"]).upper()
    if scene in kinds and kinds[scene]:
        return str(kinds[scene]).upper()
    return kind_from_text(evidence) or LIVE


# ------------------------------------------------------------------------------ the report


def _as_report(report: Any) -> dict[str, Any]:
    if isinstance(report, Mapping):
        return dict(report)
    return {
        "status": getattr(report, "status", None),
        "score": getattr(report, "score", None),
        "checks_json": getattr(report, "checks_json", None) or {},
        "failure_reasons_json": getattr(report, "failure_reasons_json", None) or [],
    }


def _checks(report: Mapping[str, Any]) -> dict[str, Any]:
    checks = report.get("checks_json") or report.get("checks") or {}
    return dict(checks) if isinstance(checks, Mapping) else {}


def _failed(check: Any) -> bool:
    return isinstance(check, Mapping) and check.get("passed") is False


def _scene_number(entry: Mapping[str, Any]) -> int | None:
    for key in ("scene", "scene_index"):
        value = entry.get(key)
        if isinstance(value, int) and not isinstance(value, bool):
            return value
    return None


@dataclass
class _Reading:
    """What a report says failed, as Romanian lines, and which scenes need what."""

    failures: list[str]
    audio: bool
    encode_reasons: list[str]
    # scene -> (what to redo: "picture" (still+motion) | "motion", the evidence)
    scenes: dict[int, tuple[str, str]]


def _audio_failure(check: Mapping[str, Any]) -> str:
    parts: list[str] = []
    peak, ceiling = (
        _number(check.get("true_peak_dbtp")),
        _number(check.get("true_peak_ceiling_dbtp")),
    )
    if peak is not None and ceiling is not None and peak > ceiling:
        parts.append(
            f"vârful real {ro_number(peak, 2)} dBTP, peste plafonul de {ro_number(ceiling, 1)} dBTP"
        )
    loudness = _number(check.get("integrated_lufs"))
    band = check.get("band_lufs")
    if (
        loudness is not None
        and isinstance(band, Sequence)
        and len(band) == 2
        and all(_number(v) is not None for v in band)
    ):
        low, high = float(band[0]), float(band[1])
        if not low <= loudness <= high:
            parts.append(
                f"tăria {ro_number(loudness, 2)} LUFS, în afara benzii "
                f"{ro_number(low, 1)}…{ro_number(high, 1)} LUFS"
            )
    if check.get("error"):
        parts.append(f"sunetul nu a putut fi măsurat ({_quote(check['error'], 120)})")
    return "Sunet: " + ("; ".join(parts) if parts else "controlul sunetului a picat") + "."


def _technical_failure(check: Mapping[str, Any]) -> str:
    parts: list[str] = []
    if check.get("probe_error"):
        parts.append(f"fișierul nu a putut fi citit ({_quote(check['probe_error'], 120)})")
    width, height = check.get("measured_width"), check.get("measured_height")
    if (width, height) != (None, None) and (width, height) != (1080, 1920):
        parts.append(f"{width}×{height} în loc de 1080×1920")
    codec = check.get("video_codec")
    if codec and codec != "h264":
        parts.append(f"codec {codec} în loc de h264")
    bitrate = _number(check.get("measured_bitrate_bps") or check.get("bitrate_bps"))
    if bitrate is not None:
        parts.append(f"debit {ro_number(bitrate / 1_000_000, 1)} Mbps")
    if check.get("color_range") and check.get("color_range") != "tv":
        parts.append(f"interval de culoare {check['color_range']} în loc de tv (limitat)")
    if check.get("has_audio_stream") is False:
        parts.append("fără pistă audio")
    return "Codare: " + ("; ".join(parts) if parts else "controlul tehnic a picat") + "."


def _read(report: Mapping[str, Any]) -> _Reading:
    checks = _checks(report)
    reading = _Reading(failures=[], audio=False, encode_reasons=[], scenes={})

    audio = checks.get("audio_qc")
    if _failed(audio):
        assert isinstance(audio, Mapping)
        reading.failures.append(_audio_failure(audio))
        reading.audio = True

    technical = checks.get("technical_qc")
    if _failed(technical):
        assert isinstance(technical, Mapping)
        line = _technical_failure(technical)
        reading.failures.append(line)
        reading.encode_reasons.append(
            "Codare: filmul se recodează din clipurile deja plătite (" + line[8:].rstrip(".") + ")."
        )

    captions = checks.get("captions_qc")
    if _failed(captions):
        assert isinstance(captions, Mapping)
        problems = [str(p) for p in captions.get("problems") or [] if str(p).strip()]
        detail = (
            "; ".join(_quote(p, 120) for p in problems[:3]) or "controlul subtitrărilor a picat"
        )
        reading.failures.append(f"Subtitrări: {detail}.")
        reading.encode_reasons.append("Subtitrări: se refac la asamblare, din textul narațiunii.")

    picture = checks.get("picture_qc")
    if isinstance(picture, Mapping):
        if picture.get("status") == "NOT_RUN":
            reading.failures.append(
                "Imagine: controlul imaginii nu a rulat; un control care nu a rulat blochează "
                "publicarea (se reia fără credite)."
            )
        for entry in picture.get("scenes") or []:
            if not isinstance(entry, Mapping):
                continue
            scene = _scene_number(entry)
            if scene is None:
                continue
            if entry.get("status") == "NOT_RUN":
                reading.failures.append(f"Scena {scene}: imaginea nu a fost verificată.")
                continue
            if entry.get("is_a_picture") is False:
                what = "cadrul nu este o imagine"
            elif entry.get("shows_the_scene") is False:
                what = "imaginea nu arată ce cere scena"
            else:
                continue
            reason = _quote(entry.get("reason"))
            reading.failures.append(
                f"Scena {scene}: {what}" + (f" («{reason}»)." if reason else ".")
            )
            reading.scenes.setdefault(scene, ("picture", reason))

    integrity = checks.get("content_integrity_qc")
    if isinstance(integrity, Mapping):
        for entry in integrity.get("degenerate_stills") or []:
            if isinstance(entry, Mapping) and _scene_number(entry) is not None:
                scene = int(_scene_number(entry) or 0)
                reason = _quote(entry.get("reason"))
                reading.failures.append(f"Scena {scene}: imagine degenerată ({reason}).")
                reading.scenes[scene] = ("picture", reason)

    drift = checks.get("character_drift_qc")
    if _failed(drift):
        assert isinstance(drift, Mapping)
        reading.failures.append(
            "Personaje: "
            + (_quote(drift.get("detail")) or "aspectul personajelor s-a schimbat")
            + "."
        )
        for entry in drift.get("scenes") or []:
            if isinstance(entry, Mapping) and entry.get("passed") is False:
                scene = _scene_number(entry)
                if scene is not None:
                    reading.scenes.setdefault(scene, ("picture", _quote(entry.get("reason"))))

    motion = checks.get("motion_qc")
    if _failed(motion):
        assert isinstance(motion, Mapping)
        fallback, allowed = motion.get("fallback_scenes"), motion.get("max_fallback_scenes")
        if isinstance(fallback, int) and isinstance(allowed, int) and fallback > allowed:
            reading.failures.append(
                f"Mișcare: {fallback} scene fără mișcare din {motion.get('scenes')}, "
                f"peste maximul de {allowed}."
            )
        else:
            reading.failures.append(
                "Mișcare: " + (_quote(motion.get("warning")) or "controlul mișcării a picat") + "."
            )
        # motion_qc stores "scenes" as a count; only list values carry per-scene entries.
        listed = [motion.get(key) for key in ("clips", "scenes")]
        for entry in [item for value in listed if isinstance(value, list) for item in value]:
            if isinstance(entry, Mapping) and entry.get("passed") is False:
                scene = _scene_number(entry)
                if scene is not None:
                    reading.scenes.setdefault(scene, ("motion", _quote(entry.get("reason"))))

    factual = checks.get("factual_qc")
    if _failed(factual):
        assert isinstance(factual, Mapping)
        bad = [
            c
            for c in factual.get("claims") or []
            if isinstance(c, Mapping) and c.get("status") != "SUPPORTED"
        ]
        reading.failures.append(
            f"Afirmații: {len(bad)} neverificate; nu se repară cu credite, ci cu surse "
            "(de decis de Proprietar)."
        )
    for name, label in (("rights_qc", "Drepturi"), ("content_source_qc", "Sursa imaginii")):
        check = checks.get(name)
        if _failed(check):
            assert isinstance(check, Mapping)
            detail = _quote(check.get("detail") or check.get("license_status"))
            reading.failures.append(
                f"{label}: {detail or 'controlul a picat'} (de decis de Proprietar)."
            )
    for name in sorted(set(checks) - _KNOWN_CHECKS):
        check = checks[name]
        if _failed(check):
            assert isinstance(check, Mapping)
            detail = _quote(check.get("detail") or check.get("reason") or check.get("error"))
            reading.failures.append(
                f"Controlul «{name}» a picat" + (f": {detail}." if detail else ".")
            )
            for entry in check.get("scenes") or []:
                if isinstance(entry, Mapping) and entry.get("passed") is False:
                    scene = _scene_number(entry)
                    if scene is not None:
                        reading.scenes.setdefault(scene, ("picture", _quote(entry.get("reason"))))
    return reading


def _paid(
    redo: str,
    scene: int,
    row: Mapping[str, Any] | None,
    credit_usd: float | None,
    evidence: str,
) -> RedoProposal:
    key = "still_credits" if redo == "still" else "credits"
    raw = row.get(key) if row is not None else None
    credits = int(raw) if isinstance(raw, int | float) and not isinstance(raw, bool) else None
    if redo == "still":
        source = row.get("still_price_source") if row is not None else None
        model = None
        resolution = None
    else:
        source = row.get("price_source") if row is not None else None
        model = row.get("model_id") if row is not None else None
        resolution = row.get("resolution") if row is not None else None
    usd = (
        credits_to_micros(credits, credit_usd)
        if credits is not None and credit_usd is not None
        else None
    )
    return RedoProposal(
        redo=redo,
        scene_index=scene,
        reason=evidence,
        credits=credits,
        usd_micros=usd,
        price_source=str(source) if source else None,
        model_id=str(model) if model else None,
        resolution=str(resolution) if resolution else None,
    )


def redo_proposals(
    report: Any,
    *,
    sheet: Mapping[str, Any] | None = None,
    scene_kinds: Mapping[int, str] | None = None,
) -> list[RedoProposal]:
    """What to redo, per scene, priced from ``sheet`` when given. Never the whole film.

    A scene's kind comes from the sheet, else ``scene_kinds``, else what the failure's own
    evidence asked for. A card scene is recomposed for free; a LIVE scene whose picture failed
    needs a new still and new motion; a LIVE scene whose clip alone failed needs new motion.
    """
    reading = _read(_as_report(report))
    rows = _sheet_rows(sheet)
    kinds = {int(k): str(v) for k, v in (scene_kinds or {}).items()}
    credit_usd = _number((sheet or {}).get("credit_usd")) if isinstance(sheet, Mapping) else None
    proposals: list[RedoProposal] = []
    if reading.audio:
        proposals.append(
            RedoProposal(
                redo="audio",
                scene_index=None,
                reason=(
                    "Sunet: remasterizare din vocile deja înregistrate, cu limitator de vârf "
                    "(țintă −2,0 dBTP), fără a atinge imaginea."
                ),
                credits=0,
            )
        )
    for reason in reading.encode_reasons:
        proposals.append(RedoProposal(redo="encode", scene_index=None, reason=reason, credits=0))
    for scene in sorted(reading.scenes):
        need, evidence = reading.scenes[scene]
        kind = _kind_of(scene, evidence, rows, kinds)
        if kind in CARD_KINDS:
            proposals.append(
                RedoProposal(
                    redo="card",
                    scene_index=scene,
                    reason=f"Scena {scene}: {_CARD_WORDS[kind]}.",
                    credits=0,
                )
            )
            continue
        row = rows.get(scene)
        if need == "picture":
            proposals.append(_paid("still", scene, row, credit_usd, evidence))
        proposals.append(_paid("motion", scene, row, credit_usd, evidence))
    return proposals


def proposal_line(proposal: RedoProposal) -> str:
    """One proposal as the Owner reads it: the free fix in words, or the paid one priced."""
    if proposal.free:
        return proposal.reason
    scene = proposal.scene_index
    if proposal.redo == "still":
        what = f"Scena {scene}: imagine nouă"
    else:
        on = " ".join(x for x in (proposal.model_id, proposal.resolution) if x)
        what = f"Scena {scene}: mișcare nouă" + (f" pe {on}" if on else "")
    if proposal.credits is None:
        return f"{what}, preț necunoscut (fără foaia de filmare)."
    extra = [x for x in (_usd(proposal.usd_micros), proposal.price_source) if x]
    return (
        f"{what}, {ro_count(proposal.credits, 'credite')}"
        + (f" ({', '.join(extra)})" if extra else "")
        + "."
    )


def qc_summary_ro(
    report: Any,
    spend: Mapping[str, Any] | None,
    *,
    sheet: Mapping[str, Any] | None = None,
    scene_kinds: Mapping[int, str] | None = None,
) -> str:
    """The Owner's report: what failed, the credits measured, what is free and what is not.

    ``spend`` is ``production_json['credits_measured']`` (or None); only its balance deltas
    are read. ``sheet`` prices the scenes that need credits. Deterministic: the same inputs
    give the same text.
    """
    data = _as_report(report)
    reading = _read(data)
    status = str(data.get("status") or "")
    score = _number(data.get("score"))
    verdict = {"PASSED": "TRECUT", "FAILED": "PICAT"}.get(status, status or UNKNOWN)
    lines = [
        f"Controlul calității: {verdict}"
        + (f", scor {ro_number(score, 2)}" if score is not None else "")
        + f" (publicarea cere TRECUT și cel puțin {ro_number(PUBLISH_SCORE, 2)}).",
    ]
    if reading.failures:
        lines.append("Ce a picat:")
        lines.extend(f"- {line}" for line in reading.failures)
    else:
        lines.append("Ce a picat: nimic din ce s-a măsurat.")
    lines.append(_credits_line(spend))

    proposals = redo_proposals(data, sheet=sheet, scene_kinds=scene_kinds)
    free = [p for p in proposals if p.free]
    paid = [p for p in proposals if not p.free]
    lines += ["", FREE_HEADING, *([f"- {proposal_line(p)}" for p in free] or [NOTHING])]
    lines += ["", PAID_HEADING, *([f"- {proposal_line(p)}" for p in paid] or [NOTHING]), ""]
    priced = [p.credits for p in paid if p.credits is not None]
    unpriced = len(paid) - len(priced)
    total = sum(priced)
    micros = [p.usd_micros for p in paid if p.credits is not None]
    usd = _usd(sum(m for m in micros if m is not None)) if priced and None not in micros else None
    positions = f"{unpriced} {'poziție' if unpriced == 1 else 'poziții'} fără preț"
    if unpriced and not priced:
        # Nothing priced is not nothing to pay: the amount is unknown until a sheet prices it.
        amount = f"{UNKNOWN} ({positions})"
    else:
        amount = (
            ro_count(total, "credite")
            + (f" ({usd})" if usd else "")
            + (f", plus {positions}" if unpriced else "")
        )
    lines.append(f"De plătit: {amount}. Nicio scenă care a trecut nu se cumpără din nou.")
    return "\n".join(lines)
