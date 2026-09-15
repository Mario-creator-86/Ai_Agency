"""
Unreal Engine 5.8 editor script: the living street of the live headquarters.

Builds /Game/HQ/Seq_Traffic, a looping level sequence that drives the vehicles dress_hq_live.py
placed in the two lanes (actors labelled car_*) across the frame: the near lane towards +x, the far
lane towards -x, each at its own speed and moment in the loop, and a LevelSequenceActor that plays
it on start and loops forever, so the street moves in the streamed game without Blueprint or C++.

Timing is configuration, not code: AMN_TRAFFIC_LOOP (seconds, default 24) and AMN_TRAFFIC_SPEED
(metres per second, default 11). Vehicles wait off frame between passes.

  UnrealEditor-Cmd.exe AMNReference.uproject -run=pythonscript -script=traffic_hq_live.py
"""

import os

import unreal

LEVEL = "/Game/HQ/HQ_Dusk"
SEQ_PATH = "/Game/HQ"
SEQ_NAME = "Seq_Traffic"
FPS = 30
LOOP_S = float(os.environ.get("AMN_TRAFFIC_LOOP", "24"))
SPEED = float(os.environ.get("AMN_TRAFFIC_SPEED", "11")) * 100.0  # cm per second
# the frame is 57 m wide around x = 0; vehicles start and end this far outside it (cm)
EDGE = 3600.0


def log(msg):
    unreal.log(f"AMN_TRAFFIC {msg}")


def frames(seconds):
    return int(round(seconds * FPS))


def channels(section):
    """The section's channels by base name: Unreal suffixes each with its index ("Location.X_0")."""
    getter = getattr(section, "get_all_channels", None) or getattr(section, "get_channels")
    out = {}
    for ch in getter():
        name = str(ch.get_name())
        base, _, suffix = name.rpartition("_")
        out[base if base and suffix.isdigit() else name] = ch
    return out


def main():
    les = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
    if not les.load_level(LEVEL):
        raise RuntimeError(f"could not load {LEVEL}")
    eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    actors = eas.get_all_level_actors()
    cars = sorted((a for a in actors if a.get_actor_label().startswith("car_")), key=lambda a: a.get_actor_label())
    if not cars:
        log("no car_* actors: run dress_hq_live.py first")
        return
    for old in (a for a in actors if isinstance(a, unreal.LevelSequenceActor) and a.get_actor_label() == SEQ_NAME):
        eas.destroy_actor(old)

    asset_path = f"{SEQ_PATH}/{SEQ_NAME}"
    if unreal.EditorAssetLibrary.does_asset_exist(asset_path):
        unreal.EditorAssetLibrary.delete_asset(asset_path)
    seq = unreal.AssetToolsHelpers.get_asset_tools().create_asset(SEQ_NAME, SEQ_PATH, unreal.LevelSequence, unreal.LevelSequenceFactoryNew())
    seq.set_display_rate(unreal.FrameRate(FPS, 1))
    total = frames(LOOP_S)
    seq.set_playback_start(0)
    seq.set_playback_end(total)

    for i, car in enumerate(cars):
        car.static_mesh_component.set_mobility(unreal.ComponentMobility.MOVABLE)
        loc = car.get_actor_location()
        rot = car.get_actor_rotation()
        heading = 1.0 if abs(((rot.yaw % 360.0) + 360.0) % 360.0) < 90.0 or ((rot.yaw % 360.0) + 360.0) % 360.0 > 270.0 else -1.0
        is_bus = "vehicle10" in car.get_actor_label()
        speed = SPEED * (0.7 if is_bus else 1.0 + 0.12 * ((i % 3) - 1))
        travel = (2.0 * EDGE) / speed
        start_s = (LOOP_S / len(cars)) * i
        x0, x1 = -EDGE * heading, EDGE * heading
        binding = seq.add_possessable(car)
        track = binding.add_track(unreal.MovieScene3DTransformTrack)
        section = track.add_section()
        section.set_range(0, total)
        ch = channels(section)
        loc_x = next((c for n, c in ch.items() if n.endswith("Location.X")), None)
        if loc_x is None:
            log(f"no Location.X channel on {car.get_actor_label()}: {sorted(ch)}")
            continue
        for name, value in (("Location.Y", loc.y), ("Location.Z", loc.z), ("Rotation.Z", rot.yaw), ("Scale.X", car.get_actor_scale3d().x), ("Scale.Y", car.get_actor_scale3d().y), ("Scale.Z", car.get_actor_scale3d().z)):
            c = next((c for n, c in ch.items() if n.endswith(name)), None)
            if c is not None:
                c.set_default(value)
        # waiting off frame, one pass across, then waiting off frame on the other side until the loop ends
        t_in = frames(start_s)
        t_out = min(total, frames(start_s + travel))
        loc_x.add_key(unreal.FrameNumber(0), x0, interpolation=unreal.MovieSceneKeyInterpolation.CONSTANT)
        loc_x.add_key(unreal.FrameNumber(t_in), x0, interpolation=unreal.MovieSceneKeyInterpolation.LINEAR)
        loc_x.add_key(unreal.FrameNumber(t_out), x1, interpolation=unreal.MovieSceneKeyInterpolation.CONSTANT)
        log(f"{car.get_actor_label()}: heading {heading:+.0f}, {speed / 100.0:.1f} m/s, enters at {start_s:.1f}s, crosses in {travel:.1f}s")

    player = eas.spawn_actor_from_class(unreal.LevelSequenceActor, unreal.Vector(0.0, 0.0, 0.0))
    player.set_actor_label(SEQ_NAME)
    player.set_sequence(seq)
    settings = player.get_editor_property("playback_settings")
    settings.set_editor_property("auto_play", True)
    loop = settings.get_editor_property("loop_count")
    loop.set_editor_property("value", -1)
    settings.set_editor_property("loop_count", loop)
    player.set_editor_property("playback_settings", settings)

    unreal.EditorAssetLibrary.save_asset(asset_path)
    les.save_current_level()
    log(f"sequence {asset_path}: {len(cars)} vehicles, loop {LOOP_S:.0f}s, autoplay and looping")


main()
