"""
Seated office characters, rendered in KEY colours so the frontend can recolour each part into
an agent's own skin / hair / garment ramps (see office_characters.js agentLook()).

Screen space: x = 0 at the seat centre, y = 0 at the desk plane (`deskTop`). The waist sits at
y = 2 and is hidden by the desk; the head is 14 x 13 px; hair rises above the head.

Parts (each its own sprite, composited by the renderer in this order):
  body_<face>        torso, neck, head, face, brows           face: open | blink | talk | sleep
  hair_<style>       drawn over the head (sleep shifts it down 3 px in the renderer)
  glasses_<kind>     square | round
  headset
  hands_<pose>       forearms + hands in front of the desk    pose: rest | type_a | type_b | chin | sleep
  mug                a coffee mug for the idle sip
"""

from __future__ import annotations

import pixelart as pa
from pixelart import KEY_RAMPS

DEEP = pa.Builder.units_deep

EYE_WHITE = "#ffffff"   # renderer maps to '#f6f2ea'
EYE_DARK = "#000000"    # renderer maps to AMBIENT.shadow
GLASS_LIGHT = "#dfe6f0"
GLASS_DARK = "#3a3a52"

HEAD_W, HEAD_H, HEAD_D = 14, 13, 11
WAIST_Y = 2
SHOULDER_Y = WAIST_Y + 14
HEAD_Y = SHOULDER_Y + 1          # bottom of the head (neck is 1 px)
BODY_DEPTH = 22                  # units; the seat is well behind the desk's far edge


class KeyMats:
    def __init__(self):
        self.used: list[str] = []

    def key(self, kind: str):
        self.used.extend(KEY_RAMPS[kind])
        return pa.key_material(kind)

    def tone(self, kind: str, i: int):
        c = KEY_RAMPS[kind][i]
        self.used.append(c)
        return pa.flat_material(f"{kind}{i}", c)

    def flat(self, c: str):
        self.used.append(c)
        return pa.flat_material(f"flat{c}", c)


def build_body(b: pa.Builder, m: KeyMats, face: str = "open"):
    skin, garment, second = m.key("skin"), m.key("garment"), m.key("second")
    y0 = BODY_DEPTH
    down = 3 if face == "sleep" else 0
    # Torso: chest block with rounded shoulders, a placket in the second colour.
    b.box("torso", -11, WAIST_Y, 22, 12, 9, garment, y0=y0, bevel=1.2)
    b.box("shoulders", -12, WAIST_Y + 6, 24, 7, 9, garment, y0=y0 - 0.2, bevel=1.6)
    b.box("placket", -1, WAIST_Y + 1, 2, 11, 0.4, second, y0=y0 - DEEP(3) - 0.2)
    b.box("collar_l", -6, SHOULDER_Y - 3, 5, 3, 1, second, y0=y0 - DEEP(3) - 0.3)
    b.box("collar_r", 1, SHOULDER_Y - 3, 5, 3, 1, second, y0=y0 - DEEP(3) - 0.3)
    # Upper arms hugging the torso sides.
    for side in (-1, 1):
        b.box(f"arm{side}", side * 13 - (2 if side < 0 else 0) - 1, WAIST_Y, 3, 12, 6, garment, y0=y0 + 1, bevel=0.6)
    # Neck and head.
    b.box("neck", -2, HEAD_Y - 1 - down, 4, 2, 4, skin, y0=y0 + 2)
    b.box("head", -HEAD_W / 2, HEAD_Y - down, HEAD_W, HEAD_H, HEAD_D, skin, y0=y0 - 1, bevel=2.4)
    # Face: eyes (white + dark), brows (hair tone 1), mouth (skin tone 1), cheeks (skin tone 1).
    fy = HEAD_Y - down
    front = y0 - 1 - DEEP(HEAD_D) * 0.0 - 0.6   # just in front of the head's front face
    eye_y = fy + 5
    if face == "sleep":
        for ex in (-5, 2):
            b.box(f"eye{ex}", ex, eye_y, 3, 1, 0, m.flat(EYE_DARK), y0=front)
    elif face == "blink":
        for ex in (-5, 2):
            b.box(f"eye{ex}", ex, eye_y, 2, 1, 0, m.flat(EYE_DARK), y0=front)
    else:
        for ex in (-5, 2):
            b.box(f"eyew{ex}", ex, eye_y, 2, 2, 0, m.flat(EYE_WHITE), y0=front)
            b.box(f"eyed{ex}", ex + 1, eye_y, 1, 1, 0, m.flat(EYE_DARK), y0=front - 0.2)
    for bx in (-5, 2):
        b.box(f"brow{bx}", bx, eye_y + 3, 3, 1, 0, m.tone("hair", 1), y0=front)
    mouth_h = 2 if face == "talk" else 1
    b.box("mouth", -1, fy + 2 - (1 if face == "talk" else 0), 3 if face != "sleep" else 2, mouth_h, 0, m.tone("skin", 1), y0=front)
    b.box("cheek_l", -7, fy + 4, 1, 1, 0, m.tone("skin", 1), y0=front)
    b.box("cheek_r", 6, fy + 4, 1, 1, 0, m.tone("skin", 1), y0=front)
    return {"head": (-HEAD_W // 2, fy, HEAD_W, HEAD_H)}


def head_holdout(b: pa.Builder, m: KeyMats, down: int = 0):
    """The head as a holdout, so parts rendered on their own are still occluded by it."""
    head = b.box("head_holdout", -HEAD_W / 2, HEAD_Y - down, HEAD_W, HEAD_H, HEAD_D, pa.flat_material("holdout", "#000000"), y0=BODY_DEPTH - 1, bevel=2.4)
    head.is_holdout = True
    b.objects.remove(head)
    return head


def build_hair(b: pa.Builder, m: KeyMats, style: str = "short"):
    hair = m.key("hair")
    head_holdout(b, m)
    y0 = BODY_DEPTH - 1
    top = HEAD_Y + HEAD_H
    d = HEAD_D - 2            # a shell over the skull, rounded like the head itself
    cap = lambda name, sx, sy, w, h, extra=0.0: b.box(name, sx, sy, w, h, d, hair, y0=y0 - extra - 0.6, bevel=2.2)  # noqa: E731
    if style == "short":
        cap("cap", -8, top - 3, 16, 5, 0.4)
        b.box("fringe", -7, top - 5, 8, 2, 1, hair, y0=y0 - 1.6)
    elif style == "crop":
        cap("cap", -7, top - 2, 14, 4, 0.2)
    elif style == "fade":
        cap("cap", -7, top - 2, 14, 4, 0.2)
        b.box("fade_l", -8, top - 5, 1, 3, d - 1, hair, y0=y0 + 0.5)
        b.box("fade_r", 7, top - 5, 1, 3, d - 1, hair, y0=y0 + 0.5)
    elif style == "bob":
        cap("cap", -8, top - 3, 16, 5, 0.4)
        b.box("side_l", -9, top - 12, 2, 10, d, hair, y0=y0 - 0.2)
        b.box("side_r", 7, top - 12, 2, 10, d, hair, y0=y0 - 0.2)
        b.box("fringe", -6, top - 5, 8, 2, 1, hair, y0=y0 - 1.6)
    elif style == "long":
        cap("cap", -8, top - 3, 16, 5, 0.4)
        b.box("side_l", -10, top - 20, 2, 18, d, hair, y0=y0 - 0.2)
        b.box("side_r", 8, top - 20, 2, 18, d, hair, y0=y0 - 0.2)
        b.box("back", -9, top - 20, 18, 17, 2, hair, y0=y0 + DEEP(HEAD_D) - 1.5)
    elif style == "bun":
        cap("cap", -7, top - 2, 14, 4, 0.2)
        b.sphere("bun", 0, top + 3, 3.0, hair, y0=y0 + 5, segments=12)
    elif style == "curly":
        cap("cap", -8, top - 4, 16, 6, 0.5)
        for i, (sx, sy) in enumerate(((-9, top - 6), (8, top - 6), (-5, top + 2), (5, top + 2), (0, top + 3))):
            b.sphere(f"curl{i}", sx, sy, 2.2, hair, y0=y0 + (0 if i < 2 else 1), segments=10)
    elif style == "ponytail":
        cap("cap", -8, top - 3, 16, 5, 0.4)
        b.box("tail", 7, top - 15, 3, 13, 3, hair, y0=y0 + DEEP(HEAD_D) - 3)
    elif style == "undercut":
        cap("cap", -6, top - 2, 12, 6, 0.9)
        b.box("swoop", -7, top - 1, 9, 2, 2, hair, y0=y0 - 1.6)
    elif style == "bald":
        pass
    return {}


def build_glasses(b: pa.Builder, m: KeyMats, kind: str = "square"):
    light, dark = m.flat(GLASS_LIGHT), m.flat(GLASS_DARK)
    head_holdout(b, m)
    y0 = BODY_DEPTH - 1 - 1.4
    ey = HEAD_Y + 5
    for ex in (-6, 1):
        if kind == "square":
            b.box(f"rim_t{ex}", ex, ey + 2, 5, 0.8, 0, light, y0=y0)
            b.box(f"rim_b{ex}", ex, ey - 1, 5, 0.8, 0, light, y0=y0)
            b.box(f"rim_l{ex}", ex, ey - 1, 0.8, 4, 0, light, y0=y0)
            b.box(f"rim_r{ex}", ex + 4, ey - 1, 0.8, 4, 0, light, y0=y0)
        else:
            b.cylinder(f"ring{ex}", ex + 2.5, ey - 0.6, 2.1, 0.5, dark, y0=y0, axis="Y", verts=12)
            b.cylinder(f"ring_in{ex}", ex + 2.5, ey, 1.5, 0.5, light, y0=y0 - 0.3, axis="Y", verts=12)
    b.box("bridge", -1, ey + 1, 2, 0.8, 0, dark, y0=y0)
    return {}


def build_headset(b: pa.Builder, m: KeyMats):
    light, dark = m.flat(GLASS_LIGHT), m.flat(GLASS_DARK)
    head_holdout(b, m)
    y0 = BODY_DEPTH - 1
    top = HEAD_Y + HEAD_H
    b.box("band", -8, top - 1, 16, 2, 2, dark, y0=y0 - 0.5 - 1.6)
    for side, sx in ((-1, -9), (1, 7)):
        b.box(f"band{side}", sx, top - 6, 2, 6, 2, dark, y0=y0 - 1.6)
        b.box(f"cup{side}", sx - (1 if side < 0 else 0), HEAD_Y + 3, 3, 5, 4, light, y0=y0 + 0.5, bevel=0.6)
    b.box("mic_arm", -8, HEAD_Y + 2, 1, 3, 0, dark, y0=y0 - 2.6)
    b.box("mic", -8, HEAD_Y + 1, 3, 1, 0, dark, y0=y0 - 2.6)
    return {}


def build_hands(b: pa.Builder, m: KeyMats, pose: str = "rest"):
    """Forearms and hands on the desk's far edge (y from 0 to -3), in front of the desk."""
    skin, garment = m.key("skin"), m.key("garment")
    y0 = 1.0                  # just in front of the desk top's far edge on screen
    if pose == "sleep":
        # Arms folded on the desk under the head.
        b.box("fold_l", -11, -2, 14, 4, 3, garment, y0=DEEP(2), bevel=0.6)
        b.box("fold_r", -3, -1, 14, 4, 3, garment, y0=DEEP(2) - 0.5, bevel=0.6)
        b.box("hand", -3, 0, 5, 3, 2, skin, y0=DEEP(2) - 1.2)
        return {}
    if pose == "chin":
        # Right forearm rises to the chin; the left hand rests on the desk.
        b.box("cuff_l", -12, -3, 3, 4, 2, garment, y0=DEEP(3))
        b.box("hand_l", -13, -3, 5, 1, 4, skin, y0=DEEP(1))
        b.box("forearm_r", 5, -3, 3, 16, 3, garment, y0=DEEP(3))
        b.box("hand_r", 4, 13, 5, 4, 3, skin, y0=DEEP(2.6), bevel=0.6)
        return {}
    lift = {"rest": (0, 0), "type_a": (1, 0), "type_b": (0, 1)}[pose]
    for side, sx, up in ((-1, -12, lift[0]), (1, 8, lift[1])):
        b.box(f"cuff{side}", sx + 1, -3 + up, 3, 4, 2, garment, y0=DEEP(3))
        b.box(f"hand{side}", sx, -3 + up, 5, 1.2, 4, skin, y0=DEEP(1) - up * 0.6)
    return {}


def build_mug(b: pa.Builder, m: KeyMats):
    mug = m.flat("#c9573f")
    b.cylinder("mug", 3, 0, 3, 6, pa.toon_material("mug_toon", pa.ramp_from("#c9573f", pa.load_palette())), y0=1)
    b.box("handle", 6, 1, 2, 3, 1, mug, y0=1)
    b.box("coffee", 1, 5.4, 4, 0.4, 3, m.flat("#fff3d6"), y0=0.5)
    return {}


# name -> (builder, frame (x0, y0, w, h) in screen px, kwargs, outline?)
PARTS = {
    **{f"body_{face}": (build_body, (-17, -6, 34, 46), {"face": face}) for face in ("open", "blink", "talk", "sleep")},
    **{f"hair_{style}": (build_hair, (-17, 4, 34, 40), {"style": style})
       for style in ("short", "crop", "fade", "bob", "long", "bun", "curly", "ponytail", "undercut", "bald")},
    "glasses_square": (build_glasses, (-17, 10, 34, 24), {"kind": "square"}),
    "glasses_round": (build_glasses, (-17, 10, 34, 24), {"kind": "round"}),
    "headset": (build_headset, (-17, 4, 34, 40), {}),
    **{f"hands_{pose}": (build_hands, (-17, -8, 34, 30), {"pose": pose}) for pose in ("rest", "type_a", "type_b", "chin", "sleep")},
    "mug": (build_mug, (-4, -3, 16, 14), {}),
}
