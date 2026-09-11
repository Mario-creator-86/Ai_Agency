"""Smoke test: does the headless editor run our Python? Prints the engine version and
the plugins we rely on. Run:
  UnrealEditor-Cmd.exe AMNReference.uproject -run=pythonscript -script=smoke_test.py
"""
import unreal

unreal.log("AMN_UE_SMOKE version=%s" % unreal.SystemLibrary.get_engine_version())
unreal.log("AMN_UE_SMOKE project=%s" % unreal.Paths.project_dir())
unreal.log("AMN_UE_SMOKE ok")
