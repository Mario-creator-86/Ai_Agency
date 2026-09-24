"""
The city behind the headquarters by day: the arithmetic look_hq_live.py applies to the skyline's and
the near blocks' material slots, kept here without Unreal so tests/test_city_emissive.py can hold it.

Why it exists (measured in the rebuild window of 2026-09-19): env_report_hq_live.py found
emissive_scaling skyline.uniform=False and near_blocks.uniform=False. Five slots of each component
(antenna, spire, billboard_frame, bridge, slogan_panel; same_city, same_city_edge, pole, sign_panel,
classic_stone) carry the glTF EmissiveFactor 0, 0, 0. The backend dims the city by writing ONE
EmissiveFactor to every slot of a component (MeshComponent.SetVectorParameterValueOnMaterials), so
it may do that only where every slot's factor is 1, 1, 1: written over a 0, it would light those
slots' baked emission textures. So it wrote nothing, and noon showed a lit night city under a blue
sky.

The glTF master multiplies emission as EmissiveTexture x EmissiveFactor x EmissiveStrength
(/InterchangeAssets/gltf/MaterialFunctions/MF_Emissive), so a factor that is the same on all three
channels can move into the strength without changing a single pixel: factor c, strength s becomes
factor 1, strength c x s. A slot at 0 becomes factor 1 with strength 0 and still emits nothing
whatever factor the backend writes. After that every slot of both components is at 1, 1, 1, the
one factor the backend writes scales each slot's own strength in proportion, and at the factor the
dusk has always had (1) the frame is today's frame. A tinted factor (a colour, not a grey) cannot
move into a scalar; none is in these two components today, and one that appears is left alone and
named, so the report stays honest (not uniform) rather than flattened.

Measured in the game on 2026-09-24, that last belief is false for the slots it was written for: a
texture-less glTF instance at factor 1 glowed flat white with its EmissiveStrength at 0 (the Bucharest
sign's frame and bridge, the CREATE panel, the SAME CITY block), and went dark again when factor 0
was written over it. The fold still makes the report uniform, but look_hq_live.near_blocks_day now
moves every plain slot that must not glow, of both components, onto M_HQ_CityDay (no emission), so
no factor the backend writes can light it.

The near blocks by day: the low "SAME CITY" block is painted #24242e (a linear albedo of 0.018,
darker than fresh asphalt) because at dusk it is a silhouette, and at noon it read as dark
cardboard. Its daytime colour is its own hue at a real facade's albedo: a slot whose luminance is
under the floor is lifted to the floor, and nothing brighter is touched. The floor defaults to the
~10 % albedo of the street in front of it (backend/app/office/scene_params.py lights the lower
hemisphere with the same figure). The backend blends dusk to day by the real sun (Daylight 0..1), so at dusk the block is exactly today's.

Plain Python on purpose: the editor's Python and the tests both import it (by file path, the way
dress_hq_live.py loads flat_material.py).
"""

GLTF_ROOT = "/InterchangeAssets/gltf/"
# the near blocks' plain slots by day (look_hq_live.near_blocks_day): BaseColor is a blend of the
# dusk colour (BaseColorFactor, the glTF instance's own) and the day colour (DayBaseColor) by
# Daylight, which the backend sets on the near_blocks component from the real sun
DAY_MASTER = "/Game/HQ/Materials/M_HQ_CityDay"
DAY_MI_PREFIX = "MI_HQ_CityDay_"
DAY_PARAMETER = "Daylight"
# the parameter the backend writes on the skyline and near_blocks components to dim their windows:
# a grey (k, k, k), k in 0..1, 1 = the dusk the Owner approved, 0 = no glow at all
EMISSIVE_PARAMETER = "EmissiveFactor"
# the street's albedo the backend already uses (scene_params: "the ~10 % a street's albedo gives")
DAY_ALBEDO_FLOOR = 0.10
EPS = 1e-4


def is_grey(rgb):
    return max(rgb[:3]) - min(rgb[:3]) < EPS


def fold_emission(factor, strength):
    """What one slot needs so that a single EmissiveFactor (k, k, k) written over it scales its glow.

    factor: the slot's imported EmissiveFactor (r, g, b), or None when the material has none.
    strength: the EmissiveStrength the look pass gives the slot (its imported strength x the city
    gain), or None when the material has no such parameter.
    Returns {"action": "keep" | "fold" | "cannot", "factor": (1, 1, 1) | None,
             "strength": float | None, "reason": str | None}. On "fold" the look pass writes both
    values; on "keep" only the strength it would have written anyway; on "cannot" nothing.
    """
    if factor is None:
        return {"action": "cannot", "factor": None, "strength": None, "reason": "no EmissiveFactor"}
    rgb = [float(c) for c in list(factor)[:3]]
    if all(abs(c - 1.0) < EPS for c in rgb):
        return {"action": "keep", "factor": (1.0, 1.0, 1.0), "strength": strength, "reason": None}
    if not is_grey(rgb):
        return {
            "action": "cannot",
            "factor": None,
            "strength": None,
            "reason": f"EmissiveFactor {[round(c, 4) for c in rgb]} is a colour, not a grey",
        }
    if strength is None:
        return {
            "action": "cannot",
            "factor": None,
            "strength": None,
            "reason": "no EmissiveStrength to carry the factor",
        }
    grey = sum(rgb) / 3.0
    # a factor of 0 carries no glow: 0 x strength keeps it dark under any factor written later
    return {
        "action": "fold",
        "factor": (1.0, 1.0, 1.0),
        "strength": 0.0 if grey < EPS else float(strength) * grey,
        "reason": None,
    }


def emission(texel, factor, strength):
    """The glTF master's emission for one texel (MF_Emissive): texture x factor x strength."""
    return tuple(t * f * strength for t, f in zip(texel, factor, strict=True))


def luminance(rgb):
    """Rec. 709 relative luminance of a linear colour."""
    r, g, b = rgb[:3]
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def day_albedo(dusk_rgb, floor=DAY_ALBEDO_FLOOR):
    """The colour a slot shows by day: its dusk colour (linear) at the floor's luminance, its hue
    kept, or None when it is already at or above the floor (then it stays on its glTF instance)."""
    rgb = [float(c) for c in list(dusk_rgb)[:3]]
    lum = luminance(rgb)
    if floor <= 0 or lum >= floor:
        return None
    if lum < 1e-6:
        return (floor, floor, floor)
    scale = floor / lum
    lifted = [c * scale for c in rgb]
    peak = max(lifted)
    if peak > 1.0:  # a saturated hue cannot reach the floor without leaving 0..1: keep it in range
        lifted = [c / peak for c in lifted]
    return tuple(lifted)


def blended_albedo(dusk_rgb, day_rgb, daylight):
    """What M_HQ_CityDay paints: Lerp(dusk, day, Daylight), as the shader's lerp computes it
    (a + t x (b - a)), so Daylight 0 returns the dusk colour exactly."""
    t = min(1.0, max(0.0, float(daylight)))
    return tuple(a + t * (b - a) for a, b in zip(dusk_rgb[:3], day_rgb[:3], strict=True))


def paints_with_factors_alone(texture_paths):
    """True when every texture a glTF instance samples is one of the importer's own defaults (white,
    flat normal, ...): the slot then paints with its factors alone, and a material of factors alone
    paints it the same. The surfaces pass measured what moving a slot WITH pictures costs (about 6
    units of mean colour distance: surfaces_hq_live.py), so those never move."""
    folder = GLTF_ROOT + "Textures/"
    return all(not p or str(p).startswith(folder) for p in texture_paths)


def baseline_key(path, what):
    """look_baseline.json keys: the material's path alone holds its imported EmissiveStrength (as
    since 2026-09-15); the imported EmissiveFactor sits beside it under path#EmissiveFactor, so a
    rerun of the look pass folds from the imported values, never from its own earlier result."""
    return path if what == "EmissiveStrength" else f"{path}#{what}"
