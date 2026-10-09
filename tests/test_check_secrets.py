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
import sys

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
def test_the_current_tree_passes_against_the_reviewed_baseline():
    # Exercise the shipped CLI, including its file-reading mode, as CI does.
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts/check_secrets.py")],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_the_cli_detects_a_key_in_utf8_text_with_windows_default_encoding(tmp_path):
    root = tmp_path / "tree"
    (root / "scripts").mkdir(parents=True)
    script = root / "scripts/check_secrets.py"
    shutil.copy2(ROOT / "scripts/check_secrets.py", script)
    (root / ".secrets.baseline").write_text('{"results": {}}', encoding="utf-8")
    key = fake_key()
    # The closing quote's UTF-8 bytes cannot be read as Windows cp1252. A scanner that
    # silently treats this text file as binary misses the credential on its next line.
    (root / "settings.py").write_text(
        f'# Diacritice și citat ”\napi_key = "{key}"\n', encoding="utf-8"
    )
    result = subprocess.run(
        [sys.executable, "-X", "utf8=0", str(script)],
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
        check=False,
    )
    assert result.returncode == 1, result.stdout + result.stderr
    assert "settings.py:2" in result.stdout
    assert key not in result.stdout + result.stderr


def test_the_workers_mirror_pin_passes_as_a_commit_line_only(tmp_path, capsys):
    # backend/runpod_worker/mirrors.lock.json pins his mirror by a 40-hex commit after the copy
    # (2026-10-09). That commit is not a credential, exactly like models.lock.json's pins.
    root = tmp_path / "tree"
    folder = root / "backend" / "runpod_worker"
    folder.mkdir(parents=True)
    commit = secrets.token_hex(20)
    lock = folder / "mirrors.lock.json"
    lock.write_text(
        '{\n  "stills": {\n    "repo": "mario/amn-stills",\n'
        f'    "revision": "{commit}",\n    "visibility": "private"\n  }}\n}}\n',
        encoding="utf-8",
    )
    assert run_gate(root, empty_baseline(tmp_path), capsys)[0] == 0

    # A key on another line of the same file is still caught.
    lock.write_text(lock.read_text(encoding="utf-8") + f'"token": "{fake_key()}"\n', "utf-8")
    code, output = run_gate(root, empty_baseline(tmp_path), capsys)
    assert code == 1 and "mirrors.lock.json" in output


def test_public_pixel_content_hashes_pass_but_credentials_and_other_fields_do_not(tmp_path, capsys):
    root = tmp_path / "tree"
    folder = root / "config"
    folder.mkdir(parents=True)
    manifest = folder / "pixel_actors.json"
    digest = secrets.token_hex(32)
    manifest.write_text('{\n  "sha256": "' + digest + '"\n}\n', encoding="utf-8")
    assert run_gate(root, empty_baseline(tmp_path), capsys)[0] == 0
    manifest.write_text(
        '{\n  "sha256": "' + digest + '",\n  "token": "' + fake_key() + '"\n}\n', encoding="utf-8"
    )
    code, output = run_gate(root, empty_baseline(tmp_path), capsys)
    assert code == 1 and "pixel_actors.json:3" in output
    manifest.write_text('{\n  "token": "' + digest + '"\n}\n', encoding="utf-8")
    assert run_gate(root, empty_baseline(tmp_path), capsys)[0] == 1
