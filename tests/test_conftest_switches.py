"""The suite's own switches.

1. STUDIO_REQUIRE_FFMPEG=1 (set in CI): a test that would skip because FFmpeg or the YuNet face
   model is missing fails instead, so a runner without them cannot leave the film pipeline
   untested behind a green run (tests/suite_switches.py).
2. The quick final encode: outside the encode spec and the one end-to-end day kept on the real
   profile, the film's final encode runs x264 on the veryfast preset instead of slow. Everything
   else in the delivery spec stays (High profile, CRF 17, the 14 Mbps cap, BT.709, faststart),
   so quality control measures the same kind of file it measures in production.
"""

from pathlib import Path

import pytest

FILM_TESTS = """
import pytest

def find_ffmpeg():
    return None  # this machine has no encoder

requires_ffmpeg = pytest.mark.skipif(find_ffmpeg() is None, reason="ffmpeg not installed")
requires_yunet = pytest.mark.skipif(True, reason="YuNet is not installed")

@requires_ffmpeg
def test_a_film_is_encoded():
    pass

@requires_yunet
def test_faces_are_counted():
    pass

def test_inline_skip_in_the_body():
    pytest.skip("no FFmpeg on this machine")

@pytest.mark.skipif(True, reason="needs the Owner's database copy")
def test_an_opt_in_test():
    pass
"""


@pytest.fixture
def film_suite(pytester):
    # The inner run loads only the switches, not the studio's fixtures.
    pytester.makeconftest(
        "from suite_switches import (  # noqa: F401\n"
        "    pytest_collection_modifyitems,\n"
        "    pytest_runtest_makereport,\n"
        ")\n"
    )
    pytester.makepyfile(test_film=FILM_TESTS)
    return pytester


def test_without_the_switch_a_missing_encoder_skips(film_suite, monkeypatch):
    monkeypatch.delenv("STUDIO_REQUIRE_FFMPEG", raising=False)
    result = film_suite.runpytest_inprocess("-p", "no:cacheprovider")
    result.assert_outcomes(skipped=4)


def test_with_the_switch_a_missing_encoder_or_face_model_fails(film_suite, monkeypatch):
    monkeypatch.setenv("STUDIO_REQUIRE_FFMPEG", "1")
    result = film_suite.runpytest_inprocess("-p", "no:cacheprovider")
    # A skip marker is judged while the test is set up, so its failure is reported as an
    # error; the skip inside the body fails the test itself. The opt-in test still skips.
    result.assert_outcomes(errors=2, failed=1, skipped=1)
    result.stdout.fnmatch_lines(["*STUDIO_REQUIRE_FFMPEG=1 requires it*"])


def _preset(args: list[str]) -> str:
    return args[args.index("-preset") + 1]


def test_a_film_test_encodes_its_final_on_the_quick_preset_and_the_same_spec():
    from app.media import assembler

    args = assembler.final_video_args(24)
    assert _preset(args) == "veryfast"
    for flag, value in (("-crf", "17"), ("-profile:v", "high"), ("-maxrate", "14M")):
        assert args[args.index(flag) + 1] == value
    assert "+faststart" in args


@pytest.mark.real_encode
def test_a_test_marked_real_encode_keeps_the_production_profile():
    from app.media import assembler

    assert _preset(assembler.final_video_args(24)) == "slow"


def test_the_encode_spec_and_one_end_to_end_day_keep_the_real_profile():
    import conftest

    assert "test_encode_spec.py" in conftest.REAL_ENCODE_MODULES
    day = Path(__file__).with_name("test_autonomous_day_end_to_end.py").read_text("utf-8")
    assert day.count("@pytest.mark.real_encode") == 1


def test_the_quick_lane_leaves_out_film_tests(film_suite, monkeypatch):
    # A test that skips without FFmpeg or YuNet is a film test, and every film test is slow.
    monkeypatch.delenv("STUDIO_REQUIRE_FFMPEG", raising=False)
    result = film_suite.runpytest_inprocess("-p", "no:cacheprovider", "-m", "not slow")
    result.assert_outcomes(skipped=2, deselected=2)
    film = film_suite.runpytest_inprocess("-p", "no:cacheprovider", "-m", "film")
    film.assert_outcomes(skipped=2, deselected=2)
