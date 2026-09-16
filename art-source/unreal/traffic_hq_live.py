"""
Unreal Engine 5.8 editor script: the living street of the live headquarters.

Builds /Game/HQ/Seq_Traffic, a looping level sequence that drives the vehicles dress_hq_live.py
placed in the two lanes (actors labelled car_*) across the frame: the near lane towards +x, the far
lane towards -x, each at its own speed and moment in the loop, and a LevelSequenceActor that plays
it on start and loops forever, so the street moves in the streamed game without Blueprint or C++.

No vehicle waits off frame any more. Every car is a conveyor: it crosses the frame a whole number of
times per loop, so the loop closes on itself, and the fleet's phases are spread evenly over one
crossing. Counted over a loop, one pass each and then parked at the edge put 1.88 vehicles on frame on
average, none at all for 2.2 % of the loop and fewer than three for 87.4 % of it - board_0 of
2026-09-16 caught one of those empty moments, and the picture always has four. Five conveyor cars put
4.31 on frame, never fewer than three and never none.

Timing is configuration, not code: AMN_TRAFFIC_LOOP (seconds, default 24) and AMN_TRAFFIC_PASSES
(crossings per loop, taken in turn across the fleet, default "4,3"; the bus takes its own,
AMN_TRAFFIC_BUS_PASSES). The speed follows from them rather than being set: a crossing is 2 x EDGE
long, so passes crossings in the loop is passes * 2 * EDGE / LOOP_S - 12 and 9 m/s for the cars, 6 for
the bus.

  UnrealEditor-Cmd.exe AMNReference.uproject -run=pythonscript -script=traffic_hq_live.py
"""

import os

import unreal

LEVEL = "/Game/HQ/HQ_Dusk"
SEQ_PATH = "/Game/HQ"
SEQ_NAME = "Seq_Traffic"
FPS = 30
LOOP_S = float(os.environ.get("AMN_TRAFFIC_LOOP", "24"))
# Crossings per loop, taken in turn across the fleet, and the bus's own. Whole numbers only: the
# sequence loops, so a car that had not finished a whole number of crossings would jump on the wrap.
PASSES = tuple(int(v) for v in os.environ.get("AMN_TRAFFIC_PASSES", "4,3").split(",") if v.strip())
BUS_PASSES = int(os.environ.get("AMN_TRAFFIC_BUS_PASSES", "2"))
# the frame is 57 m wide around x = 0; one crossing runs from this far outside it to this far outside
# it on the other side (cm), so a vehicle is on frame for 5700 / 7200 = 79 % of every crossing
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


def crossing_keys(total, passes, phase):
    """(frame, u) for one conveyor car over the loop: u runs 0 at the entry edge to 1 at the exit
    edge, `passes` whole crossings per loop, `phase` (0 to 1) of a crossing already made at frame 0.
    Each wrap is keyed twice, one frame apart, so the jump back to the entry edge costs a single frame
    and happens 7.5 m outside the frame, where nothing can see it. A wrap that lands on the loop's own
    last frame is kept: without it the car would stand still over its final crossing."""
    span = total / passes  # frames of one crossing
    keys = [(0, phase)]
    j = 1
    while True:
        f = span * (j - phase)  # the j-th wrap, in frames
        if f > total + 0.5:
            break
        wrap = int(round(f))
        if wrap - 1 > keys[-1][0]:
            keys.append((wrap - 1, 1.0 - 1.0 / span))
        if keys[-1][0] < wrap <= total:
            keys.append((wrap, 0.0))
        j += 1
    if keys[-1][0] < total:
        keys.append((total, phase))
    return keys


def main():
    les = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
    if not les.load_level(LEVEL):
        raise RuntimeError(f"could not load {LEVEL}")
    eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    actors = eas.get_all_level_actors()
    # only the vehicles themselves: their head and tail lights (car_*_headlight_l, ...) are attached
    # to them and ride along
    # the bodies only: each vehicle's glass (car_*_glass) is attached to its body and rides with it
    cars = sorted((a for a in actors if a.get_actor_label().startswith("car_") and not a.get_actor_label().endswith("_glass")
                   and isinstance(a, unreal.StaticMeshActor)),
                  key=lambda a: a.get_actor_label())
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

    # A lane is one speed. Passes taken in turn per vehicle (4, 3, 4, ...) put two speeds in one lane,
    # and the faster car overtook the slower through its body - seen on the stream. The near lane
    # (+x) runs at PASSES[0] crossings a loop, the far lane (-x) at the bus's count, bus included, and
    # each lane's vehicles are phased evenly among themselves, so the gaps stay even and nobody meets.
    def heading_of(actor):
        yaw = ((actor.get_actor_rotation().yaw % 360.0) + 360.0) % 360.0
        return 1.0 if yaw < 90.0 or yaw > 270.0 else -1.0
    lanes = {1.0: [c for c in cars if heading_of(c) > 0], -1.0: [c for c in cars if heading_of(c) < 0]}
    for car in cars:
        i = cars.index(car)
        car.static_mesh_component.set_mobility(unreal.ComponentMobility.MOVABLE)
        loc = car.get_actor_location()
        rot = car.get_actor_rotation()
        heading = heading_of(car)
        lane = lanes[heading]
        passes = PASSES[0] if heading > 0 else BUS_PASSES
        speed = passes * 2.0 * EDGE / LOOP_S
        # this lane's vehicles spread evenly over one crossing
        phase = (lane.index(car) / max(1, len(lane))) % 1.0
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
        # a conveyor: already driving at frame 0, still driving at the last frame of the loop
        for frame, u in crossing_keys(total, passes, phase):
            loc_x.add_key(unreal.FrameNumber(frame), x0 + (x1 - x0) * u,
                          interpolation=unreal.MovieSceneKeyInterpolation.LINEAR)
        # Where it stands at frame 0 is also where it stands if the sequence never plays: on frame,
        # spread across it with the rest of the fleet, not parked 36 m outside where the old keys left
        # every car. So the street reads as a street even if playback fails in the streamed game.
        at_zero = x0 + (x1 - x0) * phase
        car.set_actor_location(unreal.Vector(at_zero, loc.y, loc.z), False, False)
        log(f"{car.get_actor_label()}: heading {heading:+.0f}, {speed / 100.0:.1f} m/s, {passes} crossings a loop, "
            f"phase {phase:.2f} (x {at_zero / 100.0:+.1f} m at frame 0)")

    player = eas.spawn_actor_from_class(unreal.LevelSequenceActor, unreal.Vector(0.0, 0.0, 0.0))
    player.set_actor_label(SEQ_NAME)
    player.set_sequence(seq)
    settings = player.get_editor_property("playback_settings")
    loop = settings.get_editor_property("loop_count")
    loop.set_editor_property("value", -1)
    settings.set_editor_property("loop_count", loop)
    # Auto-play lives on the actor in some engine versions and inside PlaybackSettings in others, and
    # set_editor_property raises on whichever does not carry it. It used to be set on the struct
    # alone: on an engine that keeps it on the actor that raise would have taken the two saves at the
    # end of this function with it, and the whole pass would have been lost without a word in the log.
    # Both are tried now, whichever takes is logged, and neither can stop the saves.
    played = []
    for target, where in ((settings, "PlaybackSettings"), (player, "the actor")):
        try:
            target.set_editor_property("auto_play", True)
            played.append(where)
        except Exception as err:  # this engine version does not carry it there
            log(f"auto-play is not on {where}: {err}")
    player.set_editor_property("playback_settings", settings)
    log(f"auto-play set on {' and '.join(played)}" if played
        else "no auto-play property took: the sequence will not start by itself")

    unreal.EditorAssetLibrary.save_asset(asset_path)
    les.save_current_level()
    log(f"sequence {asset_path}: {len(cars)} vehicles crossing without a pause, loop {LOOP_S:.0f}s, looping")


main()
