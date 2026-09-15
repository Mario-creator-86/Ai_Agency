"""
Runs rig_employees.py inside the full editor, unattended, and closes the editor when it is done.

The MetaHuman build bakes groom textures with TextureGraph, which crashes (access violation) when
it runs before the engine has ticked: in a commandlet (frame 0) it fails with or without
-AllowCommandletRendering, while the same build from an open editor's Cmd box works. So this waits
for the editor to draw a few hundred frames, then runs the rigging script and quits:

  UnrealEditor.exe AMNReference.uproject -ExecCmds="py <this file>"

(Not -ExecutePythonScript: that closes the editor as soon as this file returns, before any tick.)

The Owner's Epic login must already be remembered (one run from a Launcher-opened editor). Stop
the live stream first: a build needs several GB and ran out of memory beside the streamed game.
"""

import os
import traceback

import unreal

HERE = os.path.dirname(os.path.abspath(__file__))
WARMUP_TICKS = int(os.environ.get("AMN_WARMUP_TICKS", "300"))
_state = {"ticks": 0, "handle": None}


def _run():
    script = os.path.join(HERE, "rig_employees.py")
    try:
        exec(compile(open(script, "r", encoding="utf-8").read(), script, "exec"),
             {"__file__": script, "__name__": "__main__"})
        unreal.log("AMN_PEOPLE editor run finished")
    except Exception:
        unreal.log_error("AMN_PEOPLE editor run failed\n" + traceback.format_exc())
    finally:
        unreal.SystemLibrary.quit_editor()


def _tick(_delta):
    _state["ticks"] += 1
    if _state["ticks"] < WARMUP_TICKS:
        return
    unreal.unregister_slate_post_tick_callback(_state["handle"])
    _run()


_state["handle"] = unreal.register_slate_post_tick_callback(_tick)
unreal.log(f"AMN_PEOPLE waiting {WARMUP_TICKS} editor ticks before rigging")
