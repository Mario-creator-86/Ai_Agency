"""scripts/check_all.py: the README chain, run so that it never hurts the Owner's shared PC.

Nothing here runs the chain: the machine checks and the plan are tested with stand-ins for
the process list and the free commit.
"""

import datetime as dt
import importlib.util
import sys

from app.config import ROOT

spec = importlib.util.spec_from_file_location("check_all", ROOT / "scripts/check_all.py")
check_all = importlib.util.module_from_spec(spec)
sys.modules["check_all"] = check_all
spec.loader.exec_module(check_all)


def test_the_owners_games_are_recognised_by_their_process_names():
    names = ["explorer.exe", "PathOfExileSteam.exe", "LeagueClientUx.exe", "League of Legends.exe"]
    assert check_all.games_running(names) == [
        "League of Legends.exe",
        "LeagueClientUx.exe",
        "PathOfExileSteam.exe",
    ]
    assert check_all.games_running(["python.exe", "UnrealEditor.exe", "node.exe"]) == []


def test_it_refuses_while_a_game_runs_or_under_16_gb_of_free_commit():
    def no_games():
        return ["python.exe"]

    def plenty():
        return 30.5

    assert check_all.machine_refusal(16, free_gb=plenty, processes=no_games) is None

    low = check_all.machine_refusal(16, free_gb=lambda: 9.8, processes=no_games)
    assert low and "9.8 GB" in low and "16 GB" in low

    game = check_all.machine_refusal(16, free_gb=plenty, processes=lambda: ["PathOfExile.exe"])
    assert game and "PathOfExile.exe" in game


def test_the_plan_runs_pytest_at_idle_priority_and_builds_the_page_outside_dist(
    monkeypatch, capsys, tmp_path
):
    monkeypatch.setattr(check_all, "machine_refusal", lambda *a, **k: None)
    assert check_all.main(["--dry-run", "--quick"]) == 0
    printed = capsys.readouterr().out.splitlines()
    names = [line.split(":", 1)[0] for line in printed]
    assert names == [
        "check_docs",
        "check_secrets",
        "ruff",
        "ruff format",
        "mypy",
        "pytest (Idle priority)",
        "page check",
        "page tests",
        "page build",
    ]
    pytest_line = next(line for line in printed if line.startswith("pytest"))
    assert "--basetemp=.pytest_cache/basetemp_check_all" in pytest_line
    assert "-m not slow" in pytest_line
    build = next(line for line in printed if line.startswith("page build"))
    assert "--outDir" in build and "dist" not in build.split("--outDir", 1)[1].split()[0]


def test_it_will_not_start_on_a_busy_machine(monkeypatch, capsys):
    monkeypatch.setattr(check_all, "machine_refusal", lambda *a, **k: "a game is running (x)")
    assert check_all.main(["--dry-run"]) == 2
    assert "will not start" in capsys.readouterr().out


def test_pytest_is_checked_again_right_before_it_starts(monkeypatch):
    calls = []
    monkeypatch.setattr(check_all, "machine_refusal", lambda *a, **k: calls.append(1) or "busy")
    args = check_all.argparse.Namespace(quick=False, basetemp="b", min_free_gb=16.0, dry_run=False)
    step = next(s for s in check_all.plan(args, ROOT) if s.name == "pytest")
    outcome = check_all.run_step(step)
    assert calls and outcome.refused == "busy" and not outcome.passed


def test_one_dated_line_records_the_result():
    outcomes = [
        check_all.Outcome("check_docs", 0, 0.4),
        check_all.Outcome("pytest", 1, 1717.5, summary="4 failed, 2550 passed, 6 skipped"),
    ]
    line = check_all.status_line(outcomes, when=dt.datetime(2026, 10, 2, 9, 30), quick=False)
    assert line.startswith("2026-10-02 09:30 check_all FAIL, full suite: ")
    assert "pytest FAILED (exit 1): 4 failed, 2550 passed, 6 skipped in 1718 s" in line
    assert "\n" not in line

    passed = check_all.status_line(outcomes[:1], when=dt.datetime(2026, 10, 2), quick=True)
    assert "check_all PASS, quick lane" in passed
