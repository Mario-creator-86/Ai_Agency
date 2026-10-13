"""
Unreal Engine 5.8 editor script (PREPARED 2026-09-24, NEVER RUN YET): the "BUCHAREST AI DISTRICT"
letters come out in front of their board, in place on the saved level, with the stream stopped.

What the frames show (rebuild_2c: old_0, build3_0, every preview instant, the same before and after
the real-sky rebuild): the letters are cut by two diagonal wedges of the board, "BUCHA.." on the first
line and "..ISTRICT" on the second. The letters are their own mesh (billboard_text_mesh, Blender
y 29.50 m), the lit board is a quad of the merged skyline mesh 5 cm behind them (y 29.55), and its
frame box 5 cm further (29.60-29.90). hq_city.build_city puts them there. The skyline is one Nanite
mesh 60 x 56 x 39 m: seen from 246 m in the orthographic plate camera, a 5 cm step in depth moves
nothing on screen, so Nanite's simplification may fold the board's two triangles and the frame's
front together and tilt them through the letters. That cause is a hypothesis (not measured): the
triangle-shaped cut is what a folded quad would give. This pass does not depend on it: the letters
move AMN_SIGN_FORWARD_CM (default 30, six times the old gap) towards the camera, along the camera's
own view line, so they stay on the same pixels (an orthographic camera does not scale with depth).

The first run records the letters' built location in sign_baseline.json (beside this file), so a
rerun is absolute; AMN_SIGN_FORWARD_CM=0 puts them back. The other test, which names the cause, is
the existing nanite_hq_live.py with AMN_NANITE_OFF="glow_details,skyline" (see the window brief).
"""

import json
import os

import unreal

HERE = os.path.dirname(os.path.abspath(__file__))
LEVEL = "/Game/HQ/HQ_Dusk"
LABEL = os.environ.get("AMN_SIGN_LABEL", "billboard_text_mesh")
CAMERA = "PlateCam"
FORWARD_CM = float(os.environ.get("AMN_SIGN_FORWARD_CM", "30"))
BASELINE = os.path.join(HERE, "sign_baseline.json")


def log(msg):
    unreal.log(f"AMN_SIGN {msg}")


def main():
    les = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
    if not les.load_level(LEVEL):
        raise RuntimeError(f"could not load {LEVEL}")
    eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    actors = {a.get_actor_label(): a for a in eas.get_all_level_actors()}
    sign, cam = actors.get(LABEL), actors.get(CAMERA)
    if sign is None or cam is None:
        raise RuntimeError(f"missing actor: {LABEL if sign is None else CAMERA}")
    base = json.load(open(BASELINE, "r", encoding="utf-8")) if os.path.exists(BASELINE) else {}
    if LEVEL not in base:
        loc = sign.get_actor_location()
        base[LEVEL] = [loc.x, loc.y, loc.z]
        with open(BASELINE, "w", encoding="utf-8") as fh:
            json.dump(base, fh, indent=1)
    x, y, z = base[LEVEL]
    forward = cam.get_actor_forward_vector()  # where the camera looks; towards it is the opposite
    target = unreal.Vector(x - forward.x * FORWARD_CM, y - forward.y * FORWARD_CM, z - forward.z * FORWARD_CM)
    sign.set_actor_location(target, False, False)
    log(f"{LABEL}: built at ({x:.1f}, {y:.1f}, {z:.1f}), now {FORWARD_CM:g} cm towards {CAMERA} "
        f"(camera forward {forward.x:.3f}, {forward.y:.3f}, {forward.z:.3f}) at ({target.x:.1f}, {target.y:.1f}, {target.z:.1f})")
    les.save_current_level()
    log("saved")


main()
