"""prompt_lint: read every prompt before a credit is priced or spent.

The Nepal film (storyboard 1d530880, 2026-09-26) sent the image model and the video model
the same template text: enum codes ("NEPAL_CLIMATE_CRISIS"), a hex palette, "Camera: medium
shot, locked camera" on every scene, an 8-item "Avoid:" list, a bar chart and a black screen
asked of a photo generator, and never the bible's "No human faces" rule. Each of those is a
finding here, so the shooting sheet can show it to the Owner and the purchase steps refuse
to price a film with an open BLOCK.

The module is pure text: no database, no provider, no network. Every finding carries its
code, severity, scene, the offending substring as evidence and a Romanian message that
quotes that evidence. BLOCK stops the pricing and purchase steps; WARN is shown only.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from runpod_worker.contract import MAX_PROMPT, WORKFLOWS

from app.wording import count as count_ro

BLOCK = "BLOCK"
WARN = "WARN"

LIVE = "LIVE"
CARD_KINDS = ("DATA_CARD", "TITLE_CARD", "BLACK")
SCENE_KINDS = (LIVE, *CARD_KINDS)

# The motion prompt's last sentence. veo takes its exclusions as negativePrompt nouns, so
# its promptText ends before the "No ..." sentence.
MOTION_CLOSING = "Continuous, seamless shot. No subtitles, no on-screen text."
VEO_MOTION_CLOSING = "Continuous, seamless shot."

# Runway's promptText maxLength, when the contract does not state one.
DEFAULT_PROMPT_MAX_UTF16 = 1000
#: What each connected image route allows for one prompt, in characters, by model id: the
#: GPU worker declares MAX_PROMPT for every workflow it serves (`runpod_worker.contract`);
#: another vendor declares its own here. A model absent is linted on the explicit terms of
#: its contract, else on Runway's legacy figure. A serial's complete prompt is never cut to
#: fit (2026-10-14), so the route it is bought on must be the one it is judged against.
ALLOWANCES: dict[str, int] = {model: MAX_PROMPT for model in WORKFLOWS}

# The still prompt's band of words: the studio's own editorial bound, not a vendor's — the
# RunPod worker allows 20 000 characters (`runpod_worker.contract.MAX_PROMPT`), Runway 1 000
# UTF-16 units (`DEFAULT_PROMPT_MAX_UTF16`, kept by the composer's cap). 60-120 since the
# money staircase after the Nepal film (2026-10-01: long prompts drew mixed-up pictures);
# 60-900 since 2026-10-15 20:07Z — the Owner: «de ce 120 de cuvinte? cine o impune?», then
# «MUTĂ LA 900! PENTRU AMBELE! DACĂ NE PERMITE» — so a full subject, the action, the room, the
# light and the composition fit together instead of giving way to one another (7c26a7ce
# scene 2: four rounds for a room the budget had cut). It permits: the vendor's character cap
# still bounds the composed prompt (`prompt_cap`) — on the RunPod route 20 000 characters
# (about 3 000 words), on Runway's legacy figure 1 000.
STILL_WORDS = (60, 900)
# The motion prompt's band of words. 20-70 since the Nepal film (2026-09-27); 25-95 since
# «Mișcare v2» (2026-10-11): a camera move said with its path and its tempo, a second beat
# of camera on a clip of seven seconds or more, the subject's own action and the world in
# motion do not fit in seventy words, and the live prompts of film aa170155 that did fit
# («Slow push-in toward the subject. A slow drift of dust motes ... barely moving.») were
# what the Owner saw as «doar un zoom, și mișcări mici». 25-110 since 2026-10-15 16:50Z
# (a4ecf40a scenes 6 and 7): the serial clip also names who is in the frame and nobody
# else, and that the faces keep their features — the two causes of the day's paid refusals —
# and those did not fit beside the ending and the room's life in ninety-five.
# 25-900 since 2026-10-15 20:07Z, the Owner's figure for both prompts (see STILL_WORDS): the
# move, the whole action, the ending, the cast, the faces and the room's life all fit; the
# vendor's character cap (`prompt_cap`) is the bound that remains.
MOTION_WORDS = (25, 900)
MAX_INLINE_EXCLUSIONS = 2
EVIDENCE_CHARS = 120

# The camera-move enum of the motion prompt, each with the spellings that mean it. One key
# per family of movement, and no two patterns match the same words, so a prompt that names
# its move at the start and holds it at the end still names one move (CAMERA_COUNT). The ten
# keys of 2026-09-27 stay, because stored prompts, written plans, config/film_models.json and
# the Director's rewrites name them; «Mișcare v2» (2026-10-11) adds the cinema's own moves —
# a dolly with a path, a tracking move alongside the subject, a crane that reveals, a
# handheld drift, a rack focus — and takes "dolly" and "crane" out of the older patterns so
# that each spelling means exactly one key.
CAMERA_MOVES: dict[str, str] = {
    "static": (
        r"\bstatic(?:\s+(?:camera|shot|frame))?\b|\blocked[- ]?(?:off\s+)?camera\b"
        r"|\blocked[- ]off\b|\bcamera\s+(?:is\s+|stays\s+|remains\s+)?locked\b"
    ),
    "slow push-in": r"(?:\b(?:slow|gentle|steady|fast|quick)\s+)?\bpush(?:es|ing)?[- ]in\b",
    "slow pull-back": (
        r"(?:\b(?:slow|gentle|steady|fast|quick)\s+)?\bpull(?:s|ing)?[- ](?:back|out)\b"
    ),
    "dolly in": r"\bdoll(?:y|ies|ying)[- ](?:in|inward|forward|closer)\b",
    "dolly out": r"\bdoll(?:y|ies|ying)[- ](?:out|outward|back|backward|away)\b",
    "slow pan left": r"(?:\b(?:slow|gentle|steady|fast|quick)\s+)?\bpan(?:s|ning)?\s+left\b",
    "slow pan right": r"(?:\b(?:slow|gentle|steady|fast|quick)\s+)?\bpan(?:s|ning)?\s+right\b",
    "tracking left": (
        r"\b(?:track(?:s|ing)?|truck(?:s|ing)?|doll(?:y|ies|ying))\s+(?:shot\s+)?"
        r"(?:to\s+the\s+)?left(?:ward)?\b"
    ),
    "tracking right": (
        r"\b(?:track(?:s|ing)?|truck(?:s|ing)?|doll(?:y|ies|ying))\s+(?:shot\s+)?"
        r"(?:to\s+the\s+)?right(?:ward)?\b"
    ),
    "tilt up": r"(?:\b(?:slow|gentle|steady|smooth)\s+)?\btilt(?:s|ing)?\s+up\b",
    "tilt down": r"(?:\b(?:slow|gentle|steady|smooth)\s+)?\btilt(?:s|ing)?\s+down\b",
    "aerial drift forward": (
        r"\baerial\s+drift(?:s|ing)?(?:\s+forward)?\b|\bdrone\s+(?:drift|glide)s?\s+forward\b"
    ),
    "pedestal up": r"\bpedestal(?:s)?\s+up\b",
    "crane up": (
        r"\bcrane(?:s|ing)?\s+(?:up|upward|upwards)\b|\bboom(?:s|ing)?\s+up\b|\brising\s+crane\b"
    ),
    "crane down": (
        r"\bcrane(?:s|ing)?\s+(?:down|downward|downwards)\b|\bboom(?:s|ing)?\s+down\b"
        r"|\bdescending\s+crane\b"
    ),
    "slow orbit": (
        r"(?:\b(?:slow|gentle|steady|fast)\s+)?\borbit(?:s|ing)?\b|\barc(?:s|ing)?\s+around\b"
    ),
    "handheld drift": r"\bhand[- ]?held\b",
    "rack focus": (
        r"\brack[- ]focus\b|\bfocus\s+(?:racks?|pulls?|pulling)\b|\bpull(?:s|ing)?\s+focus\b"
    ),
}

SHOT_SIZE = re.compile(
    r"\b(extreme\s+wide|wide|medium|close[- ]up|detail|establishing|aerial|macro|full)"
    r"\s+(?:shot|view|angle)\b",
    re.IGNORECASE,
)

# A still is one frozen moment: a camera move, a tempo or a span of the clip's seconds is
# the motion prompt's and has no place in the picture's words (the Owner, 2026-10-13: «în
# promptul de imagine nu are ce să caute indicații de mișcare»). The compiler leaves them out
# of the still (`prompt_agent._clauses_of`: a clause that moves the camera is dropped, a tempo
# is taken out of its clause) and `lint_still_prompt` says when a stored still prompt still
# carries one (STILL_MOTION).
#: A tempo or a span of the clip inside a clause: taken out of the still's words.
STILL_TEMPO = re.compile(
    r"\b(?:slowly|steadily|gradually|gently|smoothly|quickly|rapidly|swiftly|briskly"
    r"|continuously|unhurriedly|over\s+the\s+(?:clip|shot)(?:'s)?(?:\s+seconds)?"
    r"|throughout\s+the\s+(?:clip|shot)|for\s+the\s+whole\s+(?:clip|shot)"
    r"|across\s+the\s+(?:whole\s+)?(?:clip|shot)|over\s+\d+\s+seconds?"
    r"|as\s+the\s+(?:clip|shot)\s+(?:goes\s+on|runs|ends)"
    r"|by\s+the\s+end\s+of\s+the\s+(?:clip|shot)|from\s+the\s+first\s+frame\s+to\s+the\s+last"
    r"|frame\s+by\s+frame|second\s+by\s+second)\b",
    re.IGNORECASE,
)
#: The camera itself as the subject of a verb of movement: the whole clause is the motion's.
#: Only the camera, the lens and a drone: «the frame holds only the place and the things
#: named» (`prompt_agent.NO_PEOPLE_SENTENCE`) is a composition, and «the shot shows» a
#: picture; and only verbs that move it — a camera that «holds» or «stays» is a still.
CAMERA_MOVING = re.compile(
    r"\b(?:the\s+)?(?:camera|lens|drone)\s+"
    r"(?:(?:slowly|gently|steadily|smoothly|then)\s+)?"
    r"(?:moves?|moving|glides?|gliding|push(?:es|ing)|pulls?|pulling|tracks?|tracking"
    r"|follows?|following|circles?|circling|orbits?|orbiting|rises?|rising|descends?"
    r"|descending|sweeps?|sweeping|drifts?|drifting|pans?|panning|tilts?|tilting|zooms?"
    r"|zooming|cranes?|craning|arcs?|arcing|travels?|travell?ing|swings?|swinging|creeps?"
    r"|creeping|floats?|floating|clos(?:es|ing)\s+in|eases?\s+(?:in|out|closer|back)"
    r"|easing\s+(?:in|out|closer|back))\b",
    re.IGNORECASE,
)
#: The named moves a still prompt may say without moving anything: a locked camera is a
#: composition, a handheld look is grain.
_STILL_MAY_NAME = frozenset({"static", "handheld drift"})
#: Where a named move is the camera's and not the subject's own: the clause names the camera
#: or its stand-ins, or the move is said in the cinema's own words. «Earth orbits the Sun»
#: and «she pulls back the curtain» are the subject's moment and stay (the Codex review of
#: c6dc05c, 2026-10-13: a bare «orbits» emptied an astronomy scene's still).
_CAMERA_CONTEXT = re.compile(
    r"\b(?:camera|lens|shot|frame|framing|view|viewpoint|drone|pov|point\s+of\s+view)\b",
    re.IGNORECASE,
)
_CAMERA_ONLY_MOVE = re.compile(
    r"\b(?:doll(?:y|ies|ying)|crane(?:s|ing)?|pedestal|boom(?:s|ing)?\s+(?:up|down)"
    r"|track(?:s|ing)?\s+(?:shot\s+)?(?:to\s+the\s+)?(?:left|right)|truck(?:s|ing)?"
    r"|pan(?:s|ning)?\s+(?:left|right)|push[- ]in|pull[- ](?:back|out)|aerial\s+drift"
    r"|rack[- ]focus|focus\s+(?:racks?|pulls?|pulling)|pull(?:s|ing)?\s+focus|zoom\w*)\b",
    re.IGNORECASE,
)


def _camera_moves_in(text: str) -> list[tuple[int, str]]:
    """(start, words) of each named move in ``text`` that is the camera's: not a locked camera
    or a handheld look (`_STILL_MAY_NAME`), and either said beside the camera
    (`_CAMERA_CONTEXT`) or in the cinema's own words (`_CAMERA_ONLY_MOVE`)."""
    lowered = text.lower()
    beside_the_camera = bool(_CAMERA_CONTEXT.search(text))
    found: list[tuple[int, str]] = []
    for move, written in camera_moves(text):
        if move in _STILL_MAY_NAME:
            continue
        if not beside_the_camera and not _CAMERA_ONLY_MOVE.search(written):
            continue
        at = lowered.find(written.lower())
        if at >= 0:
            found.append((at, written))
    return found


def still_motion(text: str) -> str:
    """The earliest words of a still prompt that move the camera (a named move of the camera,
    or the camera as the subject of a verb of movement) or give a tempo or a span of the
    clip, else ""."""
    found: list[tuple[int, str]] = []
    for pattern in (CAMERA_MOVING, STILL_TEMPO):
        match = pattern.search(text)
        if match:
            found.append((match.start(), match.group(0).strip()))
    found += _camera_moves_in(text)
    return min(found)[1] if found else ""


def moves_the_camera(text: str) -> bool:
    """Whether a clause of a plan field moves the camera (`CAMERA_MOVING`, or a named move
    that is the camera's, `_camera_moves_in`)."""
    return bool(CAMERA_MOVING.search(text)) or bool(_camera_moves_in(text))


#: What joins a subject's moment to the camera's move in one clause ("the mercury rises as
#: the camera pushes in"): cut off with the move, the moment stays.
_BEFORE_CAMERA = re.compile(r"\s*(?:,|;|\b(?:as|while|and|with|then|before|until)\b)\s*$")


def static_clause(text: str) -> str:
    """A clause of a plan field as a still may say it: without the camera's movement. A clause
    that only moves the camera is "" (the motion prompt's); one that says a moment first
    ("the mercury rises as the camera pushes in on the scale") keeps the moment ("the mercury
    rises") when at least two words of it stay whole."""
    starts = [match.start() for match in CAMERA_MOVING.finditer(text)]
    starts += [at for at, _written in _camera_moves_in(text)]
    if not starts:
        return text
    first = min(starts)
    head = _BEFORE_CAMERA.sub("", text[:first]).strip()
    # The move was named by a subject of its own ("the camera"): the head ends before it.
    head = re.sub(r"\s*\b(?:the|a|an)\s*$", "", head, flags=re.IGNORECASE).strip(" ,;")
    if len(head.split()) < 2 or dangling(head):
        return ""
    # A head that is only the camera's own name ("the view", "the camera") says no picture.
    if _CAMERA_CONTEXT.fullmatch(re.sub(r"^(?:the|a|an)\s+", "", head, flags=re.IGNORECASE)):
        return ""
    return head


def without_tempo(text: str) -> str:
    """``text`` with its tempo and clip-span words taken out (`STILL_TEMPO`), the spacing and
    the punctuation closed up: "cloud rolls steadily across the ridges" is "cloud rolls across
    the ridges"."""
    said = STILL_TEMPO.sub(" ", text)
    # Removing the last adverb in "faintly and steadily" must not leave a dangling
    # conjunction: the compiler otherwise discards the whole visible-state clause.
    if said != text:
        said = re.sub(r"\s+\b(?:and|or|but)\b(?=\s*[,;.!?]|\s*$)", "", said)
    said = re.sub(r"\s+([,;.!?])", r"\1", re.sub(r"\s{2,}", " ", said))
    return said.strip()


# The tempo a motion prompt must say once. "Smooth", "fluid", "deliberate" and "sweeping"
# are the cinema's tempo words for an ample move (2026-10-11); "fast" and "quick" stay for a
# plan that asks for them (production_policy reads "fast" as a fast-motion need).
SPEED_WORDS = re.compile(
    r"\b(?:slow(?:ly)?|gentle|gently|steady|steadily|calm(?:ly)?|subtle|measured|unhurried"
    r"|smooth(?:ly)?|fluid(?:ly)?|deliberate(?:ly)?|sweeping|walking\s+pace"
    r"|fast|quick(?:ly)?|brisk)\b",
    re.IGNORECASE,
)
# Something the world does while the subject acts. Shadows, curtains, particles, sparks,
# embers and flames joined the list with «Mișcare v2»: indoor scenes (a lamp-lit desk, an
# office) have no cloud or grass, and their world moves in light and small things.
ENVIRONMENT_MOTION = re.compile(
    r"\b(?:drift\w*|wind|breeze|flow\w*|dust|clouds?|mist|fog|rain\w*|water|smoke|leaves"
    r"|ripple\w*|sway\w*|waves?|snow\w*|steam|haze|grass|current|flicker\w*|stream\w*"
    r"|shadows?|curtains?|particles?|sparks?|embers?|flames?|light\s+(?:sweep\w*|shift\w*))\b",
    re.IGNORECASE,
)
# A verb of the subject's own motion, in a plan's action: what people do (stands, walks to
# the window, turns, hands over the ledger, gestures) and what objects do (spins, pulses,
# unfolds). Read by the compiler to admit an action clause into the motion prompt as
# movement, never to refuse one; a noun that spells like a verb ("waves", "steps") admits
# a clause that moves nothing, which costs a few words and nothing else.
SUBJECT_MOTION = re.compile(
    r"\b(?:walks?|walking|runs?|running|strides?|striding|steps?|stepping|turns?|turning"
    r"|stands?|standing|sits?|sitting|rises?|rising|leans?|leaning|reach(?:es|ing)|lifts?"
    r"|lifting|raises?|raising|lowers?|lowering|hands?\s+(?:over|out|back|across)|handing"
    r"|gestures?|gesturing|nods?|nodding|shakes?|shaking|points?|pointing|waves?|waving"
    r"|pulls?|pulling|push(?:es|ing)|carr(?:ies|ying)|offers?|offering|takes?|taking|gives?"
    r"|giving|opens?|opening|clos(?:es|ing)|writes?|writing|typ(?:es|ing)|taps?|tapping"
    r"|press(?:es|ing)|draws?|drawing|paints?|painting|stirs?|stirring|pours?|pouring|drops?"
    r"|dropping|catch(?:es|ing)|throws?|throwing|climbs?|climbing|descends?|descending"
    r"|cross(?:es|ing)|enters?|entering|approach(?:es|ing)|glanc(?:es|ing)"
    r"|looks?\s+(?:up|over|back|around|down)|looking|watch(?:es|ing)|speaks?|speaking"
    r"|talks?|talking|laughs?|laughing|smiles?|smiling|argu(?:es|ing)|shouts?|shouting"
    r"|whispers?|whispering|hurr(?:ies|ying)|rush(?:es|ing)|pac(?:es|ing)|danc(?:es|ing)"
    r"|kneels?|kneeling|crouch(?:es|ing)|jumps?|jumping|bends?|bending|stretch(?:es|ing)"
    r"|breath(?:es|ing)|trembl(?:es|ing)|spins?|spinning|rotat(?:es|ing)|puls(?:es|ing)"
    r"|swings?|swinging|rolls?|rolling|slides?|sliding|glid(?:es|ing)|sweeps?|sweeping"
    r"|scatters?|scattering|flutters?|fluttering|flickers?|flickering|dims?|dimming"
    r"|brightens?|brightening|spreads?|spreading|grows?|growing|falls?|falling|floats?"
    r"|floating|hovers?|hovering|tumbl(?:es|ing)|surg(?:es|ing)|whips?|whipping|ooz(?:es|ing)"
    r"|flows?|flowing|animat(?:es|ing)|mov(?:es|ing)|bur(?:ies|ying)|digs?|digging|hoes?"
    r"|hoeing|sways?|swaying|drifts?|drifting|ripples?|rippling|unfolds?|unfolding|settles?"
    r"|settling|lands?|landing|darkens?|darkening|collaps(?:es|ing)|crumbl(?:es|ing))\b",
    re.IGNORECASE,
)
# What the studio used to ask of the video model, and what the Owner saw (2026-10-11, films
# aa170155 and f06808c9): «barely moving», «remain perfectly still», «Background details
# remain stable». A motion prompt that says one of these asks for the stillness it then
# measures as a fault (MOTION_STILLNESS, a WARN: a plan may hold one object still on purpose).
STILLNESS_WORDS = re.compile(
    r"\b(?:barely|hardly|scarcely)\s+mov\w+\b|\bperfectly\s+still\b"
    r"|\b(?:remains?|remaining|stays?|staying|kept|keeps?)\s+(?:perfectly\s+|completely\s+"
    r"|entirely\s+)?(?:stable|still|motionless|frozen)\b|\bmotionless\b|\bunhurried\b"
    r"|\bno\s+(?:camera\s+)?movement\b|\bminimal\s+(?:camera\s+)?(?:movement|motion)\b",
    re.IGNORECASE,
)
# The compiler's own stillness sentences until 2026-10-11, as stored intents and prompts of
# the films planned before still carry them: `prompt_agent.render_motion` says a living world
# in their place when it renders a stored intent again, and `qc.stronger_motion_prompt` takes
# them out of a stored prompt before asking for the move more firmly.
LEGACY_STILLNESS = (
    "Background details remain stable throughout the shot.",
    "The movement stays smooth and unhurried.",
)

ENUM_CODE = re.compile(r"\b[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+\b")
HEX_CODE = re.compile(r"#(?:[0-9A-Fa-f]{6}|[0-9A-Fa-f]{3})\b")
TEMPLATE_LABEL = re.compile(
    r"(?:^|(?<=[.;\n]))\s*((?:Environment|Camera|Lighting|Composition|Motion|Style|Palette"
    r"|Subject|Action|Mood|Shot|Lens|Setting|Scene|Colou?rs?|Quality):)",
)
BLOCKING_LABELS = ("Camera:", "Motion:")
AVOID_LIST = re.compile(
    r"\b(?:Avoid|Negative(?:\s+prompt)?|Do\s+not\s+include|Don't\s+include|Exclude)\s*:",
    re.IGNORECASE,
)
INLINE_EXCLUSION = re.compile(r"\b(?:no|without)\s+[\w-]+", re.IGNORECASE)
QUOTED = re.compile(r"\"[^\"\n]{1,80}\"|“[^”\n]{1,80}”|„[^”\n]{1,80}”|(?<!\w)'[^'\n]{1,60}'(?!\w)")
THEN_CHAIN = re.compile(
    r"\bthen\b|\bnext,|\bafter\s+that\b|\bafterwards\b|\bfollowed\s+by\b", re.IGNORECASE
)
NEGATION = re.compile(r"\b(?:no|not|without|never|avoid|don't|do\s+not)\s+[\w-]+", re.IGNORECASE)

# A still is one moment, the first frame of its shot. Film babcf272 (2026-10-09), scene 5:
# the still prompt said "Glowing white spheres ... holding together as atoms, then the empty
# accelerator tunnel from scene 1. First the near-black void of scenes 2 and 3, then the
# identical tunnel from scene 1", and the image model drew all of it: three stacked panels
# in one 9:16 picture (tunnel with an atom, a flat black band, an empty tunnel), which the
# clip then animated. Every check passed it. These patterns say where a later moment begins
# and where a prompt points at another scene, which no image or video model can see.

#: Opens a later moment when it starts a clause: "finally", "later", "at the end" (not "at
#: the end of the corridor", which is a place), "moments later", "next" and "second(ly)"
#: (not "next to the window" or "the second floor": a place again).
_LATER_OPENER = (
    r"(?:(?:and|but)\s+)?(?:finally|eventually|later|afterwards?|in\s+the\s+end|at\s+last"
    r"|at\s+the\s+end(?!\s+of\s+(?:(?:the|this|a)\s+)?+"
    r"(?!(?:shot|scene|clip|sequence|film|video|moment)\b)\w)"
    r"|(?:(?:a|an|some|a\s+few|few|\d+)\s+)?(?:moments?|seconds?|minutes?|hours?|days?|weeks?"
    r"|months?|years?|decades?|centuries)\s+later|soon\s+after(?:wards?)?"
    r"|next(?!\s+(?:to|door)\b)|secondly|second(?=\s*,|\s+(?:the|a|an)\b))\b"
)
SEQUENCE_OPENER = re.compile(rf"^\s*{_LATER_OPENER}", re.IGNORECASE)
#: The same opener, or a "then", with the comma after it: what the compiler takes off a field
#: that opens with it ("Finally, the cluster settles" is said after the scene before).
LATER_START = re.compile(
    rf"^\s*(?:{_LATER_OPENER}|(?:and\s+)?then\b|after\s+that\b)\s*,?\s*", re.IGNORECASE
)
#: How a field says its first moment when a later one follows: "First the near-black void",
#: "First, the void" (a clause of its own once split at the comma), "Initially the void".
#: "First light" (dawn) and "First Nations" are pictures and stay.
_FIRST_WORDS = (
    r"(?:at\s+first|initially|in\s+the\s+beginning|to\s+begin(?:\s+with)?|first(?=\s*,"
    r"|\s+(?:the|a|an|its|their|his|her|our|this|that|these|those)\b))"
)
FIRST_OPENER = re.compile(
    rf"^(?:{_FIRST_WORDS}|first\s*$)\s*,?\s*",
    re.IGNORECASE,
)
_FIRST_IN_PROMPT = re.compile(rf"(?:^|(?<=[.;:!?,]))\s*{_FIRST_WORDS}", re.IGNORECASE)
#: A "then" chain as a still reads it. "Followed by" is where things stand in one picture
#: ("a mother elephant followed by her calf"), and "since then", "back then", "by then" are
#: about the past, not a later moment: the motion prompt's THEN_CHAIN keeps both.
STILL_THEN = re.compile(
    r"(?<!\bsince )(?<!\buntil )(?<!\btill )(?<!\bby )(?<!\bback )(?<!\beven )(?<!\bjust )"
    r"\bthen\b(?!-)|\bnext,|\bafter\s+that\b|\bafterwards\b",
    re.IGNORECASE,
)
#: A change over time inside one clause: "eventually", "dissolves into", "cuts to". Said in
#: the present only: "transformed into a museum", "replaced by palm oil plantations" and "the
#: transition to renewable energy" are how a place is now, one picture. "Fades into the
#: distance" and "gives way to" are left alone: landscapes are described that way.
LATER_MOMENT = re.compile(
    r"\b(?:eventually|finally)\b"
    r"|\b(?:dissolv(?:e|es|ing)|morph(?:s|ing)?|transform(?:s|ing))\s+(?:in)?to\b"
    r"|\b(?:cuts?|cutting)\s+(?:back\s+)?to\b",
    re.IGNORECASE,
)
#: The same, read across a whole prompt: an opener after a sentence or clause break.
_LATER_IN_PROMPT = re.compile(rf"(?:^|(?<=[.;:!?,]))\s*{_LATER_OPENER}", re.IGNORECASE)
_SCENE_NUMBER = r"(?:\d+|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve)"
#: Another scene by its number ("scene 1", "scenes 2 and 3", "scene 4's").
SCENE_NUMBERED = (
    rf"\bscenes?\s+(?:no\.?\s*|#\s*)?{_SCENE_NUMBER}\b"
    rf"(?:\s*(?:,|and|&|or|to|-|–)\s*{_SCENE_NUMBER}\b)*"
)
#: Another scene named by its number or by its place in the film ("the previous scene").
#: Not "the opening shot": a scene names itself that way ("The opening shot shows a glacier").
SCENE_REFERENCE = re.compile(
    rf"(?:{SCENE_NUMBERED}"
    r"|\b(?:previous|preceding|prior|earlier|next|following)\s+(?:scenes?|shots?)\b)(?:'s)?",
    re.IGNORECASE,
)
#: Words that ask an image model for several pictures in one frame: babcf272's scene 5 came
#: back as three stacked panels from a plain list of moments, and a plan that says "split
#: screen" or "Before: ... After: ..." asks for exactly that. "Side by side" alone, "solar
#: panels" and "a control panel" are things in one picture and stay.
PANEL_LAYOUT = re.compile(
    r"\bsplit[- ]?(?:screens?|frames?|images?|views?|panels?)\b"
    r"|\b(?:diptych|triptych|polyptych)s?\b"
    r"|\bbefore[- ]and[- ]after\b"
    r"|\bside[- ]by[- ]side\s+(?:comparisons?|views?|images?|pictures?|photos?|shots?|frames?"
    r"|panels?)\b"
    r"|\b(?:shown|seen|displayed|presented)\s+side[- ]by[- ]side\b"
    r"|\bphoto\s+collage\b|\bcollage\s+of\s+(?:images|photos|pictures|shots|scenes|views)\b"
    r"|\bmontage\b|\b(?:stacked|separate|comic|multiple|several)\s+panels\b"
    r"|\bpanels?\s+(?:\d+|one|two|three)\b"
    r"|\bpicture[- ]in[- ]picture\b|\binset\s+(?:images?|pictures?|photos?|shots?|frames?)\b",
    re.IGNORECASE,
)
_PANEL_LABEL_WORDS = (
    r"(?:before|after|top|bottom|upper|lower|left|right)"
    r"(?:\s+(?:half|third|panel|frame|image|side|part))?|panel\s*(?:\d+|one|two|three)"
)
#: A clause labelled as one picture of a layout: "Before:", "Top half:", "Panel 2:".
PANEL_LABEL = re.compile(rf"^\s*(?:{_PANEL_LABEL_WORDS})\s*:", re.IGNORECASE)
_PANEL_LABEL_IN_PROMPT = re.compile(
    rf"(?:^|(?<=[.;\n]))\s*((?:{_PANEL_LABEL_WORDS})\s*:)", re.IGNORECASE
)
#: The head of a broken sentence: a clause that ends in an article, a preposition, a
#: conjunction or "is" ("The film exists in two interconnected spaces: the", babcf272).
#: Lower-case "a" only, so "Plan A" stays whole. Read it through dangling().
#: A hyphenated compound that ends in one of these words is a whole word («straight-on»,
#: «head-on», «switched-on», «close-up», «drive-in»): 2026-10-15 19:03Z, 7c26a7ce scene 3,
#: «facing the viewer straight-on» was read as a clause breaking off at «on», and the Editor
#: was told to rewrite a whole sentence three rounds running.
DANGLING_END = re.compile(
    r"(?<!-)(?:\b(?i:the|an|of|in|on|at|to|and|or|with|from|by|for|is|are)|\ba)\s*$"
)
#: "In", "on" and "by" after a verb of motion are adverbs, and the clause is whole: "fog
#: rolling in", "clouds drift by", "the lamps switched on" are the world motion a clip wants.
_PARTICLE_END = re.compile(
    r"\b(?:(?:roll|drift|pass|sweep|creep|blow|sail|float|walk|stroll|rush|flood|pour|seep"
    r"|switch|turn|flick|click|look|pull|crowd|stream|wash|flash|roar|march|spill|kick|burst"
    r"|drop|lean|zoom|wander|sneak|glow|soak|crawl|ebb|swirl|swarm|sink|speed|fall|press"
    r"|push|hold|stand|spread|break|bring|step|light|run|set|hang)\w*"
    r"|(?:tumbl|trickl|rumbl|settl|glid|surg|clos|fad|mov|rac|rid|pil|wav|shin)(?:e|es|ed|ing)"
    r"|(?:hurr|carr)(?:y|ies|ied|ying)|com(?:e|es|ing)|go(?:es|ing|ne)?|fl(?:y|ies|ying|own)"
    r"|came|went|flew|blew|swept|crept|ran|rode|sped|slid|sank|broke|fell|held|stood|hung"
    r"|brought|lit)\s+(?:in|on|by)\s*$",
    re.IGNORECASE,
)


#: «stay exactly as they are», «the room as it is», «left where they were»: a clause that ends
#: in a form of «to be» after «as / how / where / what + pronoun» is whole, not broken.
#: 2026-10-15 19:43Z, 7c26a7ce scene 3: the Editor's whole sentence «… and the bench and the
#: equipment behind stay exactly as they are» was refused as a fragment three repairs running.
_WHOLE_END = re.compile(
    r"\b(?:as|how|where|what|the\s+way)\s+(?:they|it|she|he|we|you|things|everything)\s+"
    r"(?:are|is|were|was)\s*$",
    re.IGNORECASE,
)


def dangling(text: str) -> bool:
    """Whether a clause breaks off: it ends in a function word that needs what follows."""
    return (
        bool(DANGLING_END.search(text))
        and not _PARTICLE_END.search(text)
        and not _WHOLE_END.search(text)
    )


_ASIDE = re.compile(r"\s*\(([^()]*)\)")
#: The first word of a new phrase after an aside: a participle ("salvaging belongings",
#: "lined with magnets"), an article, a preposition, a conjunction. Nouns that end like a
#: participle ("ceiling", "building") are the phrase's own head word.
_PHRASE_START = re.compile(
    r"^(?:(?!(?:building|ceiling|clothing|railing|housing|lighting|painting|morning|evening"
    r"|opening|setting|crossing|dwelling|clearing|awning|landing|wedding|scaffolding|paving"
    r"|fencing|wiring|piping|mooring|string|spring|thing|wing|ring|king|swing)s?\b)"
    r"\w{2,}ing|\w{3,}ed|the|a|an|this|that|these|those|its|their|his|her|our|with|without"
    r"|in|on|at|by|for|from|to|of|into|onto|under|over|near|beside|behind|across|along"
    r"|through|and|or|but|as|while|where|which|who)\b",
    re.IGNORECASE,
)


def without_asides(text: str) -> str:
    """The text with the parenthetical asides that would break a clause closed up.

    Film babcf272 (2026-10-09): splitting a value at "(" left "The film exists in two
    interconnected spaces: the" in every still prompt, and "lined with (blue-painted)
    magnets" lost its tunnel. An aside after words that break off ("the (physical) tunnel",
    "located in (Geneva)") is opened, without its commas. An aside inside a phrase ("a
    controlled (indoor, climate-stable) space") is taken out: the phrase is whole again. An
    aside that ends a phrase ("debris (wooden beams, furniture)", "figures (farmer and child)
    salvaging ...") stays, and a clause split says it as clauses of its own, as it always
    has: the plan's details are kept. An unbalanced bracket stays too.
    """

    def close(match: re.Match[str]) -> str:
        if dangling(match.string[: match.start()]):
            opened = " ".join(re.sub(r"[,;]", " ", match.group(1)).split())
            return f" {opened}" if opened else ""
        after = match.string[match.end() :].lstrip()
        if after[:1].isalnum() and not _PHRASE_START.match(after):
            return ""
        return match.group(0)

    while True:
        closed = _ASIDE.sub(close, text)
        if closed == text:
            return text
        text = closed


#: A value that says there is nothing: the bible's weather "None" reached a still prompt.
NONE_WORD = re.compile(
    r"^\s*(?:none|null|nil|n/?a|not\s+applicable|not\s+specified|unspecified"
    r"|none\s+specified|tbd|-+)\s*[.!]?\s*$",
    re.IGNORECASE,
)

# Phrases that ask for something a photo or video generator cannot draw truthfully. They
# force the scene's kind: the Nepal bar chart (100 vs 83) and black screen became women.
KIND_PHRASES: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "DATA_CARD",
        re.compile(
            r"\bbar\s+(?:chart|graph)s?\b|\b(?:pie\s+)?charts?\b|\bgraphs?\b|\binfographics?\b"
            r"|\bdiagrams?\b|\b(?:vertical|horizontal)\s+bars?\b|\bbars\b|\bper\s?cent\b"
            r"|\d+(?:[.,]\d+)?\s?%",
            re.IGNORECASE,
        ),
    ),
    (
        "BLACK",
        re.compile(
            r"\bblack\s+(?:screen|frame)\b|\bfades?\s+(?:out\s+)?to\s+black\b|\bfade[- ]out\b"
            r"|\bscreen\s+(?:goes|turns|cuts\s+to)\s+black\b|\bcut\s+to\s+black\b",
            re.IGNORECASE,
        ),
    ),
    (
        "TITLE_CARD",
        re.compile(r"\btitle(?:\s+(?:card|screen))?\b|\bend\s+card\b", re.IGNORECASE),
    ),
)

PERSON = re.compile(
    r"\b(?:person|persons|people|man(?!-)|men|woman|women|farmers?|villagers?|child|children"
    r"|kids?|boys?|girls?|workers?|famil(?:y|ies)|crowds?|mothers?|fathers?|elders?"
    r"|residents?|officials?|protesters?|students?|herders?|porters?|sherpas?|climbers?"
    r"|victims?|survivors?|rescuers?|volunteers?|locals|figures?(?!\s*\d)|pedestrians?"
    r"|shepherds?|monks?|laborers?|labourers?|refugees?|citizens?|soldiers?|nurses?"
    r"|doctors?|fishermen|fisherman|traders?|vendors?)\b",
    re.IGNORECASE,
)
FACE_HIDDEN = re.compile(
    r"\bfrom\s+behind\b|\bfrom\s+(?:high\s+)?above\b|\bsilhouett\w*|\bdistant\b"
    r"|\bin\s+the\s+distance\b|\bfar\s+away\b|\bhands\s+only\b|\bonly\s+(?:their\s+|his\s+"
    r"|her\s+)?hands\b|\bbacks?\s+to\s+the\s+camera\b|\bfaces?\s+(?:not\s+visible|hidden"
    r"|obscured|turned\s+away|out\s+of\s+frame)\b|\bno\s+(?:visible\s+)?faces?\b|\bfaceless\b",
    re.IGNORECASE,
)
FACE_SHOWN = re.compile(
    r"\b(?:faces?|facial\s+expressions?)\s+(?:clearly\s+)?(?:visible|shown|in\s+focus)\b"
    r"|\bclose[- ]?up\s+(?:of|on)\s+(?:a\s+|the\s+|his\s+|her\s+|their\s+)?faces?\b"
    r"|\blooking\s+(?:at|into)\s+the\s+(?:camera|lens)\b|\bportraits?\b|\bsmiling\b"
    r"|\bfacial\s+expressions?\b|\bfaces?\s+close[- ]?up\b",
    re.IGNORECASE,
)
# The prompt says outright that no face is seen.
NO_FACE_STATED = re.compile(
    r"\bno\s+(?:human\s+|visible\s+)?faces?\b|\bfaces?\s+(?:not\s+visible|hidden|obscured"
    r"|turned\s+away|out\s+of\s+frame|never\s+visible)\b|\bfaceless\b"
    r"|\bwithout\s+(?:visible\s+|human\s+)?faces\b|\bno\s+(?:people|person|figures|humans)\b"
    r"|\bempty\s+of\s+people\b|\bunpeopled\b"
    # The compiler's positive sentence for a scene of objects (2026-10-12,
    # `prompt_agent.NO_PEOPLE_SENTENCE`): the rule kept without a word for a person.
    r"|\bholds\s+only\s+the\s+place\s+and\s+the\s+things\s+named\b",
    re.IGNORECASE,
)
# A bible rule (continuity rule or avoid item) that forbids faces.
BIBLE_NO_FACES = re.compile(
    r"\bno\s+(?:human\s+|visible\s+|recogni[sz]able\s+)?faces?\b|\bfaceless\b"
    r"|\bfaces?\s+(?:never|must\s+not|should\s+not|do\s+not|don't)\s+(?:appear|be\s+(?:visible"
    r"|shown|seen))\b|\bwithout\s+(?:human\s+)?faces\b",
    re.IGNORECASE,
)
# Explicitly contradictory first-frame geometry, not an AI aesthetic judgement.
# These narrow checks prevent paying for physically impossible compositions; unrelated
# back views and visible faces remain fully allowed.
_BACK_TO_CAMERA = re.compile(
    r"\b(?:seen|shown|viewed|filmed)\s+(?:only\s+)?from\s+behind\b"
    r"|\b(?:their|his|her|the)\s+backs?\s+to\s+(?:the\s+)?camera\b",
    re.IGNORECASE,
)
_MEDAL_AT_FRONT = re.compile(
    r"\bmedals?\b[^.!?;]{0,100}\b(?:at|on|over|across)\s+"
    r"(?:their|his|her|the)\s+(?:chests?|fronts?|lapels?)\b",
    re.IGNORECASE,
)
_REFLECTED_FRONT = re.compile(r"\b(?:mirror|reflection|reflected)\b", re.IGNORECASE)
_VACUUM_SPACE = re.compile(
    r"\b(?:pure\s+vacuum|deep\s+space|intergalactic\s+(?:space|void)"
    r"|void\s+black|unbroken\s+darkness)\b",
    re.IGNORECASE,
)
_TERRESTRIAL_CAMERA = re.compile(
    r"\b(?:ground|road)\s+(?:sliding|moving|rolling|passing)\s+beneath\b"
    r"|\bhorizon\s+(?:opening|rising|extending)\s+ahead\b",
    re.IGNORECASE,
)
_REAL_SURFACE = re.compile(
    r"\b(?:earth(?:'s)?|planet(?:ary)?|moon|landscape|terrain|surface)\b",
    re.IGNORECASE,
)
_NO_SURFACE = re.compile(
    r"\b(?:no|without|lacking)\s+(?:an?\s+|the\s+|visible\s+)?"
    r"(?:ground|planet|moon|surface|terrain)"
    r"(?:\s+(?:or|and)\s+(?:ground|planet|moon|surface|terrain))*\b",
    re.IGNORECASE,
)
_TEMPORAL_STILL = re.compile(
    r"\b(?:brightens?\s+and\s+dims?|dims?\s+and\s+brightens?"
    r"|pulses?\s+and\s+fades?)\b",
    re.IGNORECASE,
)

BIBLE_AVOID_FACES = re.compile(
    r"^\s*(?:visible\s+|human\s+|recogni[sz]able\s+|any\s+)*faces?(?:\s+visible)?\s*$",
    re.IGNORECASE,
)

KIND_RO = {
    "DATA_CARD": "grafic (DATA_CARD)",
    "TITLE_CARD": "titlu (TITLE_CARD)",
    "BLACK": "ecran negru (BLACK)",
}
WHERE_RO = {"still": "imaginii", "motion": "de mișcare"}


@dataclass(frozen=True)
class Finding:
    """One thing wrong with a prompt, told to the Owner in Romanian."""

    code: str
    severity: str
    scene: int | None
    evidence: str
    message_ro: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "severity": self.severity,
            "scene": self.scene,
            "evidence": self.evidence,
            "message_ro": self.message_ro,
        }


@dataclass(frozen=True)
class LintScene:
    """A scene as the linter sees it: its kind and the two prompts that would be sent."""

    scene: int
    kind: str = LIVE
    still_prompt: str = ""
    motion_prompt: str = ""
    model_id: str | None = None
    contract: Mapping[str, Any] | None = None
    composition_issues: tuple[str, ...] = ()


class PromptLintBlocked(Exception):
    """Raised by require_no_block: a BLOCK finding is open, nothing may be priced or bought."""

    def __init__(self, findings: Sequence[Finding]) -> None:
        self.findings = [f for f in findings if f.severity == BLOCK]
        super().__init__(summary_ro(self.findings))


# --- helpers ---------------------------------------------------------------------------------


def utf16_units(text: str) -> int:
    """Length as the vendors count it (JavaScript string length)."""
    return len(text.encode("utf-16-le")) // 2


def _index_at_units(text: str, limit: int) -> int:
    """The character index where the first UTF-16 unit past `limit` begins."""
    used = 0
    for index, char in enumerate(text):
        used += 2 if ord(char) > 0xFFFF else 1
        if used > limit:
            return index
    return len(text)


def _words(text: str) -> int:
    return len(text.split())


def _excerpt(text: str, limit: int = EVIDENCE_CHARS) -> str:
    """A verbatim prefix of the text: its first sentence, cut at a whole word."""
    stripped = text.strip()
    first = re.split(r"(?<=[.!?])\s", stripped, maxsplit=1)[0]
    if len(first) <= limit:
        return first
    cut = first.rfind(" ", 0, limit)
    return first[: cut if cut > 0 else limit]


def _last_sentence(text: str) -> str:
    parts = [p for p in re.split(r"(?<=[.!?])\s+", text.strip()) if p.strip()]
    return parts[-1] if parts else text.strip()


def _norm(text: str) -> str:
    return " ".join(text.lower().split())


def _distinct(matches: Iterable[str]) -> list[str]:
    seen: list[str] = []
    for match in matches:
        if match not in seen:
            seen.append(match)
    return seen


def _others(values: list[str], shown: int = 3) -> str:
    """Romanian tail naming the other offending values, e.g. ' (și încă: „A”, „B”)'."""
    rest = values[1:]
    if not rest:
        return ""
    listed = ", ".join(f"„{value}”" for value in rest[:shown])
    more = (
        f" și {count_ro(len(rest) - shown, 'altă valoare', 'alte valori')}"
        if len(rest) > shown
        else ""
    )
    return f" (și încă: {listed}{more})"


def model_family(model_id: str | None) -> str | None:
    if not model_id:
        return None
    lowered = model_id.lower()
    for family in ("veo", "seedance", "wan", "gen4", "seedream"):
        if lowered.startswith(family):
            return family
    return None


def _prompt_limit(contract: Mapping[str, Any] | None, target: str) -> tuple[int, bool]:
    """(allowance, measured in characters): explicit terms, the route's declared allowance
    (`ALLOWANCES`), legacy Runway."""
    if not contract:
        return DEFAULT_PROMPT_MAX_UTF16, False
    for key in ("prompt_max_utf16", "prompt_max_chars", "prompt_max"):
        value = contract.get(key)
        if isinstance(value, bool):
            continue
        if isinstance(value, int) and value > 0:
            return value, key == "prompt_max_chars"
        if isinstance(value, Mapping):
            task = "text_to_image" if target == "still" else "image_to_video"
            chosen = value.get(task)
            if isinstance(chosen, int) and not isinstance(chosen, bool) and chosen > 0:
                return chosen, key == "prompt_max_chars"
            numbers = [
                v
                for v in value.values()
                if isinstance(v, int) and not isinstance(v, bool) and v > 0
            ]
            if numbers:
                return min(numbers), key == "prompt_max_chars"
    model_id = contract.get("still_model_id") if target == "still" else None
    model_id = model_id or contract.get("model_id") or contract.get("model")
    if isinstance(model_id, str) and model_id in ALLOWANCES:
        return ALLOWANCES[model_id], True
    return DEFAULT_PROMPT_MAX_UTF16, False


def prompt_cap(contract: Mapping[str, Any] | None, target: str) -> int:
    """The explicit vendor allowance or the selected route's declared request limit."""
    return _prompt_limit(contract, target)[0]


def _sequence_in(text: str) -> str:
    """The earliest words of a still prompt that begin a later moment, else ""."""
    found = [
        (match.start(), match.group(0).strip(" .;:!?,"))
        for pattern in (STILL_THEN, LATER_MOMENT, _LATER_IN_PROMPT, _FIRST_IN_PROMPT)
        for match in [pattern.search(text)]
        if match and match.group(0).strip(" .;:!?,")
    ]
    return min(found)[1] if found else ""


def _panels_in(text: str) -> str:
    """The earliest words of a still prompt that ask for several pictures in one, else ""."""
    found = [
        (match.start(), match.group(match.lastindex or 0).strip())
        for pattern in (PANEL_LAYOUT, _PANEL_LABEL_IN_PROMPT)
        for match in [pattern.search(text)]
        if match
    ]
    return min(found)[1] if found else ""


def classify_kind_phrase(text: str) -> tuple[str, str] | None:
    """(kind, evidence) for the earliest phrase that forces a composed scene, else None."""
    best: tuple[int, str, str] | None = None
    for kind, pattern in KIND_PHRASES:
        match = pattern.search(text)
        if match and (best is None or match.start() < best[0]):
            best = (match.start(), kind, match.group(0))
    if best is None:
        return None
    return best[1], best[2]


def bible_face_rule(bible: Mapping[str, Any] | None) -> str | None:
    """Return an intentional no-visible-faces rule, never a blanket platform ban.

    Explicit ALLOW/REQUIRE override legacy generated "no faces" prose. Explicit HIDE
    preserves the restriction even if the bible does not repeat it in words.
    Bibles without a policy keep their previous semantics: old films are not silently
    reinterpreted in the middle of a paid production.
    """
    if not isinstance(bible, Mapping):
        return None
    policy = str(bible.get("face_policy") or "").strip().upper()
    if policy in ("ALLOW", "REQUIRE"):
        return None
    rules: list[str] = []
    for key in ("continuity_rules", "rules", "people_rule"):
        value = bible.get(key)
        if isinstance(value, str):
            rules.append(value)
        elif isinstance(value, (list, tuple)):
            rules.extend(str(item) for item in value if item)
    for rule in rules:
        if BIBLE_NO_FACES.search(rule):
            return rule
    avoid = bible.get("avoid")
    if isinstance(avoid, (list, tuple)):
        for item in avoid:
            text = str(item)
            if BIBLE_AVOID_FACES.match(text) or BIBLE_NO_FACES.search(text):
                return text
    if policy == "HIDE":
        return "Faces must not be visible (explicit face_policy: HIDE)"
    return None


def camera_moves(text: str) -> list[tuple[str, str]]:
    """Distinct camera moves named in a motion prompt, as (enum value, text as written)."""
    found: list[tuple[int, str, str]] = []
    for move, pattern in CAMERA_MOVES.items():
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            found.append((match.start(), move, match.group(0).strip()))
    found.sort()
    return [(move, written) for _, move, written in found]


def shot_size(text: str) -> tuple[str, str] | None:
    """(size, text as written) of the first shot size the still prompt names."""
    match = SHOT_SIZE.search(text)
    if not match:
        return None
    size = " ".join(match.group(1).lower().replace("close up", "close-up").split())
    return size, match.group(0)


def _person_mentions(text: str) -> list[tuple[str, bool]]:
    """Each person the prompt shows, and whether its face is kept out of sight nearby."""
    mentions: list[tuple[str, bool]] = []
    for sentence in re.split(r"(?<=[.!?;])\s+", text):
        words = list(re.finditer(r"\S+", sentence))
        for match in PERSON.finditer(sentence):
            before = sentence[max(0, match.start() - 16) : match.start()].lower()
            if re.search(r"\b(?:no|without|not\s+a|zero)\s+(?:\w+\s+)?$", before):
                continue
            index = next(
                (i for i, word in enumerate(words) if word.start() <= match.start() < word.end()),
                0,
            )
            start = words[max(0, index - 3)].start()
            end = words[min(len(words) - 1, index + 6)].end()
            window = sentence[start:end]
            mentions.append((match.group(0), bool(FACE_HIDDEN.search(window))))
    return mentions


def _finding(code: str, severity: str, scene: int | None, evidence: str, message: str) -> Finding:
    return Finding(
        code=code, severity=severity, scene=scene, evidence=evidence.strip(), message_ro=message
    )


# --- checks shared by both prompts -----------------------------------------------------------


def _hygiene(
    text: str, scene: int | None, target: str, cap: int, *, characters: bool = False
) -> list[Finding]:
    where = WHERE_RO[target]
    findings: list[Finding] = []

    codes = _distinct(match.group(0) for match in ENUM_CODE.finditer(text))
    if codes:
        findings.append(
            _finding(
                "ENUM_CODE",
                BLOCK,
                scene,
                codes[0],
                f"Promptul {where} conține codul intern „{codes[0]}”{_others(codes)}. "
                "Modelul nu înțelege coduri; scrieți în cuvinte ce trebuie să se vadă.",
            )
        )

    hexes = _distinct(match.group(0) for match in HEX_CODE.finditer(text))
    if hexes:
        findings.append(
            _finding(
                "HEX_CODE",
                BLOCK,
                scene,
                hexes[0],
                f"Promptul {where} conține culoarea în cod hex „{hexes[0]}”{_others(hexes)}. "
                "Modelul nu citește coduri de culoare; numiți culorile în cuvinte.",
            )
        )

    labels = _distinct(match.group(1) for match in TEMPLATE_LABEL.finditer(text))
    if labels:
        blocking = any(label in BLOCKING_LABELS for label in labels)
        findings.append(
            _finding(
                "TEMPLATE_LABEL",
                BLOCK if blocking else WARN,
                scene,
                labels[0],
                f"Promptul {where} are rubrica de șablon „{labels[0]}”{_others(labels)}. "
                "Scrieți o descriere firească, în fraze, fără rubrici.",
            )
        )

    avoid = AVOID_LIST.search(text)
    if avoid:
        findings.append(
            _finding(
                "AVOID_LIST",
                BLOCK,
                scene,
                avoid.group(0),
                f"Promptul {where} are o listă de interdicții „{avoid.group(0)}”. "
                "Modelele desenează adesea tocmai ce li se interzice; spuneți ce trebuie "
                "să apară.",
            )
        )

    quoted = QUOTED.search(text)
    if quoted:
        findings.append(
            _finding(
                "QUOTED_TEXT",
                BLOCK,
                scene,
                quoted.group(0),
                f"Promptul {where} conține text între ghilimele „{quoted.group(0)}”. "
                "Modelul îl va scrie pe imagine; descrieți scena fără citate.",
            )
        )

    units = len(text) if characters else utf16_units(text)
    if units > cap:
        overflow = text[cap if characters else _index_at_units(text, cap) :]
        shown = _excerpt(overflow, 60)
        measure = "caractere" if characters else "unități"
        findings.append(
            _finding(
                "OVER_CAP",
                BLOCK,
                scene,
                overflow,
                f"Promptul {where} are {units} {measure}, peste limita de {cap} a modelului. "
                f"Partea care nu încape începe cu „{shown}”. Promptul nu se taie: "
                "se rescrie mai scurt.",
            )
        )
    return findings


# --- the still prompt ------------------------------------------------------------------------


def lint_still_prompt(
    text: str,
    *,
    scene: int | None,
    bible: Mapping[str, Any] | None = None,
    contract: Mapping[str, Any] | None = None,
    kind: str = LIVE,
) -> list[Finding]:
    """Findings for the prompt sent to the image model for one LIVE scene."""
    cap, characters = _prompt_limit(contract, "still")
    findings = _hygiene(text, scene, "still", cap, characters=characters)

    exclusions = [match.group(0) for match in INLINE_EXCLUSION.finditer(text)]
    if len(exclusions) > MAX_INLINE_EXCLUSIONS:
        findings.append(
            _finding(
                "TOO_MANY_EXCLUSIONS",
                WARN,
                scene,
                exclusions[MAX_INLINE_EXCLUSIONS],
                f"Promptul imaginii are {count_ro(len(exclusions), 'excludere', 'excluderi')}; "
                f"sunt permise cel mult "
                f"{MAX_INLINE_EXCLUSIONS}. Prima în plus: „{exclusions[MAX_INLINE_EXCLUSIONS]}”. "
                "Spuneți pozitiv ce se vede.",
            )
        )

    if kind == LIVE:
        forced = classify_kind_phrase(text)
        if forced:
            forced_kind, evidence = forced
            findings.append(
                _finding(
                    "KIND_MISMATCH",
                    BLOCK,
                    scene,
                    evidence,
                    f"Scena filmată cere „{evidence}”, ceea ce un generator de imagini nu "
                    f"desenează corect. Se compune local, gratuit, ca {KIND_RO[forced_kind]}.",
                )
            )

    # WARN, not BLOCK: a BLOCK on a stored prompt makes the sheet LINT_BLOCKED, and the sheet
    # repair then rewrites every scene's package, which would orphan takes already bought.
    # The compiler is what keeps a still to one moment; this tells the Owner when it did not.
    sequence = _sequence_in(text)
    if sequence:
        findings.append(
            _finding(
                "STILL_SEQUENCE",
                WARN,
                scene,
                sequence,
                f"Promptul imaginii înșiră mai multe momente („{sequence}”). O imagine este "
                "un singur moment, primul cadru al planului: cu „apoi” modelul de imagine "
                "desenează mai multe tablouri într-unul, ca panouri suprapuse. Descrieți doar "
                "primul moment.",
            )
        )
    panels = _panels_in(text)
    if panels:
        findings.append(
            _finding(
                "STILL_PANELS",
                WARN,
                scene,
                panels,
                f"Promptul imaginii cere mai multe tablouri într-o singură imagine („{panels}”): "
                "ecran împărțit, „înainte și după” sau panouri. Modelul de imagine le desenează "
                "suprapuse în cadrul vertical. O imagine este un singur moment: descrieți doar "
                "primul tablou.",
            )
        )
    pointer = SCENE_REFERENCE.search(text)
    if pointer:
        findings.append(
            _finding(
                "SCENE_REFERENCE",
                WARN,
                scene,
                pointer.group(0),
                f"Promptul imaginii trimite la altă scenă („{pointer.group(0)}”). Modelul de "
                "imagine nu știe cum arată „scena N” și poate desena mai multe tablouri "
                "într-unul; descrieți locul în cuvinte.",
            )
        )
    # WARN, as STILL_SEQUENCE: the compiler keeps movement out of the still (2026-10-13); this
    # tells the Owner when a stored prompt still carries a camera move, a tempo or a span.
    moving = still_motion(text)
    if moving:
        findings.append(
            _finding(
                "STILL_MOTION",
                WARN,
                scene,
                moving,
                f"Promptul imaginii cere mișcare („{moving}”). O imagine este un singur moment "
                "nemișcat: mișcarea camerei, tempoul și durata clipului se spun doar în "
                "promptul de mișcare. Descrieți ce se vede în acel moment.",
            )
        )

    # A front-of-chest medal cannot be visible on someone explicitly shown only
    # from behind, unless a reflection is deliberately part of the shot.
    back = _BACK_TO_CAMERA.search(text)
    medal = _MEDAL_AT_FRONT.search(text)
    if back and medal and not _REFLECTED_FRONT.search(text):
        findings.append(
            _finding(
                "PHYSICAL_MEDAL_ORIENTATION",
                BLOCK,
                scene,
                medal.group(0),
                "Promptul imaginii cere oameni văzuți din spate, dar medalii vizibile "
                "la piept/în față. Poziționați camera în față sau la trei sferturi "
                "ori descrieți o compoziție fizic coerentă înainte de generare.",
            )
        )
    temporal = _TEMPORAL_STILL.search(text)
    if temporal:
        findings.append(
            _finding(
                "STILL_TEMPORAL_CHANGE",
                WARN,
                scene,
                temporal.group(0),
                "Promptul imaginii descrie o schimbare în timp. Păstrați în imagine "
                "o singură stare a luminii și descrieți variația în promptul video.",
            )
        )

    rule = bible_face_rule(bible)
    if rule:
        persons = _person_mentions(text)
        shown = FACE_SHOWN.search(text)
        if shown:
            findings.append(
                _finding(
                    "FORBIDDEN_FACES",
                    BLOCK,
                    scene,
                    shown.group(0),
                    f"Promptul imaginii cere o față vizibilă („{shown.group(0)}”), deși biblia "
                    "vizuală interzice fețele.",
                )
            )
        for person, hidden in persons:
            if not hidden:
                findings.append(
                    _finding(
                        "FORBIDDEN_FACES",
                        BLOCK,
                        scene,
                        person,
                        f"Promptul imaginii arată un om („{person}”) fără să-i ascundă fața, "
                        "deși biblia vizuală interzice fețele. Adăugați lângă el „from behind”, "
                        "„distant”, „silhouette”, „seen from above” sau „hands only”.",
                    )
                )
        carried = bool(NO_FACE_STATED.search(text)) or (
            bool(persons) and not shown and all(hidden for _, hidden in persons)
        )
        if not carried:
            findings.append(
                _finding(
                    "BIBLE_RULE_MISSING",
                    BLOCK,
                    scene,
                    rule,
                    f"Biblia vizuală cere „{rule}”, dar promptul imaginii nu o spune, iar "
                    "modelul adaugă oameni cu fețe. Scrieți-o pozitiv, de exemplu „figures "
                    "small and distant, seen from behind, faces not visible”.",
                )
            )

    count = _words(text)
    low, high = STILL_WORDS
    if text.strip() and not low <= count <= high:
        findings.append(
            _finding(
                "STILL_LENGTH",
                WARN,
                scene,
                _excerpt(text),
                f"Promptul imaginii are {count_ro(count, 'cuvânt', 'cuvinte')} "
                f"(„{_excerpt(text, 60)}”); "
                f"lungimea potrivită este {low}–{high}.",
            )
        )
    return findings


# --- the motion prompt -----------------------------------------------------------------------


def lint_motion_prompt(
    text: str,
    *,
    scene: int | None,
    still_prompt: str = "",
    model_id: str | None = None,
    contract: Mapping[str, Any] | None = None,
) -> list[Finding]:
    """Findings for the promptText sent with the approved still to the video model."""
    cap, characters = _prompt_limit(contract, "motion")
    findings = _hygiene(text, scene, "motion", cap, characters=characters)
    # Catch a concrete terrestrial camera move pasted into a vacuum scene.
    # Do not infer an Earth horizon from astronomy words alone; an explicit
    # planet, moon or landscape in the planned still makes the move legitimate.
    ground = _TERRESTRIAL_CAMERA.search(text)
    if (
        ground
        and _VACUUM_SPACE.search(still_prompt)
        and not _REAL_SURFACE.search(_NO_SURFACE.sub("", still_prompt))
    ):
        findings.append(
            _finding(
                "PHYSICAL_COSMIC_GROUND",
                BLOCK,
                scene,
                ground.group(0),
                "Mișcarea cere sol/orizont terestru sub cameră, dar imaginea "
                "descrie vid cosmic fără suprafață. Descrieți deplasarea camerei "
                "printre filamente/galaxii, fără elemente de pe Pământ.",
            )
        )
    family = model_family(model_id)
    model_name = model_id or "modelul video"

    equals = (
        bool(still_prompt.strip()) and bool(text.strip()) and _norm(text) in _norm(still_prompt)
    )
    if equals:
        findings.append(
            _finding(
                "MOTION_EQUALS_STILL",
                BLOCK,
                scene,
                _excerpt(text),
                f"Promptul de mișcare repetă textul imaginii („{_excerpt(text, 80)}”). "
                "Modelul video vede deja imaginea; descrieți doar mișcarea camerei și a "
                "mediului.",
            )
        )
    elif still_prompt.strip() and text.strip():
        motion_words = _content_words(_strip_closing(text))
        still_words = _content_words(still_prompt)
        shared = [word for word in motion_words if word in still_words]
        if motion_words and len(shared) / len(motion_words) > 0.6:
            listed = ", ".join(shared[:6])
            findings.append(
                _finding(
                    "MOTION_REDESCRIBES",
                    WARN,
                    scene,
                    listed,
                    f"Promptul de mișcare redescrie imaginea (cuvinte comune: „{listed}”). "
                    "Spuneți doar ce se mișcă.",
                )
            )

    moves = camera_moves(text)
    if len(moves) != 1:
        if moves:
            evidence = ", ".join(written for _, written in moves)
            message = (
                "Promptul de mișcare are "
                f"{count_ro(len(moves), 'mișcare de cameră', 'mișcări de cameră')} "
                f"(„{evidence}”); "
                "este permisă exact una."
            )
        else:
            evidence = _excerpt(text) or "prompt gol"
            message = (
                f"Promptul de mișcare nu are nicio mișcare de cameră („{_excerpt(text, 60)}”). "
                "Alegeți exact una: " + ", ".join(CAMERA_MOVES) + "."
            )
        findings.append(_finding("CAMERA_COUNT", BLOCK, scene, evidence, message))

    if family != "veo":
        chain = THEN_CHAIN.search(text)
        if chain:
            severity = BLOCK if family == "seedance" else WARN
            findings.append(
                _finding(
                    "THEN_CHAIN",
                    severity,
                    scene,
                    chain.group(0),
                    f"Promptul de mișcare înșiră acțiuni cu „{chain.group(0)}”. Pe "
                    f"{model_name} un clip trebuie să fie o singură mișcare continuă.",
                )
            )

    if family == "veo":
        negation = NEGATION.search(text)
        if negation:
            findings.append(
                _finding(
                    "NEGATION_IN_PROMPT",
                    BLOCK,
                    scene,
                    negation.group(0),
                    f"Pe {model_name} promptul nu poate conține negații („{negation.group(0)}”); "
                    "interdicțiile merg în negativePrompt, ca substantive simple.",
                )
            )

    if text.strip():
        closing = VEO_MOTION_CLOSING if family == "veo" else MOTION_CLOSING
        if not _norm(text).endswith(_norm(closing)):
            ending = _last_sentence(text)
            findings.append(
                _finding(
                    "MOTION_CLOSING",
                    WARN,
                    scene,
                    ending,
                    f"Promptul de mișcare se încheie cu „{_excerpt(ending, 60)}” în loc de "
                    f"„{closing}”.",
                )
            )
        if not SPEED_WORDS.search(text):
            findings.append(
                _finding(
                    "MOTION_SPEED",
                    WARN,
                    scene,
                    _excerpt(text),
                    f"Promptul de mișcare nu spune viteza („{_excerpt(text, 60)}”); adăugați "
                    "un singur cuvânt, de exemplu slow sau gentle.",
                )
            )
        if not ENVIRONMENT_MOTION.search(_strip_closing(text)):
            findings.append(
                _finding(
                    "MOTION_ENVIRONMENT",
                    WARN,
                    scene,
                    _excerpt(text),
                    "Promptul de mișcare nu are nicio mișcare a mediului "
                    f"(„{_excerpt(text, 60)}”): nori care trec, vânt în iarbă, "
                    "apă care curge, praf.",
                )
            )
        stillness = STILLNESS_WORDS.search(_strip_closing(text))
        if stillness:
            findings.append(
                _finding(
                    "MOTION_STILLNESS",
                    WARN,
                    scene,
                    stillness.group(0),
                    f"Promptul de mișcare cere nemișcare („{stillness.group(0)}”). Modelul "
                    "face exact ce i se cere: un clip aproape static. Spuneți ce se mișcă, "
                    "cu drum și ritm.",
                )
            )
        count = _words(text)
        low, high = MOTION_WORDS
        if not low <= count <= high:
            findings.append(
                _finding(
                    "MOTION_LENGTH",
                    WARN,
                    scene,
                    _excerpt(text),
                    f"Promptul de mișcare are {count_ro(count, 'cuvânt', 'cuvinte')} "
                    f"(„{_excerpt(text, 60)}”); "
                    f"lungimea potrivită este {low}–{high}.",
                )
            )
    return findings


STOP_WORDS = frozenset(
    "a an the and or of to in on at with from for by as is are its it this that while into "
    "over under through across toward towards very".split()
)


def _content_words(text: str) -> list[str]:
    words = [w.lower() for w in re.findall(r"[A-Za-z][A-Za-z-]+", text)]
    return _distinct(w for w in words if w not in STOP_WORDS and len(w) > 2)


def _strip_closing(text: str) -> str:
    stripped = text.strip()
    for closing in (MOTION_CLOSING, VEO_MOTION_CLOSING):
        if _norm(stripped).endswith(_norm(closing)):
            return stripped[: len(stripped) - len(closing)].strip()
    return stripped


# --- the whole film --------------------------------------------------------------------------


def lint_scene(
    scene: LintScene,
    *,
    bible: Mapping[str, Any] | None = None,
    contract: Mapping[str, Any] | None = None,
) -> list[Finding]:
    """Findings for one scene: its kind, then its prompts if it is filmed."""
    kind = (scene.kind or "").upper()
    terms = dict(scene.contract if scene.contract is not None else contract or {})
    if scene.model_id:
        terms.setdefault("model_id", scene.model_id)
    if kind not in SCENE_KINDS:
        return [
            _finding(
                "KIND_UNKNOWN",
                BLOCK,
                scene.scene,
                scene.kind or "(gol)",
                f"Scena are un tip necunoscut „{scene.kind or '(gol)'}”; se acceptă doar "
                "LIVE, DATA_CARD, TITLE_CARD și BLACK.",
            )
        ]
    if kind != LIVE:
        paid = scene.still_prompt.strip() or scene.motion_prompt.strip()
        if not paid:
            return []
        return [
            _finding(
                "CARD_HAS_PROMPT",
                BLOCK,
                scene.scene,
                _excerpt(paid),
                f"Scena {scene.scene} este {KIND_RO[kind]} și se compune local, gratuit, dar "
                f"are un prompt pentru generator („{_excerpt(paid, 60)}”). Un card nu ajunge "
                "niciodată la un model plătit.",
            )
        ]
    findings: list[Finding] = []
    for issue in scene.composition_issues:
        findings.append(_finding("REQUIRED_CONTENT_LOST", BLOCK, scene.scene, issue, issue))
    if not scene.still_prompt.strip():
        findings.append(
            _finding(
                "PROMPT_MISSING",
                BLOCK,
                scene.scene,
                "prompt gol",
                f"Scena filmată {scene.scene} nu are promptul imaginii („prompt gol”).",
            )
        )
    else:
        findings += lint_still_prompt(
            scene.still_prompt, scene=scene.scene, bible=bible, contract=terms, kind=kind
        )
    if scene.motion_prompt.strip():
        findings += lint_motion_prompt(
            scene.motion_prompt,
            scene=scene.scene,
            still_prompt=scene.still_prompt,
            model_id=scene.model_id,
            contract=terms,
        )
    return findings


def lint_film(
    scenes: Sequence[LintScene],
    *,
    bible: Mapping[str, Any] | None = None,
    contract: Mapping[str, Any] | None = None,
) -> list[Finding]:
    """Every scene's findings, then the film's camera language across its LIVE scenes."""
    findings: list[Finding] = []
    for scene in scenes:
        findings += lint_scene(scene, bible=bible, contract=contract)
    live = [scene for scene in scenes if (scene.kind or "").upper() == LIVE]
    moves: list[tuple[int, str, str] | None] = []
    sizes: list[tuple[int, str, str] | None] = []
    for scene in live:
        found = camera_moves(scene.motion_prompt) if scene.motion_prompt.strip() else []
        moves.append((scene.scene, found[0][0], found[0][1]) if len(found) == 1 else None)
        size = shot_size(scene.still_prompt)
        sizes.append((scene.scene, size[0], size[1]) if size else None)
    findings += _camera_language(moves, "mișcare de cameră")
    findings += _camera_language(sizes, "încadrare")
    return findings


def _camera_language(
    values: list[tuple[int, str, str] | None], what: str, run_length: int = 3
) -> list[Finding]:
    if len(values) >= run_length and all(values):
        kinds = {value[1] for value in values if value}
        if len(kinds) == 1:
            first = values[0]
            assert first is not None
            return [
                _finding(
                    "SAME_CAMERA_EVERY_SCENE",
                    WARN if first[1] == "static" else BLOCK,
                    None,
                    first[2],
                    "Toate cele "
                    f"{count_ro(len(values), 'scenă filmată', 'scene filmate')} au aceeași "
                    f"{what} („{first[2]}”). "
                    "Filmul pare o singură imagine; variați încadrarea și mișcarea.",
                )
            ]
    findings: list[Finding] = []
    index = 0
    while index < len(values):
        current = values[index]
        end = index + 1
        while (
            current is not None
            and end < len(values)
            and values[end] is not None
            and values[end][1] == current[1]  # type: ignore[index]
        ):
            end += 1
        if current is not None and end - index >= run_length:
            last = values[end - 1]
            assert last is not None
            findings.append(
                _finding(
                    "SAME_CAMERA_RUN",
                    WARN,
                    current[0],
                    current[2],
                    f"Scenele {current[0]}–{last[0]} au la rând aceeași {what} "
                    f"(„{current[2]}”). Variați-o cel puțin o dată la trei scene.",
                )
            )
        index = end
    return findings


# --- the gate --------------------------------------------------------------------------------


def has_block(findings: Iterable[Finding]) -> bool:
    return any(finding.severity == BLOCK for finding in findings)


def summary_ro(findings: Sequence[Finding]) -> str:
    """One Romanian line for the sheet or a 409: counts, then the first blocking reason."""
    blocks = [f for f in findings if f.severity == BLOCK]
    warns = [f for f in findings if f.severity == WARN]
    if not blocks and not warns:
        return "Prompturile sunt în regulă."
    text = (
        f"Prompturile au {count_ro(len(blocks), 'blocaj', 'blocaje')} și "
        f"{count_ro(len(warns), 'avertisment', 'avertismente')}."
    )
    if blocks:
        first = blocks[0]
        where = f"scena {first.scene}" if first.scene is not None else "tot filmul"
        text += f" Primul blocaj ({where}): {first.message_ro}"
    return text


def require_no_block(findings: Sequence[Finding]) -> None:
    """Called before any pricing or purchase: an open BLOCK stops the step."""
    if has_block(findings):
        raise PromptLintBlocked(findings)
