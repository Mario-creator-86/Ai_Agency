"""The secret scan guards something: green on the reviewed tree, red on a new key.

Measured 2026-10-01: the scan failed on every tree it was run on (about 780 locations in the
Owner's tree, 43 in a fresh clone), all of them reviewed non-secrets - pinned SHA-256 digests,
AWS's documented example key, Unreal asset paths, test fixtures - and it walked gitignored
folders (.claude/worktrees, the Unreal content inventory). A real key would have drowned in
that noise. The scan now reads what git would ship (tracked plus untracked, not ignored),
compares against a reviewed baseline and fails only on what the baseline does not list.

Every key here is built at run time from random characters: none is a credential and none is
written into this file, so this file itself does not trip the scan.
"""

import importlib.util
import json
import secrets
import shutil
import string
import subprocess

import pytest
from app.config import ROOT

spec = importlib.util.spec_from_file_location("check_secrets", ROOT / "scripts/check_secrets.py")
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)


def fake_key() -> str:
    alphabet = string.ascii_letters + string.digits
    return "sk-" + "".join(secrets.choice(alphabet) for _ in range(40))


def empty_baseline(folder):
    path = folder / "baseline.json"
    path.write_text(json.dumps({"results": {}}), encoding="utf-8")
    return path


def run_gate(root, baseline, capsys, *extra):
    code = gate.main(["--baseline", str(baseline), *extra], root=root)
    captured = capsys.readouterr()
    return code, captured.out + captured.err


def test_a_new_key_fails_the_gate_and_only_its_location_is_printed(tmp_path, capsys):
    root = tmp_path / "tree"
    root.mkdir()
    key = fake_key()
    (root / "settings.py").write_text(f'api_key = "{key}"\n', encoding="utf-8")
    (root / "clean.py").write_text('greeting = "bună ziua"\n', encoding="utf-8")

    code, output = run_gate(root, empty_baseline(tmp_path), capsys)

    assert code == 1
    assert "settings.py:1" in output
    assert "clean.py" not in output
    assert key not in output and key[3:] not in output


@pytest.mark.parametrize("name", ["deploy.ps1", "probe.mjs", "notes.txt", "build.cmd", "a.yaml"])
def test_scripts_and_text_files_the_old_scan_skipped_are_scanned(tmp_path, capsys, name):
    root = tmp_path / "tree"
    root.mkdir()
    (root / name).write_text(f'api_key = "{fake_key()}"\n', encoding="utf-8")

    code, output = run_gate(root, empty_baseline(tmp_path), capsys)

    assert code == 1 and f"{name}:1" in output


def test_a_reviewed_line_marked_allowlisted_passes(tmp_path, capsys):
    root = tmp_path / "tree"
    root.mkdir()
    (root / "fixture.py").write_text(
        f'api_key = "{fake_key()}"  # pragma: allowlist secret\n', encoding="utf-8"
    )

    code, _ = run_gate(root, empty_baseline(tmp_path), capsys)

    assert code == 0


def test_a_baselined_value_passes_where_it_moved_but_not_in_another_file(tmp_path, capsys):
    root = tmp_path / "tree"
    root.mkdir()
    key = fake_key()
    (root / "fixture.py").write_text(f'api_key = "{key}"\n', encoding="utf-8")
    baseline = tmp_path / "baseline.json"
    assert gate.main(["--baseline", str(baseline), "--write-baseline"], root=root) == 0
    capsys.readouterr()
    written = json.loads(baseline.read_text(encoding="utf-8"))
    assert key not in json.dumps(written)  # only the hash is kept, never the value
    assert list(written["results"]) == ["fixture.py"]

    # The reviewed line moves down: still the reviewed value, still green.
    (root / "fixture.py").write_text(f'\n\n# moved\napi_key = "{key}"\n', encoding="utf-8")
    assert run_gate(root, baseline, capsys)[0] == 0

    # The same value appearing in another file was never reviewed there.
    (root / "other.py").write_text(f'api_key = "{key}"\n', encoding="utf-8")
    code, output = run_gate(root, baseline, capsys)
    assert code == 1 and "other.py:1" in output and "fixture.py" not in output


def test_local_secrets_and_generated_folders_are_never_read(tmp_path, capsys):
    root = tmp_path / "tree"
    for folder in ("data", ".claude/worktrees/x", "node_modules/pkg", ".venv/lib"):
        (root / folder).mkdir(parents=True)
        (root / folder / "leak.py").write_text(f'api_key = "{fake_key()}"\n', encoding="utf-8")
    (root / ".env").write_text(f"API_KEY={fake_key()}\n", encoding="utf-8")
    (root / "studio.credentials.key").write_text(fake_key(), encoding="utf-8")

    code, output = run_gate(root, empty_baseline(tmp_path), capsys)

    assert code == 0, output
    assert gate.candidate_files(root) == []


@pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")
def test_in_a_git_tree_only_what_git_would_ship_is_scanned(tmp_path, capsys):
    root = tmp_path / "repo"
    root.mkdir()
    # A throwaway repository in the test's own folder; nothing is committed anywhere.
    subprocess.run(["git", "init", "-q", str(root)], check=True, stdin=subprocess.DEVNULL)
    (root / ".gitignore").write_text("generated/\n", encoding="utf-8")
    (root / "generated").mkdir()
    (root / "generated" / "inventory.py").write_text(
        f'api_key = "{fake_key()}"\n', encoding="utf-8"
    )
    (root / "clean.py").write_text("value = 1\n", encoding="utf-8")

    assert [p.name for p in gate.candidate_files(root)] == [".gitignore", "clean.py"]
    assert run_gate(root, empty_baseline(tmp_path), capsys)[0] == 0

    # A new file nobody has added yet is still in the tree that would ship.
    (root / "new_module.py").write_text(f'api_key = "{fake_key()}"\n', encoding="utf-8")
    code, output = run_gate(root, empty_baseline(tmp_path), capsys)
    assert code == 1 and "new_module.py:1" in output


@pytest.mark.slow
def test_the_current_tree_passes_against_the_reviewed_baseline(capsys):
    code = gate.main([])
    output = capsys.readouterr().out
    assert code == 0, output
