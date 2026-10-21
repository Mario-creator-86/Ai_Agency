"""Cold sheet reads measure independent local clips concurrently, without changing facts."""

from threading import Barrier
from types import SimpleNamespace

from app.media import shooting_sheet


def test_clip_measurements_use_bounded_parallelism_and_measure_each_content_once(monkeypatch):
    barrier = Barrier(4, timeout=5)
    seen = []

    def measure(take):
        seen.append(take.sha256)
        barrier.wait()
        return 5.0

    monkeypatch.setattr(shooting_sheet, "shot_clip_seconds", measure, raising=False)
    takes = [
        SimpleNamespace(kind="motion", status="PAID", sha256=str(i)) for i in range(4)
    ]
    shooting_sheet._warm_shot_durations([*takes, takes[0]], workers=4)
    assert sorted(seen) == ["0", "1", "2", "3"]
