"""The room windows' three states, the pure part (look_hq_live.py window_views() does the Unreal part;
tests/test_window_view.py holds this file).

The rooms' windows onto the city (the Blender scene's window_view and window_view_b) keep the glTF
instance the import gives them, re-textured with their dusk picture exactly as every build since
2026-09-15 has done. That is the approved dusk, and the rejected rebuild of 2026-09-19 showed why it
must stay: it moved the windows to a hand-built M_HQ_WindowView that could not be shown to paint the
same, and the build frame came out 4-7 grey levels brighter in the rooms before any value was sent.

A glTF instance cannot take a parameter its parent lacks, so the day and night pictures ride on a
copy of the instance's own parent chain (MI_Default_Opaque_DS and M_Default, the Interchange glTF
masters), with exactly one change in the copied master: at its base colour and emissive outputs,
lerp(original, day picture, DayBlend), then lerp(that, night picture, NightBlend). At both blends 0
(their defaults, and the backend's value at the reference dusk) lerp returns its first input
unchanged, so the window is painted by the untouched original graph from the same parameter values.
The look pass checks the values (differences() below) and fails the rebuild if any old one moved.

The night picture comes from make_textures.py's window_view generators. None exists yet: it must be
drawn there (see NIGHT_NOTE). Until it is, the night state is the darkest honest one, a black pane
(NightPicture 0), never the dusk horizon in the night.
"""

import os

# make_textures.py's pictures, by the Blender scene's material names
DUSK_PICTURES = {"window_view": "window_city", "window_view_b": "window_city_b"}
DAY_PICTURE = "window_city_day"
NIGHT_PICTURE = "window_city_night"
NIGHT_NOTE = (
    "no night picture: art-source/blender/hq/make_textures.py must draw window_city_night.png "
    "with its window_view generator (the towers of window_city, seed 11, under hq_time.js's night "
    "sky #070b1a / #0f1630 / #1a2244 / #232a4a) and the look pass be run again; until then the "
    "window is dark at night"
)
# The per-picture instance (a duplicate of the import's instance, in the build's own Scene_ folder)
# carries this prefix: env_report_hq_live.py finds the window slots by it.
INSTANCE_PREFIX = "MI_HQ_WindowView_"
# The copied parent chain lives in /Game/HQ/Materials under versioned names: a rerun of the look
# pass reuses a copy with the same graph and never edits one the level still uses. Raise the version
# whenever the inserted graph changes.
GRAPH_VERSION = 1
COPY_PREFIX = "M_HQ_WindowView_"
# The parameters the copy adds, and their defaults (the reference dusk: both blends at 0)
ADDED_DEFAULTS = {
    "DayBlend": 0.0,
    "NightBlend": 0.0,
    # 1 once the night picture exists; at 0 the night state is a black pane
    "NightPicture": 0.0,
    # the old instance's own factors and strength, copied onto the day and night branches so the
    # new pictures are painted as the dusk one is, without reusing the glTF parameter names
    "ViewEmissiveStrength": 1.0,
}
ADDED_VECTORS = ("ViewBaseFactor", "ViewEmissiveFactor")
ADDED_TEXTURES = ("DayTex", "NightTex")
ADDED_PARAMETERS = tuple(ADDED_DEFAULTS) + ADDED_VECTORS + ADDED_TEXTURES


def dusk_picture(material_name):
    """The dusk picture of a window slot's material, or None for any other material."""
    name = str(material_name)
    if name.startswith(INSTANCE_PREFIX):
        image = name[len(INSTANCE_PREFIX):]
        return image if image in DUSK_PICTURES.values() else None
    # the importer numbers duplicates (window_view_3); the rule the look pass has always used
    return DUSK_PICTURES.get(name.lower().rstrip("0123456789").rstrip("_"))


def night_state(textures_dir):
    """The night picture if make_textures.py has drawn it, else the dark state and why."""
    path = os.path.join(str(textures_dir), f"{NIGHT_PICTURE}.png")
    if os.path.exists(path):
        return {"picture": path, "NightPicture": 1.0, "note": f"night picture {path}"}
    return {"picture": None, "NightPicture": 0.0, "note": NIGHT_NOTE}


def copy_name(source_name):
    return f"{COPY_PREFIX}{source_name}_v{GRAPH_VERSION}"


def instance_name(image):
    return f"{INSTANCE_PREFIX}{image}"


def differences(before, after):
    """Every parameter the old instance had whose value the new one does not repeat exactly, as
    "kind:name: old -> new" or "kind:name: lost". Parameters the copy adds are not compared."""
    out = []
    for key, value in before.items():
        if key not in after:
            out.append(f"{key}: lost")
        elif after[key] != value:
            out.append(f"{key}: {value} -> {after[key]}")
    return out
