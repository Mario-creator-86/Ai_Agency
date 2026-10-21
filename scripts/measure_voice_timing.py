"""Print every voice's measured pauses and speech rate, and cross-check them with the meter.

The studio's pauses («pauza vocii», the Owner's decision of 2026-10-16) come from each voice's
own kept takes: `app.media.pauses.load_profiles` reads the vendor's character ``alignment`` in
every kept PAID narration sidecar (<media_root>/<film>/narration/*.json; never the
``normalized_alignment``) and `voice_profile` resolves each voice from its own takes, its pool's
or the fallback in config/pause_rules.json. This prints what the studio will time a film by,
and, unless ``--no-meter``, measures the same takes' sentence pauses with FFmpeg's silencedetect
(-45 dB) to show how far the vendor's clock is from the silence actually heard.

It reads only. Nothing is bought, no model or vendor is called, and the derived cache
(``voice_pause_profiles.json`` beside the films) is written only with ``--write-cache``.

Usage::

    uv run python scripts/measure_voice_timing.py
    uv run python scripts/measure_voice_timing.py --media-root "D:/films" --no-meter
    uv run python scripts/measure_voice_timing.py --json
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.media import pauses  # noqa: E402
from app.media.toolchain import SILENCE_THRESHOLD_DB, find_ffmpeg, silence_spans  # noqa: E402

#: The meter's shortest silence inside a take, as the 2026-10-16 measurement read it.
METER_MIN_SECONDS = 0.08
#: How far either side of the vendor's gap a measured silence may lie and still belong to it.
METER_REACH_SECONDS = 0.1


def _fmt(stat: dict[str, Any] | pauses.Stat | None) -> str:
    if stat is None:
        return "-"
    if isinstance(stat, pauses.Stat):
        return f"{stat.median:.3f} [{stat.p25:.3f}] n={stat.n} ({stat.source})"
    if not stat.get("n"):
        return "-"
    return f"{stat['median']:.3f} [{stat['p25']:.3f}] n={stat['n']}"


def meter_check(paths: Sequence[Path], ffmpeg: str) -> dict[str, dict[str, list[float]]]:
    """Per voice, the sentence pauses on the vendor's clock and as the meter hears them, and
    the silence the meter hears after each take's last letter."""
    found: dict[str, dict[str, list[float]]] = {}
    for path in paths:
        audio = path.with_name(path.name[: -len(".json")])
        try:
            sidecar = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        raw = sidecar.get("raw_response") if isinstance(sidecar, dict) else None
        alignment = pauses.alignment_of(raw)
        if alignment is None or not audio.is_file() or not isinstance(raw, dict):
            continue
        key = pauses.profile_key(raw.get("provider"), raw.get("model"), raw.get("voice_id"))
        silences = silence_spans(
            ffmpeg, audio, threshold_db=SILENCE_THRESHOLD_DB, min_seconds=METER_MIN_SECONDS
        )
        if key is None or silences is None:
            continue
        tokens = pauses.alignment_tokens(alignment)
        entry = found.setdefault(str(key), {"vendor": [], "meter": [], "tail": []})
        for before, after in zip(tokens, tokens[1:], strict=False):
            if pauses.punctuation_class(before.text) != pauses.SENTENCE:
                continue
            low, high = before.end - METER_REACH_SECONDS, after.start + METER_REACH_SECONDS
            heard = sum(
                min(end, high) - max(start, low)
                for start, end in silences
                if min(end, high) > max(start, low)
            )
            entry["vendor"].append(max(0.0, after.start - before.end))
            entry["meter"].append(max(0.0, heard))
        if tokens:
            last = tokens[-1].end
            entry["tail"].append(
                sum(end - max(start, last) for start, end in silences if end > last)
            )
    return found


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--media-root", type=Path, default=None, help="the films' folder")
    parser.add_argument("--no-meter", action="store_true", help="skip the FFmpeg cross-check")
    parser.add_argument("--write-cache", action="store_true", help="write the derived cache")
    parser.add_argument("--json", action="store_true", help="print the profiles as JSON")
    args = parser.parse_args(argv)

    rules = pauses.load_rules()
    if args.media_root is None:
        from app.media.disk import media_root  # noqa: PLC0415

        args.media_root = media_root()
    root = Path(args.media_root)
    profiles = pauses.load_profiles(root, rules=rules, write=args.write_cache)
    if args.json:
        print(json.dumps(profiles, ensure_ascii=False, indent=1, sort_keys=True))
        return 0

    print(f"Media root: {root}")
    print(f"Kept takes measured: {profiles['takes']} (rules v{rules.version}, {rules.status})")
    for pool, summary in profiles["pools"].items():
        classes = summary["classes"]
        print(
            f"  pool {pool:9s} takes={summary['takes']:3d}  sentence {_fmt(classes['SENTENCE'])}"
            f"  s/word {summary['rate']['seconds_per_word']}"
        )
    print()
    print("Each voice as a film is timed by it (own >= min_samples, else pool, else config):")
    for key, measured in sorted(profiles["voices"].items()):
        voice = pauses.voice_profile(key, rules=rules, profiles=profiles)
        print(
            f"- {key}  ({measured['pool']}, {measured['takes']} takes, {measured['words']} words)"
        )
        print(f"    sentence {_fmt(voice.sentence)}")
        print(f"    clause   {_fmt(voice.clause)}")
        print(f"    dash     {_fmt(voice.dash)}")
        print(
            f"    speech   {voice.seconds_per_word:.3f} s/word median, "
            f"{voice.seconds_per_word_high:.3f} high ({voice.rate_source})"
        )

    if args.no_meter:
        return 0
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        print("\nFFmpeg not found: no cross-check with the meter.")
        return 0
    print(f"\nCross-check with the meter (silencedetect {SILENCE_THRESHOLD_DB:.0f} dB):")
    for key, entry in sorted(meter_check(pauses.narration_sidecars(root), ffmpeg).items()):
        if not entry["vendor"]:
            continue
        differences = [abs(a - b) for a, b in zip(entry["vendor"], entry["meter"], strict=True)]
        tail = statistics.median(entry["tail"]) if entry["tail"] else 0.0
        print(
            f"- {key}: sentence pause vendor {statistics.median(entry['vendor']):.3f} s, "
            f"meter {statistics.median(entry['meter']):.3f} s, median |diff| "
            f"{statistics.median(differences):.3f} s (n={len(differences)}); silence after the "
            f"last letter {tail:.3f} s"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
