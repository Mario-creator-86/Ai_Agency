"""The suite's lanes and its strict switch, kept apart from conftest.py so a test can load
exactly these hooks into an inner pytest run.

Lanes. A test that skips without FFmpeg (or the YuNet face model) is a *film* test; every film
test, and every test in SLOW_MODULES, is *slow*. ``pytest -m "not slow"`` is the quick lane.

STUDIO_REQUIRE_FFMPEG=1. About 25 test files skip when FFmpeg, its subtitles filter or the
YuNet model is missing. That is right on a buyer's laptop without an encoder, and wrong on CI:
a runner without FFmpeg would leave the whole film pipeline untested behind a green run. CI
sets the variable, so there a missing tool is a red run that names it.
"""

from __future__ import annotations

import os
import re

import pytest

REQUIRE_TOOLS_ENV = "STUDIO_REQUIRE_FFMPEG"
#: Skip reasons that mean "a film tool is missing", as the suite words them.
TOOL_SKIP = re.compile(r"ffmpeg|ffprobe|yunet|subtitles filter|a day cannot be filmed", re.I)
#: Modules slow for reasons other than a skip marker: measured with --durations on 2026-10-01
#: (the six end-to-end days alone took 491 s of a 1,717 s run).
SLOW_MODULES = frozenset(
    {
        "test_autonomous_day_end_to_end.py",
        "test_film_dry_run.py",
        "test_sheet_assemble.py",
        "test_nepal_rehearsal.py",
        "test_rehearsal_on_a_copy.py",
        "test_encode_spec.py",
    }
)


def tools_required() -> bool:
    return os.environ.get(REQUIRE_TOOLS_ENV, "").strip() == "1"


def _is_film_test(item: pytest.Item) -> bool:
    for marker in item.iter_markers("skipif"):
        reason = str(marker.kwargs.get("reason", ""))
        if TOOL_SKIP.search(reason):
            return True
    return False


def mark_lanes(items: list[pytest.Item]) -> None:
    for item in items:
        film = _is_film_test(item)
        if film:
            item.add_marker(pytest.mark.film)
        if film or item.path.name in SLOW_MODULES:
            item.add_marker(pytest.mark.slow)


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    mark_lanes(items)


def _skip_reason(report: pytest.TestReport) -> str:
    longrepr = report.longrepr
    if isinstance(longrepr, tuple) and len(longrepr) == 3:
        return str(longrepr[2])
    return str(longrepr or "")


@pytest.hookimpl(wrapper=True)
def pytest_runtest_makereport(item: pytest.Item, call: pytest.CallInfo[None]):  # type: ignore[no-untyped-def]
    report = yield
    if report.skipped and not hasattr(report, "wasxfail") and tools_required():
        reason = _skip_reason(report)
        if TOOL_SKIP.search(reason):
            report.outcome = "failed"
            report.longrepr = (
                f"{reason.removeprefix('Skipped: ')} - and {REQUIRE_TOOLS_ENV}=1 requires it: "
                "install FFmpeg (with libass) and keep the YuNet model in backend/app/media/models"
            )
    return report
