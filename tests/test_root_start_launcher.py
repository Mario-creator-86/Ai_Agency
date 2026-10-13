"""The old root command delegates to the pinned launcher without starting production."""

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def launcher():
    spec = importlib.util.spec_from_file_location("root_start_compat", ROOT / "start.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_arguments_cwd_and_failure_code_are_preserved(launcher, monkeypatch, tmp_path):
    calls = []
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(launcher.shutil, "which", lambda _: "uv-test.exe")

    def spawn(command, *, cwd):
        calls.append((command, cwd))
        return SimpleNamespace(wait=lambda: 7)

    monkeypatch.setattr(launcher.subprocess, "Popen", spawn)
    args = ["--demo", "--demo-dir", str(tmp_path / "a folder"), "--no-graphics"]
    assert launcher.main(args) == 7
    assert calls == [
        (["uv-test.exe", "run", "--locked", "python", str(ROOT / "scripts/start.py"), *args], ROOT)
    ]


def test_ctrl_c_waits_for_launcher_instead_of_killing_it(launcher, monkeypatch):
    waits = []
    monkeypatch.setattr(launcher.shutil, "which", lambda _: "uv-test.exe")

    def wait():
        waits.append(True)
        if len(waits) == 1:
            raise KeyboardInterrupt
        return 0

    monkeypatch.setattr(launcher.subprocess, "Popen", lambda *a, **kw: SimpleNamespace(wait=wait))
    assert launcher.main([]) == 0
    assert len(waits) == 2


def test_missing_uv_does_not_fall_back_to_the_global_runtime(launcher, monkeypatch, capsys):
    monkeypatch.setattr(launcher.shutil, "which", lambda _: None)
    assert launcher.main([]) == 1
    assert "PATH" in capsys.readouterr().err


def test_spawn_error_is_reported(launcher, monkeypatch, capsys):
    monkeypatch.setattr(launcher.shutil, "which", lambda _: "uv-test.exe")

    def refused(*args, **kwargs):
        raise OSError("test spawn failure")

    monkeypatch.setattr(launcher.subprocess, "Popen", refused)
    assert launcher.main([]) == 1
    assert "test spawn failure" in capsys.readouterr().err
