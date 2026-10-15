"""From an approved story to the instructions a camera would understand.

What the studio used to send a video model was the line the writer had typed under `visual`:
"a spinning galaxy". Eight of those, at about two dollars sixty a shot, and the Owner's
verdict was exact — "sunt doar niste imagini lipite". Nothing in that pipeline ever described
a camera, a light, a lens, a continuity rule or a reason for the shot to exist, and no amount
of money spent on a better model repairs a prompt that says nothing.

This is the step between the approved script and the generator, and it has two parts:

- **A master visual bible for the film.** One look, decided once: style and realism, the
  world and its period, the palette, how light behaves, the camera's language, the continuity
  rules every shot inherits, and what must never appear. Without it, each shot is a different
  film that happens to be adjacent to the last.
- **A full prompt package per shot.** Subject, action, environment, camera, lighting,
  composition, motion, emotion, background, continuity with the shot before it, audio intent,
  transition, what to avoid — and the story purpose, so a shot that serves nothing can be
  found and cut instead of filmed.

Three rules this step does not bend. It may not invent a fact: a number or a date that is not
in the narration or the claims is refused, because a prompt is not a place to write history.
It may not make the film more spectacular than the story: a quiet last message from a dying
spacecraft does not acquire a battle. And it writes the same package in both environments —
TEST saves money by choosing a cheaper model, never by thinking less. `visual_prompt` keeps
holding what is actually sent, composed from the package, so the entire render path downstream
is unchanged by any of this.

An episode of the office serial takes the same path with its own brief (S8, 2026-09-24). Its
look is not decided per film: the storyboard's bible is the series' one look
(`app.media.series_look`), and every serial prompt opens with its style block word for word,
then the beat's room, the camera, the people in frame as their bibles describe them and the
action, within the look's cap (`compose_serial_prompt`). The model is asked only for the
people: who is in frame facing the viewer, what they do and feel, where the camera stands.
"""

from __future__ import annotations

import json
import logging
import re
import unicodedata
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.agents.memory import agent_for_role, remember
from app.db import lock_for_write
from app.factual.editorial import SCENE_PURPOSES
from app.factual.models import FactualClaim, ScriptDraft
from app.factual.sanitizer import wrap_in_inert_boundary
from app.media import prompt_lint as lint
from app.media.markings import markings_kept, planned_markings, still_exclusions
from app.media.models import CharacterBible, Storyboard, StoryboardScene
from app.media.series_look import (
    LIGHT_SLOTS,
    PART_PURPOSES,
    PLACE_SLOTS,
    SHOT_TYPES,
    load_factual_look,
    load_series_look,
    look_block,
    room_sentence,
    serial_shot_size,
    series_bible,
)
from app.services import append_event, utc_now

logger = logging.getLogger("studio.prompt_agent")

#: The role that owns the studio's pictures. The same steward who reads the vendors' pages
#: about video models writes the instructions those models are given.
PROMPT_ROLE = "VideoEditor"
BIBLE_TEMPLATE = "visual-bible-v1"
SHOTS_TEMPLATE = "shot-prompts-v3"
SERIAL_SHOTS_TEMPLATE = "serial-shot-prompts-v3"

#: The marks of an office-serial film, as `storyboard_from_episode` writes them (the same
#: marks `app.agents.editorial.is_serial_film` reads; that module imports this one).
SERIAL_SERIES_KEY = "office_serial"
SERIAL_SCRIPT_KIND = "office_serial_episode"

#: What the studio will not accept in any generated picture, whatever the story. Not a style
#: preference: these are the failures that make a film look like a raw AI generation.
DEFAULT_NEGATIVES = (
    "on-screen text or captions",
    "warped or extra hands and fingers",
    "plastic or waxy skin",
    "cartoon or 3D-render look when realism is asked for",
    "unmotivated camera movement",
    "clothing, hair or weather changing without reason",
    "faces or bodies morphing mid-shot",
    "watermarks or logos",
)

#: A prompt is specific, not long. A thousand meaningless words teach a model nothing, and
#: the fields that matter get buried. Measured in characters of composed prompt.
MAX_PROMPT_CHARS = 1400
MAX_BIBLE_CHARS = 2400

#: The fields a shot package must actually fill. A prompt missing any of them is a prompt
#: that leaves the decision to the model — which is how a night scene arrives sunlit.
REQUIRED_SHOT_FIELDS = (
    "subject",
    "action",
    "environment",
    "camera",
    "lighting",
    "composition",
    "motion",
)

#: Where prompt lessons are kept. Reuses the studio's own memory rather than a new table: a
#: lesson is a studio-wide fact about how a vendor's model reads instructions.
LESSON_MARKER = "prompt lesson:"

#: The Owner, 2026-10-12, 16:50, after 11.05 USD of the day's 19.50 went on redos and all three
#: films still failed QC: «DIRECTOAREA ACCEPTĂ DEFECTELE MICI! DAR TREBUIE SĂ ÎNȚELEAGĂ DE CE
#: APAR DEFECTELE ȘI LA VIITOARELE PROMPTURI SĂ SE ASIGURE CĂ NU MAI SUNT!» A lesson is how the
#: studio remembers why a defect happened; these numbers decide how it reaches the next prompt.
#: How many lessons a writer is given: the confirmed ones first, then the unverified, each
#: newest first, once near-duplicates are left out.
LESSONS_GIVEN = 12
#: The share of those places kept for the newest unverified lessons (a third: four of twelve,
#: so at most eight confirmed ones while unverified ones wait). Review of 68fa0b4, 2026-10-12:
#: twelve confirmed lessons filled every place, and what the Director's QC and the editorial
#: review had just learned never reached a writer.
LESSONS_UNVERIFIED_SHARE = 3
#: How many of the newest refuted lessons a writer is told about, as refuted diagnoses.
LESSONS_REFUTED_GIVEN = 4
#: A lesson with fewer content words than this is compared with another only word for word:
#: «Keep the camera still.» is {keep} once the scaffold is filler, and one word swallowed or
#: retired unrelated lessons (review of 68fa0b4, 2026-10-12).
LESSON_MIN_WORDS = 3
#: How many new lessons the Director reads in one call of `reconcile_prompt_lessons`; the rest
#: wait for the next writer.
LESSONS_READ_AT_ONCE = 60
#: How many of the newest live lessons of its scope a new one is compared with before it is
#: kept, and how many of the newest live lessons are read at all.
LESSONS_COMPARED = 400
LESSONS_SCANNED = 200
#: A lesson longer than this is a report, not a rule: refused whole, never cut (a cut rule
#: says half of what it meant and is then obeyed as written).
LESSON_MAX_CHARS = 4000
#: A new lesson whose content words are at least this share inside an older one says the
#: same thing (`lesson_overlap`, measured from the NEW lesson's words): it replaces the older
#: (a correction wins, a recurring lesson comes back to the top), never the reverse.
LESSON_OVERLAP = 0.6
#: A new lesson this much inside a LONGER older one says nothing the older does not: the
#: older is said again (refreshed, back to the top) instead of being replaced by less.
LESSON_CONTAINED = 0.9
#: The kinds of film a lesson is for (review of a9f84ea, 2026-10-12): a factual film's «show
#: people only from behind, small and distant» would have reached the serial's beat writer,
#: whose fixed rule is «in frame, facing the viewer». A lesson learned on an episode of the
#: serial is the serial's, one learned on a factual short the factual films', and "all" is
#: both — as every lesson stored before scopes existed reads.
SCOPE_SERIAL = "serial"
SCOPE_FACTUAL = "factual"
SCOPE_ALL = "all"
LESSON_SCOPES = (SCOPE_SERIAL, SCOPE_FACTUAL, SCOPE_ALL)
#: Said after a lesson whose fix no picture has proven yet (`confirm_prompt_lessons`).
UNVERIFIED_SUFFIX = " (unverified)"
#: Why an older lesson stopped being given: a newer one corrected it (it is given back when
#: the correction is refuted).
SUPERSEDED_RO = "înlocuită de o lecție mai nouă"
#: Why an unverified lesson was stored again as a confirmed one.
CONFIRMED_RO = "confirmată: imaginea făcută după ea a trecut controlul"
#: The first word of every refuted lesson's reason: `withdraw_prompt_lessons` puts it before its
#: caller's words, so a refuted lesson is told from one replaced or merged (finding 5 of the
#: review of 68fa0b4: a refuted lesson was learned again at once).
REFUTED_RO = "retrasă"
#: Why an unverified lesson was withdrawn, when its caller gives no words of its own.
WITHDRAWN_RO = "retrasă: defectul a rămas în imaginea făcută după ea"
#: Why a row was stored again with the same lesson in it (its sources and state carried): it
#: was learned again, the Director read it, or one of its sources failed while another waits.
REFRESHED_RO = "învățată din nou: păstrată ca lecția cea mai nouă, cu toate sursele ei"
ABSORBED_RO = "spusă deja de o lecție mai veche: sursa ei a trecut la aceea"
READ_RO = "citită lângă lecțiile știute"
SOURCE_FAILED_RO = "o sursă a ei a picat; lecția rămâne cât timp altă sursă n-a decis"
#: Said before a refuted lesson in the list `prompt_lessons` gives; `fit_with_lessons` moves
#: those under ``refuted_diagnoses`` and `lessons_rule` says what they are.
REFUTED_PREFIX = "Refuted diagnosis: "
#: The Director's reading of a new lesson beside the live ones (`reconcile_prompt_lessons`).
LESSON_READING_TASK = "prompt_lesson_reading"
LESSON_READING_TEMPLATE = "prompt-lesson-reading-v1"
LESSON_READ_EVENT = "media.prompt_lesson_read"
#: What every writer of words a picture is made from is told about the lessons in its data.
#: The data is inside the inert boundary, so the instructions name the lessons as rules, the
#: way the serial brief names its series_look (2026-10-12: the lessons were sent as one more
#: data field nobody named, and the first to be dropped when the payload was too long). A
#: lesson never overrides the brief's fixed rules (review of a9f84ea: a lesson learned on one
#: kind of film can contradict the other kind's look); the writer decides where one applies.
#: Of two lessons that contradict each other the newer wins (review of 68fa0b4, 2026-10-12:
#: «unless a confirmed lesson says otherwise» let the old rule beat the correction of it).
LESSONS_RULE = (
    "The studio's lessons from earlier defects are rules: follow every one. They are given "
    "first in the data below as lessons; each was learned from a picture that failed quality "
    "control, and words that break one make the same defect again and pay for it twice. A "
    'lesson marked "(unverified)" comes from the newest defects and no picture has proven '
    "its fix yet: follow it too. Where two lessons contradict each other, a newer lesson that "
    "contradicts an older one wins: the confirmed lessons come first and the unverified after, "
    "each newest first, and an unverified lesson that contradicts a confirmed one is its "
    "correction. A lesson never overrides this brief's fixed rules (the look it gives, who "
    "faces the viewer and how, the visual bible, no writing in the picture): where one "
    "contradicts them, the brief wins and that lesson does not apply here.\n"
)
#: Added when the data carries refuted diagnoses (finding 5 of the review of 68fa0b4).
REFUTED_RULE = (
    "Under refuted_diagnoses are causes earlier defects were blamed on that a picture proved "
    "wrong: the picture made after each still showed the defect. Do not rely on them, and do "
    "not write them back as a fix; the cause lies elsewhere.\n"
)


#: What the payload of each call may take, in characters of JSON. Whole claims and then scenes
#: are dropped to fit (`trim_payload`); nothing is ever sliced mid-string. The studio's lessons
#: ride whole on top of this budget (`fit_with_lessons`), never trimmed for the film's sake.
MAX_BIBLE_PAYLOAD_CHARS = 120000
MAX_SHOTS_PAYLOAD_CHARS = 160000

#: A storyboard whose model shot plan could not be read, even after the one re-ask. It is
#: not rendered until a plan is written: template prompts are a TEST convenience only.
NEEDS_SHOT_PLAN = "NEEDS_SHOT_PLAN"
#: Why a closed film («Închide filmul», `shooting_sheet.film_is_closed`) is not described
#: again: its status stays REJECTED, so its topic no longer holds the studio.
FILM_CLOSED_PROMPTS_RO = (
    "Filmul este închis: planul lui de cadre nu se mai scrie, iar filmul rămâne închis. "
    "Nimic nu s-a schimbat."
)

#: Where each scene's package came from: the video editor's model, the studio's template
#: (no model reachable; TEST only), or the office serial's fixed look with no model.
SOURCE_MODEL = "model"
SOURCE_TEMPLATE = "template"
SOURCE_SERIES_LOOK = "series_look"


class PromptError(ValueError):
    """The prompt package could not be written; nothing was stored."""


class ShotPlanUnusable(PromptError):
    """The model answered, was asked once more, and shots are still missing.

    The storyboard is NEEDS_SHOT_PLAN and a WARNING event names the scenes; nothing about
    it is rendered until a plan is written.
    """

    def __init__(self, storyboard_id: str, missing: list[int], reason: str) -> None:
        self.storyboard_id = storyboard_id
        self.missing = list(missing)
        super().__init__(reason)


# ------------------------------------------------------------------ the shapes


class VisualBible(BaseModel):
    """The one look the whole film inherits."""

    model_config = ConfigDict(extra="ignore")
    style: str = Field(default="", max_length=300)
    realism: str = Field(default="", max_length=200)
    period: str = Field(default="", max_length=200)
    world: str = Field(default="", max_length=400)
    palette: str = Field(default="", max_length=300)
    lighting: str = Field(default="", max_length=400)
    camera_language: str = Field(default="", max_length=400)
    weather: str = Field(default="", max_length=200)
    continuity_rules: list[str] = Field(default_factory=list, max_length=10)
    avoid: list[str] = Field(default_factory=list)
    season: str = Field(default="", max_length=100)
    # The only place a hex colour is kept: the local card compositor reads it, no image or
    # video model ever does (`_coerce` moves every hex it finds in a prompt-bound field here).
    card_palette: list[str] = Field(default_factory=list, max_length=16)


#: The bible fields whose words can reach a picture prompt. A code in capitals or a hex
#: colour in them is refused (`_coerce`): the Nepal bible's "NEPAL_CLIMATE_CRISIS" and
#: "#2E4A66" were pasted into every prompt and read literally by the image model.
PROMPT_BOUND_BIBLE_FIELDS = (
    "style",
    "realism",
    "period",
    "world",
    "season",
    "palette",
    "lighting",
    "camera_language",
    "weather",
    "continuity_rules",
    "avoid",
)

_HEX_COLOUR = re.compile(r"#(?:[0-9A-Fa-f]{6}|[0-9A-Fa-f]{3})\b")
_LABEL_PREFIX = re.compile(r"^[A-Za-z][\w /'-]{0,24}:\s*")


def _hex6(value: str) -> str:
    """A hex colour as the cards read it: '#RRGGBB', upper case."""
    digits = value.lstrip("#").upper()
    if len(digits) == 3:
        digits = "".join(char * 2 for char in digits)
    return f"#{digits}"


def _scrub_codes(text: str) -> str:
    """A bible value with every clause that holds a code or a hex colour taken out.

    A hex inside an otherwise worded clause is removed and the words kept ("slate blue
    (#2E4A66)" is "slate blue"); a clause that is only a label and codes ("primary:
    #2E4A66") goes. The rest keeps its own punctuation.
    """
    pieces = re.split(r"((?<=[.!?])\s+|\s*[;,]\s*)", text)
    kept: list[str] = []
    separator = ""
    for position, piece in enumerate(pieces):
        if position % 2:
            separator = piece
            continue
        cleaned = " ".join(re.sub(r"\(\s*\)", "", _HEX_COLOUR.sub("", piece)).split())
        body = _LABEL_PREFIX.sub("", cleaned)
        if lint.ENUM_CODE.search(cleaned) or not re.search(r"[A-Za-z]", body):
            continue
        if kept:
            kept.append("; " if ";" in separator else ", " if "," in separator else " ")
        kept.append(cleaned)
    return " ".join("".join(kept).split())


class ShotPrompt(BaseModel):
    """One shot, described the way a director would brief a camera crew."""

    model_config = ConfigDict(extra="ignore")
    scene_index: int = Field(ge=1, le=60)
    story_purpose: str = Field(default="", max_length=20)
    subject: str = Field(default="", max_length=400)
    action: str = Field(default="", max_length=500)
    environment: str = Field(default="", max_length=500)
    camera: str = Field(default="", max_length=300)
    lighting: str = Field(default="", max_length=300)
    composition: str = Field(default="", max_length=300)
    motion: str = Field(default="", max_length=400)
    emotion: str = Field(default="", max_length=200)
    background: str = Field(default="", max_length=300)
    continuity: str = Field(default="", max_length=400)
    ending_frame: str = Field(default="", max_length=300)
    audio_intent: str = Field(default="", max_length=200)
    transition: str = Field(default="", max_length=200)
    avoid: list[str] = Field(default_factory=list)
    # One move from prompt_lint.CAMERA_MOVES; anything else is ignored by the compiler.
    camera_move: str = Field(default="", max_length=40)
    # A closer framing of the same picture the edit may cut to inside the scene, for nothing
    # (assembler.plan_second_framings): {"subject", "centre_x", "centre_y"}. Any shape is
    # accepted here and read by _second_framing, so a rough answer never costs the shot.
    second_framing: Any = None


class ShotPack(BaseModel):
    model_config = ConfigDict(extra="ignore")
    shots: list[ShotPrompt] = Field(default_factory=list, max_length=60)


_BIBLE_INSTRUCTIONS = (
    "You are the studio's video editor, and this film has been approved. Before any shot is "
    "described, decide the one look the whole film will have, so the finished piece reads as "
    "a single film rather than several clips that happen to be next to each other. Below is "
    "the story and every scene as data.\n\n"
    "Decide: the visual style and how real it should look; the period and the world; the "
    "colour palette; how light behaves across the film; the camera's language; the weather, "
    "if any; the continuity rules every shot must obey (what stays identical from shot to "
    "shot — a character's face and clothing, a location, a time of day, a palette); and what "
    "must never appear. Respect the physical setting: for an airless scene describe vacuum "
    "and direct sunlight, not terrestrial weather, haze or wind. Vertical 9:16, watched on "
    "a phone: the subject has to stay readable. "
    "Be specific and brief — a rule that could describe any film is not a rule. Write every "
    "value in plain English words, the way a photographer would say it: the place by its "
    "name and what it looks like, the season, the weather, the light, and colours named in "
    "words (slate blue, wet ochre). Never write codes in capitals with underscores and never "
    "hex colour codes: an image model reads them literally. A chart or a title card is drawn "
    "by the studio, not by the model; if the film has one, give its colours as hex codes in "
    "card_palette, the only place a code belongs. Return only "
    'JSON: {"style": "...", "realism": "...", "period": "...", "world": "...", '
    '"season": "...", "palette": "...", "lighting": "...", "camera_language": "...", '
    '"weather": "...", "continuity_rules": ["..."], "avoid": ["..."], '
    '"card_palette": ["#RRGGBB"]}.\n'
)

_SHOTS_INSTRUCTIONS = (
    "You are the studio's video editor. The story below is approved and must not change: "
    "your job is to turn each scene into instructions a camera crew would understand, "
    "inheriting the master visual bible exactly. One primary visual idea per shot — the "
    "audience is watching on a phone.\n\n"
    "For every scene give: the subject (and, where a person appears, enough of their look "
    "that the next shot can match it); the action, described as movement rather than as a "
    "label — not 'walking' but 'walking quickly toward camera, looking back over his "
    "shoulder, coat pulled by the wind'; the environment with the detail that matters and no "
    "decoration; the camera (shot size, angle, lens character, and its movement with a path "
    "and a speed); the lighting, with direction, quality and colour; the "
    "composition for a vertical frame; the motion and how the world responds to it; the "
    "emotion, at a believable intensity; the background life, which must not compete with the "
    "subject; what must match the previous shot (continuity); what the last frame should be "
    "left on; the audio intent; the transition into the next shot; and what to avoid.\n\n"
    "The still is drawn from the subject, the action, the environment, the camera's framing, "
    "the lighting and the composition at the shot's FIRST moment, so those fields describe "
    "what is seen then — a pose, a state, a place — never a camera move, a speed or a span of "
    "the clip's seconds: those belong only in the camera's move, in motion and in "
    "ending_frame.\n\n"
    "Show the information rather than narrating it twice: if the narration says a storm grew "
    "stronger, the picture shows cloud, wind, water and a reaction, not a caption. Never ask "
    "for writing in the picture — no text overlay, title, label, caption or written number: a "
    "generator draws letters as gibberish or stripes, and text is added in the edit. Do not "
    "add facts, numbers, dates or events that are not in the narration or the claims. Do not "
    "make the film more spectacular than the story: no explosions, crowds, battles or aliens "
    "unless the scene says so. Detailed does not mean long — every phrase must earn its "
    "place.\n\n"
    "The camera: name the shot size (a wide establishing shot, a medium shot, or a detail "
    "of hands, objects or texture; never a close-up of a face) and the lens (24mm wide, "
    "50mm, 85mm compression), and choose exactly one camera_move from this list: dolly in, "
    "dolly out, tracking left, tracking right, crane up, crane down, slow orbit, handheld "
    "drift, aerial drift forward, pedestal up, tilt up, tilt down, slow pan left, slow pan "
    "right, rack focus, static. The movement is ample and specific, the way a film moves, "
    "not a timid zoom: in camera, give the move's path with its speed — where it starts and "
    "where it ends over the clip's seconds (a steady dolly in from the whole room to her "
    "hands on the ledger; a crane up from the bench that reveals the hall). Keep static for "
    "a shot the story holds its breath on, and rack focus only beside a clear action of the "
    "subject. Vary the size and the move across the film; never the same one three scenes "
    "in a row. Optionally give second_framing: a closer framing of the same picture the "
    "editor can cut to halfway through a long scene, at no extra cost — what it shows and "
    "where its centre is, as fractions of the frame's width and height (0 left or top, 1 "
    "right or bottom). In motion, say what the subject does across the clip's seconds, as "
    "verbs (she stands and walks to the window; he turns and hands over the ledger; the "
    "wheel spins; the beam pulses), and what the world does and how fast (curtains lift in "
    "the draught, leaves scatter, cloud rolls, water runs, dust rises, light sweeps across "
    "the wall), without camera words. Ample is not spectacle: nothing happens that the "
    "story does not say, and the shot keeps its one primary visual idea. Name colours in "
    "words, never as hex codes or codes in capitals. When the bible says people's faces must "
    "not be seen, show people only from behind, small and distant, or their hands. Return "
    "only JSON: "
    '{"shots": [{"scene_index": 1, "story_purpose": "HOOK", "subject": "...", '
    '"action": "...", "environment": "...", "camera": "...", "camera_move": "dolly in", '
    '"lighting": "...", "composition": "...", "motion": "...", "emotion": "...", '
    '"background": "...", "continuity": "...", "ending_frame": "...", '
    '"audio_intent": "...", "transition": "...", "avoid": ["..."], '
    '"second_framing": {"subject": "...", "centre_x": 0.5, "centre_y": 0.4}}]}.\n'
)


#: The office serial's brief (S8, 2026-09-24). The factual brief asks for a look to be
#: decided and a world to be described; an episode has both already: the series' look is
#: fixed in config/serial_series_look.json, and every beat is set in one of the studio's own
#: rooms. What a shot of the serial needs from the editor is the people: who is in frame,
#: what they do and feel, and where the camera stands.
_SERIAL_SHOTS_INSTRUCTIONS = (
    "You are the studio's video editor, and this is an approved episode of the studio's own "
    "office serial, Inside The Nexus. The beats are as they will be filmed and must not "
    "change. The series has one look, given below as series_look: it is fixed, it opens every "
    "prompt word for word, and you do not describe style, rendering, light or palette "
    "yourself. Each beat is set in the room its location names, one of the studio's own "
    "rooms, and nowhere else.\n\n"
    "Each shot tells the beat as a scene of a story, not as a portrait: the people are alive "
    "and the feeling of the beat — comedy, suspense, fear, relief, whatever the lines carry — "
    "shows in their bodies before it shows in their words (the Owner, 2026-10-15: «Trebuie să "
    "avem dinamică, suspans dacă este cazul, caractere vii; comedie, suspans, frică; creează o "
    "scenă, spune o poveste»).\n\n"
    "For every beat describe one shot, complete the first time, so that nothing has to be "
    "bought twice:\n"
    "- subject: who is in frame, facing the viewer, and in what room; name the room ONLY by "
    "its own objects (the penthouse: a wide mahogany desk, a big window onto the city, a "
    "brass lamp, bookshelves, plants; the render bay: wooden desks, its monitors switched off "
    "and dark; the research room: a plain wooden desk, a lamp, bookshelves), never another "
    "room's equipment, and no screen anywhere unless the beat needs one, and then dark.\n"
    "- action: the first thing seen as ONE short clause, before any desk or room detail — the "
    "pose, where the hands are (below the frame edge when the framing cannot hold them), and "
    "the position of any worn prop (a headset pushed up off one ear) — then the movement of "
    "the beat as a chain of two or three moments with a beginning and an end inside the shot "
    "(she leans in, slaps the folder shut, sits back; he stands, crosses to the window, turns): "
    "the still is drawn from the first moment, the clip plays the chain.\n"
    "- emotion: the feeling and how it shows — the eyes, the mouth, the shoulders, the pace of "
    "the hands; a laugh held back, a breath held, a flinch, a slow smile.\n"
    "- camera and camera_move: a storytelling choice, varied across the episode and never the "
    "same move twice in a row — an establishing wide for the opening, a two-shot while people "
    "clash, a single or a close-up on a turn or a reaction, a slow push-in on the turn, a "
    "pull-back on the payoff to show the room, a pan from one speaker to the other, tracking "
    "when someone walks; static only for a breath the story holds, never a timid zoom on a "
    "face.\n"
    "- background: the room's own life that does not compete with the speakers (a lamp's "
    "glow, a plant, a colleague passing far behind).\n"
    "- continuity: what must match the previous shot; ending_frame: the last gesture of the "
    "beat, with no camera words.\n"
    "What people say is heard, never drawn. Never ask for writing in the picture: no text, "
    "sign, label, title, screen words or written number, because a generator draws letters "
    "as gibberish. Name no object that carries writing in real life — a nameplate, a sign, a "
    "poster, a badge, a label, a book spine, a printed page, a sticky note, a screen with "
    "content: leave such objects out (a «blank nameplate» invites a name, a negation invites "
    "the thing). Do not add events, objects or people the beat does not have. Choose one "
    "camera_move from: " + ", ".join(lint.CAMERA_MOVES) + ". Return only JSON: "
    '{"shots": [{"scene_index": 1, "subject": "...", "action": "...", "emotion": "...", '
    '"camera": "...", "camera_move": "static", "background": "...", '
    '"continuity": "...", "ending_frame": "...", '
    '"audio_intent": "...", "transition": "..."}]}.\n'
)

_GENERATION_QC_INSTRUCTIONS = (
    "Before writing, check each shot against the same requirements used to judge its output: "
    "it must illustrate the scene's narration and verified claims, not merely match your own "
    "plan. Keep the period, setting, object, physical scale and character bible accurate. "
    "An image is one continuous first moment filling the frame, not a sequence or panels. "
    "For the serial, put each person's first-moment pose in its own semicolon clause before "
    "any later action; retain their canonical outfit and which parts are visible. Keep actions "
    "concise so these details fit the series' prompt budget. Describe the final visible state "
    "in ending_frame, with no camera instructions there. Camera movement belongs in camera_move; "
    "a static shot keeps its framing throughout. Respect the bible's face rule throughout "
    "the video, including its last frame; the camera must not swing into a forbidden face. "
    "Show only the actors/objects already present in the approved first frame, with stable "
    "identity, clothing, anatomy and object geometry. Do not solve a faulty first frame with "
    "a motion instruction. Pages/screens stay blank; an instrument's deliberately required "
    "scale is distinct from added captions. Avoid lists are metadata, not positive drawing "
    "instructions: state the desired visible result in subject/action/motion/ending_frame. "
    "A video model without a negative channel will not receive avoid as a separate instruction. "
    "Do not invent a weather effect to create motion in a vacuum or in a fixed indoor scene.\n"
    "When canonical character identities are supplied, the still composer inserts their hair "
    "and wardrobe. Do not repeat that description in action: use concise named clauses for "
    "each person's visible pose and movement instead. For example: Nadia taps the pen on the "
    "blank ledger; Sarah's shoulder remains at the right edge. Distinguish first-frame "
    "presence from later actions and make subject, cast, action and ending agree.\n"
)


# ------------------------------------------------------------------ what the film is


def _is_serial(board: Storyboard, script: ScriptDraft | None) -> bool:
    """Whether a storyboard is an episode of the office serial, by the marks it carries."""
    if str(board.series_key or "").strip().lower() == SERIAL_SERIES_KEY:
        return True
    story = script.story_json if script is not None and isinstance(script.story_json, dict) else {}
    return story.get("kind") == SERIAL_SCRIPT_KIND


def _serial_scene_facts(session: Session, entry: dict[str, Any]) -> dict[str, Any]:
    """What a serial beat adds to a scene's facts: its part, room, lines and background.

    The room is the name the storyboard stored; a storyboard built before it stored one
    (before S8) is given the name from the headquarters' rooms, as the storyboard would.
    """
    room = str(entry.get("location_name") or "").strip()
    if not room and entry.get("location"):
        from app.story.locations import location_name, studio_locations  # noqa: PLC0415

        room = location_name(entry["location"], studio_locations(session, []))
    lines = [
        {
            "speaker": line.get("speaker"),
            "direction": line.get("direction") or "",
            "text": line.get("text") or "",
        }
        for line in entry.get("lines") or []
        if isinstance(line, dict)
    ]
    given = entry.get("speaker_bibles")
    bibles: dict[str, Any] = given if isinstance(given, dict) else {}
    speaker_ids: list[str] = []
    for line in lines:
        bible_id = bibles.get(str(line.get("speaker") or ""))
        if bible_id and bible_id not in speaker_ids:
            speaker_ids.append(str(bible_id))
    return {
        "part": str(entry.get("part") or ""),
        "location": room,
        "lines": lines,
        "speaker_ids": speaker_ids,
        "background": [str(name) for name in entry.get("background") or []],
    }


def _film_facts(session: Session, board: Storyboard) -> dict[str, Any]:
    """The story, its scenes and its characters, as the prompt agent reads them."""
    script = session.get(ScriptDraft, board.script_draft_id)
    scenes = list(
        session.scalars(
            select(StoryboardScene)
            .where(StoryboardScene.storyboard_id == board.id)
            .order_by(StoryboardScene.scene_index)
        )
    )
    claims = (
        {
            row.id: row.claim_text
            for row in session.scalars(
                select(FactualClaim).where(FactualClaim.topic_id == script.topic_id)
            )
        }
        if script
        else {}
    )
    script_scenes = {
        int(entry.get("scene_number") or index): entry
        for index, entry in enumerate(list(script.scenes_json or []) if script else [], start=1)
    }
    characters = {
        row.id: row
        for row in session.scalars(
            select(CharacterBible).where(
                CharacterBible.id.in_(
                    [cid for scene in scenes for cid in (scene.character_ids_json or [])]
                )
            )
        )
    }
    serial = _is_serial(board, script)
    facts: dict[str, Any] = {
        "serial": serial,
        "title": board.title,
        "aspect_ratio": board.aspect_ratio,
        "visual_style": board.visual_style,
        "story": dict(script.story_json or {}) if script else {},
        "target_seconds": board.target_duration_seconds,
        "scenes": [
            {
                "scene_index": scene.scene_index,
                "seconds": scene.duration_seconds,
                "story_purpose": scene.story_purpose
                or str(script_scenes.get(scene.scene_index, {}).get("purpose") or ""),
                "narration": scene.voiceover_segment,
                # The writer's own line about what is seen, from the script — not from
                # `visual_prompt`, which this step overwrites with what it composed. Reading
                # it back would feed a second run its own output, and each pass would drift
                # a little further from what the writer actually asked for.
                "writer_visual": str(
                    script_scenes.get(scene.scene_index, {}).get("visual_description")
                    or (scene.prompt_json or {}).get("writer_visual")
                    or scene.visual_prompt
                ),
                "shot_type": scene.shot_type,
                "claims": [claims.get(cid, "") for cid in (scene.claim_ids_json or [])],
                "characters": [
                    {
                        "id": cid,
                        "name": characters[cid].canonical_name,
                        "face_hair": characters[cid].face_hair_desc,
                        "outfit": characters[cid].outfit_desc,
                        "props": characters[cid].props_desc,
                        "never": characters[cid].forbidden_deviations,
                    }
                    for cid in (scene.character_ids_json or [])
                    if cid in characters
                ],
            }
            for scene in scenes
        ],
    }
    if serial:
        scene_list: list[dict[str, Any]] = facts["scenes"]
        for scene_facts in scene_list:
            entry = script_scenes.get(int(scene_facts["scene_index"]), {})
            scene_facts.update(_serial_scene_facts(session, entry))
    return facts


def _allowed_text(facts: dict[str, Any]) -> str:
    """Everything the film is allowed to state: its narration and its verified claims."""
    parts = [str(facts.get("title") or "")]
    for scene in facts.get("scenes", []):
        parts.append(str(scene.get("narration") or ""))
        parts.extend(str(claim) for claim in scene.get("claims") or [])
    story = facts.get("story") or {}
    parts.extend(str(value) for value in story.values() if isinstance(value, str))
    return " ".join(parts)


def new_numbers(text: str, allowed: str) -> list[str]:
    """Numbers a prompt states that the story never did.

    A prompt is not a place to write history. "Three hundred soldiers" in a shot description,
    where the claims say nothing about how many, is a fabricated fact that the picture then
    makes look documented — and the studio publishes it as fact.
    """
    permitted = set(re.findall(r"\d+", allowed))
    # Years and counts only; a lens ("35mm") or a ratio ("9:16") is craft, not a claim.
    found = re.findall(r"(?<![\w.:/])(\d{2,4})(?![\w.:/%]|mm|fps|k\b)", text)
    return sorted({value for value in found if value not in permitted})


#: Words that ask a picture generator to draw writing. Image and video models draw letters as
#: gibberish — the "theory" pages of the ATLAS film read "Theam Thory Thory" — and a scene that
#: asked for "a text overlay appears: 'Top quark or W boson?'" came back as eleven seconds of
#: stripes, the film's whole payoff. Text belongs to the edit, never to the shot.
_TEXT_REQUEST = re.compile(
    r"text overlay|on[- ]?screen text|\bcaptions?\b|\bsubtitles?\b|title card|\blettering\b|"
    r"\btypography\b|\bheadline\b|(?:reads|reading|says|saying|appears?)\s*:?\s*['\"“‘]",
    re.IGNORECASE,
)


def strip_on_screen_text(text: str) -> str:
    """The description with every clause that asks for writing in the picture removed.

    Clauses are sentences and the parts between ';'. What is kept keeps its own
    punctuation: the text used to be rejoined with spaces, so every ';' vanished and each
    package with one was reported as "repaired" although nothing had been taken out. With
    nothing removed the text comes back as it was (whitespace aside).
    """
    said = " ".join(str(text or "").split())
    pieces = re.split(r"((?<=[.!?])\s+|\s*;\s*)", said)
    kept: list[str] = []
    separator = ""
    removed = False
    for position, piece in enumerate(pieces):
        if position % 2:
            separator = piece
            continue
        if not piece.strip():
            continue
        if _TEXT_REQUEST.search(piece):
            removed = True
            ending = piece.rstrip()[-1:]
            # A removed sentence took its full stop with it; the clause before keeps one.
            if ending in ".!?" and kept and kept[-1][-1:] not in ".!?":
                kept[-1] += ending
            continue
        if kept:
            kept.append("; " if ";" in separator else " ")
        kept.append(piece.strip())
    if not removed:
        return said
    return " ".join("".join(kept).split())


#: A clause that asks for another rendering than the series' look: another medium, another
#: studio's style, another frame. The adversary's pass (2026-09-24) found that a model's
#: action, camera, expression and background reached a serial prompt whole, so one
#: "photorealistic live-action, shot on 35mm film" after the style block pulled the still
#: away from the look the block had just asked for. A lens ("35mm lens") is not a style.
_STYLE_OVERRIDE = re.compile(
    r"(?:photo|hyper|ultra)[- ]?realis\w*|\brealism\b|live[- ]action|real[- ]life footage|"
    r"documentary (?:footage|style)|\bshot on (?:\d+ ?mm )?film\b|\bfilm (?:grain|stock)\b|"
    r"\b\d+ ?mm film\b|\banime\b|\bmanga\b|\bcartoon\w*|\b2d\b|hand[- ]drawn|cel[- ]shad\w*|"
    r"watercolou?r|oil[- ]paint\w*|(?:pencil|charcoal|ink) (?:sketch|drawing)|sketch style|"
    r"pixel[- ]art|claymation|stop[- ]motion|black[- ]and[- ]white|monochrome|\bsepia\b|"
    r"\bnoir\b|\bchibi\b|low[- ]poly|comic[- ]book|\bin the style of\b|"
    r"\b(?:pixar|disney|ghibli|dreamworks)\b|\b16 ?: ?9\b|widescreen|"
    r"horizontal (?:frame|format)|landscape (?:frame|format|orientation)|"
    r"\b(?:unreal engine|octane render|v-?ray)\b",
    re.IGNORECASE,
)


def strip_style_overrides(text: str) -> str:
    """The description with every clause that restyles the picture removed, the rest kept
    with its own punctuation. Clauses are sentences, and the parts between ';' and ','."""
    pieces = re.split(r"((?<=[.!?])\s+|\s*[;,]\s*)", str(text or ""))
    kept: list[str] = []
    separator = ""
    for position, piece in enumerate(pieces):
        if position % 2:
            separator = piece
            continue
        if not piece.strip() or _STYLE_OVERRIDE.search(piece):
            continue
        if kept:
            kept.append("; " if ";" in separator else ", " if "," in separator else " ")
        kept.append(piece.strip())
    return " ".join("".join(kept).split())


def _flatten(value: Any) -> str:
    """A structured answer said as one line: "key: value; key: value"."""
    if isinstance(value, dict):
        return "; ".join(
            f"{key}: {_flatten(item)}" for key, item in value.items() if _flatten(item)
        )
    if isinstance(value, list | tuple):
        return ", ".join(_flatten(item) for item in value if _flatten(item))
    return "" if value is None else str(value)


def _max_length(field: Any) -> int | None:
    for meta in getattr(field, "metadata", None) or []:
        limit = getattr(meta, "max_length", None)
        if isinstance(limit, int):
            return limit
    return None


def _coerce(data: dict[str, Any], model: type[BaseModel]) -> dict[str, Any]:
    """Fit a model's answer to the schema instead of refusing it for its shape.

    Kael's shot plan for the ATLAS film was 14,036 characters of camera, lens, light and
    composition — and all of it was thrown away because two `audio_intent` lines ran past 200
    characters, so the whole pack failed validation and every shot was rebuilt from the
    writer's one-line description. His visual bible went the same way for describing the
    palette, the light and the camera as objects instead of sentences. A field that is too
    long is shortened, a structured value is said as a sentence; nothing good is discarded
    for its formatting. A text that is too long is cut at a whole word, never mid-word.

    A visual bible's prompt-bound fields refuse codes in capitals and hex colours (the Nepal
    bible, 2026-09-26, was "NEPAL_CLIMATE_CRISIS" and "#2E4A66" throughout): a clause holding
    one is dropped, and a rule or exclusion holding one is dropped whole. Every hex colour
    found is kept in ``card_palette``, the one field only the local card compositor reads.
    """
    bible = model is VisualBible
    found_hex: list[str] = []
    fitted: dict[str, Any] = {}
    for name, field in model.model_fields.items():
        if name not in data or (bible and name == "card_palette"):
            continue
        value = data[name]
        scrub = bible and name in PROMPT_BOUND_BIBLE_FIELDS
        if field.annotation is str:
            text = " ".join(_flatten(value).split())
            if scrub:
                found_hex.extend(_HEX_COLOUR.findall(text))
                text = _scrub_codes(text)
            fitted[name] = text
        elif field.annotation == list[str]:
            items = value if isinstance(value, list) else [value]
            cleaned = [" ".join(_flatten(item).split()) for item in items]
            cleaned = [item for item in cleaned if item]
            if scrub:
                found_hex.extend(hexes for item in cleaned for hexes in _HEX_COLOUR.findall(item))
                cleaned = [
                    item
                    for item in cleaned
                    if not _HEX_COLOUR.search(item) and not lint.ENUM_CODE.search(item)
                ]
            fitted[name] = cleaned
        else:
            fitted[name] = value
    if bible:
        given = data.get("card_palette")
        stated = given if isinstance(given, list) else [given] if given else []
        colours = [
            _hex6(str(item).strip())
            for item in [*stated, *found_hex]
            if _HEX_COLOUR.fullmatch(str(item).strip())
        ]
        palette = list(dict.fromkeys(colours))[:16]
        if palette:
            fitted["card_palette"] = palette
    return fitted


def _first_object(text: str, wanted: tuple[str, ...]) -> dict[str, Any] | None:
    """The first JSON object in a model's answer that carries one of the fields asked for."""
    raw = (text or "").strip()
    decoder = json.JSONDecoder()
    start = raw.find("{")
    tried = 0
    while start >= 0 and tried < 400:
        tried += 1
        try:
            data, _end = decoder.raw_decode(raw, start)
        except ValueError:
            start = raw.find("{", start + 1)
            continue
        if isinstance(data, dict) and any(key in data for key in wanted):
            return data
        start = raw.find("{", start + 1)
    return None


@dataclass
class ShotPlanParse:
    """What could be read of a shot plan, how, and what the decoder said about the rest.

    ``method`` is ``strict`` (the answer decoded as written), ``repaired`` (it decoded after
    the narrow repair), ``salvaged`` (only shot by shot) or ``none``. ``error`` is the strict
    decoder's own message with its offset in the answer, kept even when a repair succeeded:
    it is what a re-ask tells the model, and what the Owner's event carries.
    """

    shots: dict[int, ShotPrompt] = dataclass_field(default_factory=dict)
    method: str = "none"
    error: str | None = None


def repair_json(text: str) -> str:
    """The narrow repair, and nothing else: an inner quote is escaped, a trailing comma dropped.

    Inside a string, a double quote that is not followed (after blanks) by one of ``, : } ]``
    or the end cannot be the string's end, so it is written as ``\\"``. Outside a string, a
    comma followed only by blanks and a closing bracket is removed. Valid JSON is unchanged.
    The Nepal plan (2026-09-26) was lost to exactly the first case:
    ``"Subtle metallic "ping" as bars stop, then silence"``.
    """
    out: list[str] = []
    in_string = False
    index = 0
    size = len(text)
    while index < size:
        char = text[index]
        if in_string:
            if char == "\\":
                out.append(text[index : index + 2])
                index += 2
                continue
            if char == '"':
                ahead = index + 1
                while ahead < size and text[ahead] in " \t\r\n":
                    ahead += 1
                if ahead >= size or text[ahead] in ",:}]":
                    in_string = False
                    out.append(char)
                else:
                    out.append('\\"')
                index += 1
                continue
            out.append(char)
            index += 1
            continue
        if char == '"':
            in_string = True
        elif char == ",":
            ahead = index + 1
            while ahead < size and text[ahead] in " \t\r\n":
                ahead += 1
            if ahead < size and text[ahead] in "}]":
                index += 1
                continue
        out.append(char)
        index += 1
    return "".join(out)


def _decoder_error(raw: str, start: int, exc: json.JSONDecodeError) -> str:
    """The decoder's message, placed in the model's own answer (offset, line, column)."""
    offset = start + exc.pos
    line = raw.count("\n", 0, offset) + 1
    column = offset - (raw.rfind("\n", 0, offset) + 1) + 1
    return f"{exc.msg} at offset {offset} (line {line}, column {column})"


def _shots_from(items: Any) -> dict[int, ShotPrompt]:
    """Every shot that can be placed, fitted to the schema; a broken shot costs only itself."""
    from pydantic import ValidationError  # noqa: PLC0415

    shots: dict[int, ShotPrompt] = {}
    for raw in items if isinstance(items, list) else []:
        if not isinstance(raw, dict):
            continue
        try:
            from app.agents.identity import complete_schema  # noqa: PLC0415

            shot = complete_schema(ShotPrompt).model_validate(_coerce(raw, ShotPrompt))
        except ValidationError:
            continue
        shots.setdefault(shot.scene_index, shot)
    return shots


def _salvage_shots(raw: str) -> list[dict[str, Any]]:
    """Each shot decoded on its own, from the answer as written or after the narrow repair.

    A shot starts at the brace before its ``"scene_index"`` and ends where the next shot
    starts; one shot that cannot be read no longer takes the others with it, and a repair
    that misreads one shot's quotes cannot spill into the next.
    """
    decoder = json.JSONDecoder()
    starts: list[int] = []
    for match in re.finditer(r'"scene_index"\s*:', raw):
        brace = raw.rfind("{", 0, match.start())
        if brace >= 0 and brace not in starts:
            starts.append(brace)
    found: list[dict[str, Any]] = []
    for position, start in enumerate(starts):
        end = starts[position + 1] if position + 1 < len(starts) else len(raw)
        chunk = raw[start:end]
        for attempt in (chunk, repair_json(chunk)):
            try:
                data, _end = decoder.raw_decode(attempt)
            except ValueError:
                continue
            if isinstance(data, dict) and "scene_index" in data and "shots" not in data:
                found.append(data)
                break
    return found


def parse_shot_plan(text: str) -> ShotPlanParse:
    """A model's shot plan read in four steps, each only when the one before failed.

    A strict parse; the narrow repair (`repair_json`); a salvage shot by shot; and otherwise
    nothing, with the decoder's error kept for the one re-ask. Never raises.
    """
    raw = str(text or "")
    start, end = raw.find("{"), raw.rfind("}")
    if start < 0 or end <= start:
        return ShotPlanParse(error="no JSON object in the answer")
    candidate = raw[start : end + 1]
    error: str | None = None
    try:
        data = json.loads(candidate)
    except json.JSONDecodeError as exc:
        error = _decoder_error(raw, start, exc)
        data = _first_object(raw, ("shots",))
        if data is not None:
            # A strict object that stands on its own, with prose or a second object around it.
            error = None
    if isinstance(data, dict) and "shots" in data:
        return ShotPlanParse(_shots_from(data.get("shots")), "strict", error)
    try:
        repaired = json.loads(repair_json(candidate))
    except json.JSONDecodeError:
        repaired = None
    if isinstance(repaired, dict) and "shots" in repaired:
        return ShotPlanParse(_shots_from(repaired.get("shots")), "repaired", error)
    salvaged = _shots_from(_salvage_shots(raw))
    if salvaged:
        return ShotPlanParse(salvaged, "salvaged", error)
    return ShotPlanParse({}, "none", error or "no shot plan in the answer")


def _parse_shot_pack(text: str) -> ShotPack | None:
    """Every shot that can be placed, as a pack; None when not one shot could be read."""
    parsed = parse_shot_plan(text)
    from app.agents.identity import complete_schema  # noqa: PLC0415

    shots = [parsed.shots[index] for index in parsed.shots]
    return complete_schema(ShotPack)(shots=shots) if shots else None


# ------------------------------------------------------------------ whole-item payloads


def _scene_lists(data: Any) -> list[list[Any]]:
    """Every ``scenes`` list inside a payload, at whatever depth the payload keeps it."""
    found: list[list[Any]] = []
    if isinstance(data, dict):
        for key, value in data.items():
            if key == "scenes" and isinstance(value, list):
                found.append(value)
            else:
                found.extend(_scene_lists(value))
    return found


def _dumps(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, default=str)


def trim_payload(data: dict[str, Any], limit: int) -> tuple[dict[str, Any], dict[str, int]]:
    """Compatibility entry point: keep all evidence; batching partitions whole scenes."""
    del limit
    return json.loads(_dumps(data)), {"claims": 0, "lessons": 0, "scenes": 0}


def fit_with_lessons(data: dict[str, Any], lessons: Sequence[str], limit: int) -> dict[str, Any]:
    """The payload fitted to ``limit`` with the studio's lessons kept whole, and first.

    The film is fitted as if there were no lessons (`trim_payload`), then the lessons are put
    in front of it: they never cost a scene, and a scene never costs a lesson. 2026-10-12: the
    serial's shot-plan payload stood at 14-15 thousand of its 16 thousand characters (the
    `shot_prompts` runs of f06808c9, 2026-10-11), and `trim_payload` drops lessons before
    scenes, so any lesson the studio had learned would have been the first thing cut.
    """
    rest = {
        key: value for key, value in data.items() if key not in ("lessons", "refuted_diagnoses")
    }
    fitted, _dropped = trim_payload(rest, limit)
    kept, refuted = _split_refuted(lessons)
    head: dict[str, Any] = {}
    if kept:
        head["lessons"] = kept
    if refuted:
        # What a picture proved was not the cause (review of 68fa0b4, 2026-10-12): said apart
        # from the rules, so no writer follows a refuted diagnosis as one.
        head["refuted_diagnoses"] = refuted
    return {**head, **fitted}


def shot_payload_batches(
    data: dict[str, Any],
    lessons: Sequence[str],
    limit: int = MAX_SHOTS_PAYLOAD_CHARS,
    *,
    max_scenes: int | None = None,
) -> list[dict[str, Any]]:
    """Partition whole scenes; never discard their claims, character bibles or narration.

    An indivisible scene exceeding the advisory budget travels whole. Provider context
    limits must report an error, not silently give the writer incomplete evidence.
    """
    key = "episode" if "episode" in data else "film"
    if max_scenes is not None and max_scenes < 1:
        raise ValueError("A shot batch must contain at least one scene")
    film = data.get(key)
    if not isinstance(film, dict) or not isinstance(film.get("scenes"), list):
        return [fit_with_lessons(data, lessons, limit)]
    kept, refuted = _split_refuted(lessons)

    def payload(scenes: list[Any]) -> dict[str, Any]:
        return {
            **({"lessons": kept} if kept else {}),
            **({"refuted_diagnoses": refuted} if refuted else {}),
            **data,
            key: {**film, "scenes": scenes},
        }

    batches: list[dict[str, Any]] = []
    current: list[Any] = []
    for scene in film["scenes"]:
        if current and (
            len(_dumps(payload([*current, scene]))) > limit
            or (max_scenes is not None and len(current) >= max_scenes)
        ):
            batches.append(payload(current))
            current = []
        current.append(scene)
    if current or not batches:
        batches.append(payload(current))
    return batches


@dataclass(frozen=True)
class ShotGenerationProfile:
    max_tokens: int
    native_thinking: bool = False
    max_scenes: int | None = None


def shot_generation_profile(engine: Engine, editor_id: str) -> ShotGenerationProfile:
    """Learn from this assigned model's actual outcomes, never its brand or private trace."""
    from app.agents.models import Agent, AgentRun, ModelRecord, ProviderRecord  # noqa: PLC0415
    from app.config import Settings  # noqa: PLC0415

    settings = Settings()  # type: ignore[call-arg]
    base = settings.shot_plan_output_tokens
    recovery = max(base, settings.shot_plan_recovery_output_tokens)
    with Session(engine) as session:
        agent = session.get(Agent, editor_id)
        model = session.get(ModelRecord, agent.model_id) if agent else None
        provider = session.get(ProviderRecord, model.provider_id) if model else None
        if model is None or provider is None:
            return ShotGenerationProfile(base)
        runs = session.scalars(
            select(AgentRun)
            .where(
                AgentRun.agent_id == editor_id,
                AgentRun.model_name == model.model_name,
                AgentRun.provider_name == provider.name,
                AgentRun.task_type == "shot_prompts",
                AgentRun.prompt_template_version.endswith("+think"),
            )
            .order_by(AgentRun.started_at.desc())
            .limit(20)
        )
        for run in runs:
            cap = (run.context_json or {}).get("generation_limits", {}).get("effective_max_tokens")
            if not isinstance(cap, int) or isinstance(cap, bool) or cap <= 0:
                continue
            if run.status == "EMPTY_OUTPUT" and (run.completion_tokens or 0) >= cap:
                return ShotGenerationProfile(recovery, True, 1)
            if run.status == "SUCCEEDED" and parse_shot_plan(run.output_text or "").shots:
                return ShotGenerationProfile(max(base, min(cap, recovery)), True, 1)
    return ShotGenerationProfile(base)


def _split_refuted(lessons: Sequence[str]) -> tuple[list[str], list[str]]:
    """The lessons to follow, and the refuted diagnoses (`REFUTED_PREFIX` taken off)."""
    kept: list[str] = []
    refuted: list[str] = []
    for lesson in lessons:
        said = str(lesson).strip()
        if not said:
            continue
        if said.startswith(REFUTED_PREFIX):
            refuted.append(said[len(REFUTED_PREFIX) :].strip())
        else:
            kept.append(said)
    return kept, [item for item in refuted if item]


def lessons_rule(lessons: Sequence[str]) -> str:
    """`LESSONS_RULE` when there are lessons to follow, `REFUTED_RULE` when there are refuted
    diagnoses, else nothing (an empty rule is noise)."""
    kept, refuted = _split_refuted(lessons)
    return (LESSONS_RULE if kept else "") + (REFUTED_RULE if refuted else "")


def _parse_bible(text: str) -> VisualBible | None:
    from pydantic import ValidationError  # noqa: PLC0415

    data = _first_object(text, tuple(VisualBible.model_fields))
    if data is None:
        return None
    try:
        from app.agents.identity import complete_schema  # noqa: PLC0415

        return complete_schema(VisualBible).model_validate(_coerce(data, VisualBible))
    except ValidationError:
        return None


# ------------------------------------------------------------------ the bible


def build_visual_bible(
    engine: Engine,
    registry: Any,
    storyboard_id: str,
    correlation_id: str | None = None,
) -> dict[str, Any]:
    """Decide the one look this film has, and keep it on the storyboard.

    Falls back to a bible composed from the film's own fields when no model can be reached:
    a studio without a language model still produces one consistent-looking film rather than
    a set of unrelated shots.
    """
    correlation = correlation_id or str(uuid4())
    # The lessons learned since the last writer are read by the Director first (free): one
    # that corrects an older lesson retires it before the bible is written from both.
    reconcile_prompt_lessons(engine, registry, correlation)
    with Session(engine) as session:
        board = session.get(Storyboard, storyboard_id)
        if board is None:
            raise PromptError(f"Storyboard {storyboard_id} not found")
        facts = _film_facts(session, board)
        editor = agent_for_role(session, PROMPT_ROLE)
        editor_id = editor.id if editor else None
        # The bible's words open every prompt of the film: a lesson about how a model reads
        # them (a code in capitals, a hex colour, a light that contradicts the place) is the
        # bible's to follow too, not only the shot plan's (2026-10-12) — the lessons of its
        # kind of film only (a serial's «facing the viewer» is not a factual film's rule).
        lessons = prompt_lessons(session, scope=_scope_of(bool(facts.get("serial"))))

    bible: VisualBible | None = None
    run_id = None
    if editor_id is not None and registry is not None:
        fitted = fit_with_lessons(facts, lessons, MAX_BIBLE_PAYLOAD_CHARS)
        payload = _dumps(fitted)
        result = _run(
            engine,
            registry,
            editor_id,
            "visual_bible",
            _BIBLE_INSTRUCTIONS
            + lessons_rule(lessons)
            + wrap_in_inert_boundary(payload, "approved-film"),
            BIBLE_TEMPLATE,
            correlation,
            f"Stabilesc privirea filmului «{facts['title']}».",
            2200,
        )
        if result is not None:
            run_id = result["id"]
            bible = _parse_bible(result.get("output_text") or "")

    record = (bible or VisualBible()).model_dump()
    record["avoid"] = _avoid_list(record.get("avoid"))
    record.setdefault("aspect_ratio", facts["aspect_ratio"])
    record["aspect_ratio"] = facts["aspect_ratio"]
    record["quality_target"] = "premium cinematic, readable on a phone in vertical framing"
    if not record.get("style"):
        record["style"] = f"{facts['visual_style'].replace('_', ' ').lower()}, cinematic"
    if not record.get("continuity_rules"):
        record["continuity_rules"] = [
            "the same palette, light and time of day across every shot unless the story says "
            "otherwise",
            "a character's face, hair and clothing are identical from shot to shot",
            "the location holds unless a scene explicitly moves",
        ]
    record["source"] = "director" if bible is not None else "studio defaults"
    record["written_at"] = utc_now()

    with Session(engine) as session, session.begin():
        board = session.get(Storyboard, storyboard_id)
        if board is None:
            raise PromptError(f"Storyboard {storyboard_id} not found")
        board.visual_bible_json = record
        append_event(
            session,
            "media.visual_bible_written",
            "storyboard",
            storyboard_id,
            1,
            {"source": record["source"], "rules": len(record["continuity_rules"])},
            correlation,
        )
    return {"storyboard_id": storyboard_id, "bible": record, "run_id": run_id}


def _avoid_list(raw: Any) -> list[str]:
    """The film's own exclusions, on top of the ones the studio always refuses."""
    theirs = [" ".join(str(item).split()) for item in raw] if isinstance(raw, list) else []
    merged = list(DEFAULT_NEGATIVES)
    for item in theirs:
        if item and item.lower() not in {m.lower() for m in merged}:
            merged.append(item)
    return merged


# ------------------------------------------------------------------ the shots


def write_shot_prompts(
    engine: Engine,
    registry: Any,
    storyboard_id: str,
    correlation_id: str | None = None,
    *,
    repair_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Write the full prompt package for every shot of an approved film.

    The package is identical in both environments: the environment decides which model is
    bought, never how well the shot is described. `visual_prompt` is rewritten from the
    package, so the render, the costing and quality control need to know nothing about this.
    """
    from app.factual.story_review import story_gate  # noqa: PLC0415
    from app.media.shooting_sheet import film_is_closed  # noqa: PLC0415 - it imports us

    correlation = correlation_id or str(uuid4())
    # The lessons learned since the last writer are read by the Director first (free; review of
    # 68fa0b4, 2026-10-12): a correction retires the rule it corrects before the shots are
    # written, a lesson said again is merged with its sources.
    reconcile_prompt_lessons(engine, registry, correlation)
    with Session(engine) as session:
        board = session.get(Storyboard, storyboard_id)
        if board is None:
            raise PromptError(f"Storyboard {storyboard_id} not found")
        if film_is_closed(session, storyboard_id):
            # «Închide filmul»: a closed film is not described again, and no model is run for it.
            raise PromptError(FILM_CLOSED_PROMPTS_RO)
        # Describing the shots is the last step before money, so it is where the story gate
        # is enforced: a film whose story nobody judged does not get described, and one the
        # review sent back waits for the rewrite.
        passed, why = story_gate(session, board.script_draft_id)
        if not passed:
            raise PromptError(why)
        need_bible = not board.visual_bible_json or (
            registry is not None and board.visual_bible_json.get("source") == "studio defaults"
        )
        facts = _film_facts(session, board)
        editor = agent_for_role(session, PROMPT_ROLE)
        editor_id = editor.id if editor else None
        # The lessons of this kind of film (review of a9f84ea, 2026-10-12): a factual short's
        # «show people only from behind» never reaches the serial's beats, whose people face
        # the viewer, and the serial's lessons never reach a factual film's shots.
        lessons = prompt_lessons(session, scope=_scope_of(bool(facts.get("serial"))))
    serial = bool(facts.get("serial"))
    # An episode of the serial does not decide a look: it has the series' one, read from the
    # Owner's proposal and written onto the storyboard every time, never asked of a model.
    look = load_series_look() if serial else {}
    if serial:
        with Session(engine) as session, session.begin():
            board = session.get(Storyboard, storyboard_id)
            if board is not None:
                board.visual_bible_json = series_bible(look, board.aspect_ratio)
    elif need_bible:
        build_visual_bible(engine, registry, storyboard_id, correlation)
    with Session(engine) as session:
        board = session.get(Storyboard, storyboard_id)
        bible = dict((board.visual_bible_json or {}) if board else {})

    packs: dict[int, ShotPrompt] = {}
    run_id = None
    run_ids: list[str] = []
    # Whether a model answered at all: an answer that cannot be read is a lost plan, never a
    # reason to fall back to templates in silence (the Nepal film, 2026-09-26).
    answered = False
    reasked = False
    parsed = ShotPlanParse()
    if editor_id is not None and registry is not None:
        profile = shot_generation_profile(engine, editor_id)
        if serial:
            data: dict[str, Any] = {
                "series_look": {
                    "style_block": look.get("block") or "",
                    "version": look.get("version"),
                    "continuity_rules": look.get("continuity_rules") or [],
                },
                "episode": facts,
            }
            instructions, template = _SERIAL_SHOTS_INSTRUCTIONS, SERIAL_SHOTS_TEMPLATE
        else:
            data = {"visual_bible": bible, "film": facts}
            instructions, template = _SHOTS_INSTRUCTIONS, SHOTS_TEMPLATE
        if repair_context:
            data["repair_context"] = repair_context
        # The lessons are rules named in the instructions and kept whole at the head of the
        # data, for the serial's beats as for a factual film's shots (2026-10-12, the Owner:
        # «la viitoarele prompturi să se asigure că nu mai sunt»): the serial's payload sat
        # at its cap, and the lessons were the first thing `trim_payload` dropped.
        if serial:
            data["generation_contract"] = {
                "max_still_characters": look.get("max_prompt_chars"),
                "max_motion_words": MOTION_MAX_WORDS,
                "negative_channel": "image only; motion uses positive visible states",
            }
        else:
            data["generation_contract"] = {
                "max_prompt_utf16": lint.DEFAULT_PROMPT_MAX_UTF16,
                "max_motion_words": MOTION_MAX_WORDS,
                "negative_channel": "depends on selected video model; do not rely on avoid alone",
            }
        for fitted in shot_payload_batches(
            data, lessons, MAX_SHOTS_PAYLOAD_CHARS, max_scenes=profile.max_scenes
        ):
            batch_facts = fitted["episode" if serial else "film"]
            indices = [int(s["scene_index"]) for s in batch_facts["scenes"]]
            prompt = (
                instructions
                + _GENERATION_QC_INSTRUCTIONS
                + lessons_rule(lessons)
                + wrap_in_inert_boundary(_dumps(fitted), "approved-film")
                + "\nReturn shots only for these scene_index values: "
                + json.dumps(indices)
                + ". The shared story and bible are context; do not write other scenes."
            )
            result = _run(
                engine,
                registry,
                editor_id,
                "shot_prompts",
                prompt,
                template,
                correlation,
                f"Scriu prompturile pentru {len(indices)} cadre.",
                profile.max_tokens,
                native_thinking=profile.native_thinking,
            )
            if result is None:
                continue
            answered = True
            run_id = result["id"]
            run_ids.append(str(run_id))
            parsed = parse_shot_plan(result.get("output_text") or "")
            packs.update({index: shot for index, shot in parsed.shots.items() if index in indices})
            missing = [index for index in indices if index not in packs]
            # ONE re-ask, carrying the decoder's own words, for a factual film. The serial's
            # shots are composed from its fixed look when the model's are missing (S8).
            if missing and not serial:
                reasked = True
                again = _run(
                    engine,
                    registry,
                    editor_id,
                    "shot_prompts",
                    prompt + _reask_note(parsed, missing),
                    template,
                    correlation,
                    f"Cer din nou planul de cadre: lipsesc cadrele {_listed(missing)}.",
                    profile.max_tokens,
                    native_thinking=(
                        not parsed.shots
                        and _first_object(result.get("output_text") or "", ("shots",)) is None
                    ),
                )
                if again is not None:
                    run_id = again["id"]
                    run_ids.append(str(run_id))
                    second = parse_shot_plan(again.get("output_text") or "")
                    for index, answer in second.shots.items():
                        if index in indices:
                            packs.setdefault(index, answer)
                    parsed = ShotPlanParse(packs, second.method, second.error)

    allowed = _allowed_text(facts)
    written: list[dict[str, Any]] = []
    refused: list[str] = []
    previous_ending = ""
    kept_from_before: list[int] = []
    moves: list[str] = []
    ending_dropped: list[int] = []
    with Session(engine) as session, session.begin():
        # Behind the write lock the Owner's close takes: a film closed while the model wrote is
        # left as it is (REJECTED, its scenes untouched). Setting it NEEDS_SHOT_PLAN or APPROVED
        # here would reopen it, and its topic would hold the studio again.
        lock_for_write(session)
        if film_is_closed(session, storyboard_id):
            raise PromptError(FILM_CLOSED_PROMPTS_RO)
        scenes = list(
            session.scalars(
                select(StoryboardScene)
                .where(StoryboardScene.storyboard_id == storyboard_id)
                .order_by(StoryboardScene.scene_index)
            )
        )
        facts_by_index = {int(s["scene_index"]): s for s in facts["scenes"]}
        lost = answered and not serial and any(s.scene_index not in packs for s in scenes)
        for scene in scenes:
            scene_facts = facts_by_index.get(scene.scene_index, {})
            shot = packs.get(scene.scene_index)
            earlier = dict(scene.prompt_json or {})
            if (lost or not answered) and shot is None and earlier.get("source") == SOURCE_MODEL:
                # A plan a model wrote before is never overwritten by a template because
                # this answer could not be read, nor because no model answered at all this
                # time (the day asks a NEEDS_SHOT_PLAN film again, and the run may be refused).
                kept_from_before.append(scene.scene_index)
                previous_ending = str(earlier.get("ending_frame") or "")
                continue
            package, notes = _validated_package(shot, scene_facts, bible, allowed, previous_ending)
            refused.extend(f"cadrul {scene.scene_index}: {note}" for note in notes)
            if serial:
                package = _serial_package(package, shot, scene_facts, look)
                scene.shot_type = SHOT_TYPES[package["shot_size"]]
                package["source"] = SOURCE_MODEL if shot is not None else SOURCE_SERIES_LOOK
                composed = compose_serial_prompt(package, look)
                # The shot's own movement, so the motion step has words of its own and the
                # film's camera varies: the plan's move, else one that suits the shot's size
                # and is not the scene before's, as the factual compile chooses. A serial
                # given «static» everywhere was BLOCKed SAME_CAMERA_EVERY_SCENE on every
                # rewrite (2026-10-11, f06808c9), whatever its writer wrote.
                move = _serial_camera_move(package, moves)
                moves.append(move)
                package["camera_move"] = move
                package["motion_prompt"], dropped = serial_motion(package, look)
                if dropped:
                    # Where the clip must arrive could not be said beside the action, even
                    # cut to its first moment (review of 68fa0b4): recorded, so the scene's
                    # rewrite asks the editor to shorten the action before a clip is bought.
                    ending_dropped.append(scene.scene_index)
                package["still_prompt"] = composed
                package["composition_issues"] = composition_issues(
                    package, composed, package["motion_prompt"]
                )
            else:
                # Two prompts per filmed scene (compile_prompts); a scene composed locally
                # carries none, and its visual_prompt stays the writer's line.
                package["scene_kind"] = str(getattr(scene, "scene_kind", None) or LIVE_KIND).upper()
                package["shot_type"] = scene.shot_type
                compiled = compile_prompts(package, bible, previous_moves=moves)
                package.update(compiled)
                if compiled["camera_move"]:
                    moves.append(compiled["camera_move"])
                composed = compiled["still_prompt"] or str(
                    package.get("writer_visual") or scene.visual_prompt or ""
                )
            scene.prompt_json = package
            scene.story_purpose = package["story_purpose"]
            scene.visual_prompt = composed
            previous_ending = str(package.get("ending_frame") or "")
            written.append(
                {
                    "scene_index": scene.scene_index,
                    "story_purpose": package["story_purpose"],
                    "chars": len(composed),
                    "from_model": shot is not None,
                }
            )
        missing = [
            s.scene_index
            for s in scenes
            if s.scene_index not in packs and s.scene_index not in kept_from_before
        ]
        board = session.get(Storyboard, storyboard_id)
        if lost and missing:
            if board is not None:
                board.status = NEEDS_SHOT_PLAN
            append_event(
                session,
                "media.shot_prompts_incomplete",
                "storyboard",
                storyboard_id,
                1,
                {
                    "severity": "WARNING",
                    "from_model": sum(1 for item in written if item["from_model"]),
                    "missing_scenes": missing,
                    "kept_from_before": kept_from_before,
                    "decoder_error": parsed.error,
                    "parse_method": parsed.method,
                    "reasked": reasked,
                    "run_ids": run_ids,
                },
                correlation,
            )
        else:
            if board is not None and board.status == NEEDS_SHOT_PLAN:
                board.status = "APPROVED"  # the plan it was waiting for is written
            append_event(
                session,
                "media.shot_prompts_written",
                "storyboard",
                storyboard_id,
                1,
                {
                    "shots": len(written),
                    "from_model": sum(1 for item in written if item["from_model"]),
                    "repaired": refused[:6],
                    "parse_method": parsed.method,
                    "reasked": reasked,
                    "ending_dropped": ending_dropped,
                },
                correlation,
            )
    if lost and missing:
        logger.warning(
            "shot_prompts_incomplete",
            extra={"storyboard_id": storyboard_id, "missing": missing, "error": parsed.error},
        )
        raise ShotPlanUnusable(
            storyboard_id,
            missing,
            f"Planul de cadre al editorului nu a putut fi citit pentru cadrele "
            f"{_listed(missing)}, nici după a doua cerere; filmul așteaptă un plan "
            f"({NEEDS_SHOT_PLAN}).",
        )
    logger.info(
        "shot_prompts_written",
        extra={"storyboard_id": storyboard_id, "shots": len(written), "repaired": len(refused)},
    )
    return {
        "storyboard_id": storyboard_id,
        "shots": written,
        "repaired": refused,
        "run_id": run_id,
        "bible": bible,
        "ending_dropped": ending_dropped,
    }


def _listed(indexes: list[int]) -> str:
    return ", ".join(str(index) for index in indexes)


def _reask_note(parsed: ShotPlanParse, missing: list[int]) -> str:
    """What the one re-ask adds to the brief: the decoder's error and the missing scenes."""
    return (
        "\n\nYour previous answer could not be read in full. The JSON decoder said: "
        f"{parsed.error or 'no readable shot plan'}. Scenes missing from what could be read: "
        f"{_listed(missing)}. Answer again with the complete JSON for every scene and nothing "
        'else. Inside a value, write a double quote as \\" or use single quotes.\n'
    )


def shot_plan_gaps(
    session: Session, storyboard_id: str, sources: Sequence[str] = (SOURCE_MODEL,)
) -> list[int]:
    """The scenes of a storyboard whose package came from none of ``sources``: the model's
    alone for a factual film, the series look's too for the office serial
    (`assembler.shot_plan_sources`; 2026-10-11, f06808c9: the sheet read every serial scene
    the look composed as a gap and refused the walk NEEDS_SHOT_PLAN, while the stills stage
    accepted them)."""
    return [
        scene.scene_index
        for scene in session.scalars(
            select(StoryboardScene)
            .where(StoryboardScene.storyboard_id == storyboard_id)
            .order_by(StoryboardScene.scene_index)
        )
        if (scene.prompt_json or {}).get("source") not in sources
    ]


def hold_for_shot_plan(engine: Engine, storyboard_id: str, correlation_id: str) -> list[int]:
    """Stop a film whose shots a model did not write: NEEDS_SHOT_PLAN and a WARNING event.

    Returns the scenes without a model package; an empty list means the film may go on and
    nothing was changed. Template prompts are a TEST convenience; in PRODUCTION the media
    stage asks this before anything is bought.

    A closed film (`shooting_sheet.film_is_closed`) is never held, which would reopen it: the
    answer is an empty list and nothing is changed; every buyer meets it closed at its lease.
    """
    from app.media.assembler import shot_plan_sources  # noqa: PLC0415 - it imports us
    from app.media.shooting_sheet import film_is_closed  # noqa: PLC0415 - it imports us

    # The serial's scenes composed from the series look are no gap (read before the lock).
    sources = shot_plan_sources(engine, storyboard_id)
    with Session(engine) as session, session.begin():
        # Behind the write lock the Owner's close takes, so a close is seen or comes after.
        lock_for_write(session)
        if film_is_closed(session, storyboard_id):
            return []
        gaps = shot_plan_gaps(session, storyboard_id, sources)
        board = session.get(Storyboard, storyboard_id)
        if not gaps or board is None:
            return gaps
        total = int(board.total_scenes or 0) or len(gaps)
        board.status = NEEDS_SHOT_PLAN
        append_event(
            session,
            "media.shot_prompts_incomplete",
            "storyboard",
            storyboard_id,
            1,
            {
                "severity": "WARNING",
                "from_model": max(0, total - len(gaps)),
                "missing_scenes": gaps,
                "decoder_error": None,
                "parse_method": "not_model",
                "reasked": False,
                "run_ids": [],
                "held_by": "media_stage",
            },
            correlation_id,
        )
    return gaps


def _validated_package(
    shot: ShotPrompt | None,
    scene: dict[str, Any],
    bible: dict[str, Any],
    allowed: str,
    previous_ending: str,
) -> tuple[dict[str, Any], list[str]]:
    """One shot's package, with every gap filled and every invented fact removed.

    A missing field is filled from what the film already states, because a shot with no
    lighting is a shot whose lighting the model invents. An invented number is cut: the
    picture would make it look documented.
    """
    notes: list[str] = []
    purpose = str((shot.story_purpose if shot else "") or scene.get("story_purpose") or "").upper()
    if purpose not in SCENE_PURPOSES:
        purpose = "DEVELOPMENT"
        notes.append("scopul cadrului lipsea")
    package: dict[str, Any] = {
        "story_purpose": purpose,
        "narration": str(scene.get("narration") or ""),
        # Kept so a rerun starts from the writer's line again, whatever this step composed.
        "writer_visual": str(scene.get("writer_visual") or ""),
        "seconds": float(scene.get("seconds") or 0),
        "subject": (shot.subject if shot else "") or str(scene.get("writer_visual") or ""),
        "action": (shot.action if shot else "") or str(scene.get("writer_visual") or ""),
        "environment": (shot.environment if shot else "") or str(bible.get("world") or ""),
        "camera": (shot.camera if shot else "")
        or f"{str(scene.get('shot_type') or 'MEDIUM').lower()} shot, locked camera",
        "lighting": (shot.lighting if shot else "") or str(bible.get("lighting") or ""),
        "composition": (shot.composition if shot else "")
        or "subject centred in a vertical frame, readable on a phone",
        # Two clauses, so the compiler reads the first as the subject's motion and the second
        # as the world's (`_motion_intent`); said without camera words, which it drops. Until
        # 2026-10-11: "slow, natural movement within the frame", every word of it dropped.
        "motion": (shot.motion if shot else "")
        or "the subject carries on with its action; shadows drift and the light shifts around it",
        "emotion": (shot.emotion if shot else ""),
        "background": (shot.background if shot else ""),
        "continuity": (shot.continuity if shot else "") or previous_ending,
        "ending_frame": (shot.ending_frame if shot else ""),
        "audio_intent": (shot.audio_intent if shot else "narration dominates"),
        "transition": (shot.transition if shot else "dissolve into the next shot"),
        "avoid": _avoid_list(shot.avoid if shot else None),
        "characters": scene.get("characters") or [],
        # The plan's own camera move, when it named one from the enum; the compiler
        # chooses one otherwise (`choose_camera_move`).
        "camera_move": (
            shot.camera_move.strip().lower()
            if shot and shot.camera_move.strip().lower() in lint.CAMERA_MOVES
            else ""
        ),
        # Where this package came from. A render in PRODUCTION requires "model": template
        # prompts are a TEST convenience (SHOT_PLAN_PARSE, 2026-09-27).
        "source": SOURCE_MODEL if shot is not None else SOURCE_TEMPLATE,
    }
    # Only when the editor gave a usable one: a package without it is the package it was,
    # and the sheet's hashes of every film planned before stay what they were.
    framing = _second_framing(shot.second_framing if shot else None)
    if framing is not None:
        package["second_framing"] = framing
    for key in ("subject", "action", "environment", "background", "composition", "ending_frame"):
        original = str(package.get(key) or "")
        cleaned = strip_on_screen_text(original)
        if cleaned != " ".join(original.split()):
            package[key] = cleaned
            if "cerere de text în imagine scoasă" not in notes:
                notes.append("cerere de text în imagine scoasă")
    writer_line = strip_on_screen_text(str(scene.get("writer_visual") or ""))
    for field in REQUIRED_SHOT_FIELDS:
        if not str(package.get(field) or "").strip():
            package[field] = writer_line or str(bible.get("style") or "")
            notes.append(f"{field} lipsea")
    invented = new_numbers(
        " ".join(str(package[k]) for k in ("subject", "action", "environment", "background")),
        allowed,
    )
    if invented:
        notes.append("cifre inventate scoase: " + ", ".join(invented[:4]))
        for key in ("subject", "action", "environment", "background"):
            text = str(package[key])
            for value in invented:
                text = re.sub(rf"\b{re.escape(value)}\b", "", text)
            package[key] = " ".join(text.split())
    return package, notes


def _second_framing(raw: Any) -> dict[str, Any] | None:
    """The editor's second framing as the edit reads it: a subject (cleaned of on-screen
    text) and a centre held inside the frame; None for anything that is not one."""
    if not isinstance(raw, dict):
        return None
    centre: list[float] = []
    for key in ("centre_x", "centre_y"):
        value = raw.get(key)
        if isinstance(value, bool) or not isinstance(value, int | float):
            return None
        centre.append(round(min(1.0, max(0.0, float(value))), 3))
    subject = strip_on_screen_text(" ".join(str(raw.get("subject") or "").split()))
    return {"subject": subject, "centre_x": centre[0], "centre_y": centre[1]}


def _short_name(name: Any) -> str:
    """How a shot names a character: "Sarah Executive" -> "Sarah", "Dr. Aris ..." -> "Dr. Aris"."""
    words = str(name or "").split()
    if not words:
        return ""
    if words[0].rstrip(".").lower() in ("dr", "mr", "mrs", "ms", "prof") and len(words) > 1:
        return f"{words[0]} {words[1]}"
    return words[0]


def _fit(text: str, limit: int) -> str:
    """``text`` cut at a word boundary to at most ``limit`` characters."""
    said = " ".join(str(text or "").split())
    if len(said) <= limit:
        return said
    cut = said[: max(0, limit)].rsplit(" ", 1)[0]
    return cut.rstrip(",;: ")


def _clauses(text: Any, separators: str) -> list[str]:
    said = " ".join(str(text or "").split()).rstrip(". ")
    return [part.strip() for part in re.split(f"[{separators}]", said) if part.strip()]


def _identity(character: dict[str, Any], limit: int) -> str:
    """A character as their bible describes them, in at most ``limit`` characters.

    Whole clauses, most telling first: the hair, then the first garment, then the rest of the
    face and of the outfit while they fit. Cut mid-phrase, "a navy executive blazer" became
    "a navy executive", a garment the bible never named.
    """
    face = _clauses(character.get("face_hair"), ";")
    outfit = _clauses(character.get("outfit"), ",;")
    if outfit:
        outfit[0] = f"wearing {outfit[0][:1].lower()}{outfit[0][1:]}"
    name = f"{_short_name(character.get('name'))}: "
    kept = set(face[:1] + outfit[:1])
    size = len(name) + sum(len(part) + 2 for part in kept)
    for extra in face[1:] + outfit[1:]:
        if size + len(extra) + 2 > limit:
            break
        kept.add(extra)
        size += len(extra) + 2
    # Said in the bible's order: the whole face, then the clothes. A clause that does not
    # fit whole is left out, never cut in the middle: «Tousled wavy dark hair, wearing;» and
    # «Brunette professional bob with.» were what the first episode's stills said of their
    # people (2026-10-11, f06808c9).
    parts = [part for part in face + outfit if part in kept]
    text = name + ", ".join(parts)
    while len(text) > limit and len(parts) > 1:
        parts.pop()
        text = name + ", ".join(parts)
    return _clean_cut(_fit(text, limit))


def _serial_package(
    package: dict[str, Any],
    shot: ShotPrompt | None,
    scene: dict[str, Any],
    look: dict[str, Any],
) -> dict[str, Any]:
    """A serial shot's package: the beat's room, the people in frame and the camera.

    The room is the beat's, never the model's; the people are the beat's speakers first, as
    their bibles describe them; the camera is the model's, or the size the beat's part asks
    for. Without a model the action is the beat's scene line with each speaker's direction,
    and what they say is left to the voice: a line in a picture prompt is drawn as writing.
    """
    cast = [c for c in scene.get("characters") or [] if isinstance(c, dict)]
    by_id = {c.get("id"): c for c in cast}
    speakers = [by_id[cid] for cid in scene.get("speaker_ids") or [] if cid in by_id]
    if not speakers:
        speakers = cast[:2]
    size = serial_shot_size(scene.get("part"), int(scene.get("scene_index") or 1), len(speakers))
    if size == "establishing":
        in_frame = speakers or cast
    elif size == "two_shot":
        in_frame = speakers[:2]
    else:
        in_frame = speakers[:1]
    # The people of the beat who do not speak stand at their own desks; a speaker outside a
    # single's frame is off camera, not in the background.
    others = [
        _short_name(c.get("name"))
        for c in cast
        if c not in in_frame and c not in speakers and c.get("name")
    ]
    others += [_short_name(name) for name in scene.get("background") or [] if name]
    focus = _short_name(in_frame[0].get("name")) if in_frame else "the speaker"
    sizes = look.get("shot_sizes") or {}
    default_camera = str(sizes.get(size) or "").replace("{name}", focus)

    said: list[str] = []
    feelings: list[str] = []
    previous = None
    for line in scene.get("lines") or []:
        who = _short_name(line.get("speaker"))
        if not who or who == previous:
            continue
        direction = strip_on_screen_text(str(line.get("direction") or ""))
        verb = "speaks" if previous is None else "answers"
        said.append(f"{who}, {direction}, {verb}" if direction else f"{who} {verb}")
        if direction:
            feelings.append(f"{who} {direction}")
        previous = who
    writer_line = strip_on_screen_text(str(scene.get("writer_visual") or ""))
    spoken = "; ".join(said) + "." if said else ""
    fallback_action = " ".join(part for part in (writer_line, spoken) if part)

    # While the series has a look, a model may describe the shot but never restyle it: what
    # it wrote that asks for another medium or frame is taken out (`strip_style_overrides`).
    restyle = strip_style_overrides if look.get("in_use") else (lambda text: text)
    package = dict(package)
    model_action = restyle(str(package.get("action") or "")) if shot and shot.action else ""
    package["action"] = model_action or fallback_action
    package["emotion"] = (restyle(shot.emotion) if shot and shot.emotion else "") or "; ".join(
        feelings
    )
    model_camera = restyle(strip_on_screen_text(shot.camera)) if shot and shot.camera else ""
    package["camera"] = model_camera or default_camera
    background = restyle(str(package.get("background") or "")) if shot and shot.background else ""
    if not background and others:
        background = "at their own desks behind them: " + ", ".join(dict.fromkeys(others))
    package["background"] = background
    package["location"] = str(scene.get("location") or "")
    package["shot_size"] = size
    package["in_frame"] = in_frame
    if look.get("in_use"):
        package["lighting"] = "the series look"
    package["avoid"] = list(
        dict.fromkeys([*(look.get("avoid") or []), *(package.get("avoid") or [])])
    )
    package["series_look_version"] = look.get("version") if look.get("in_use") else None
    package["from_model"] = shot is not None
    purpose = PART_PURPOSES.get(str(scene.get("part") or "").lower())
    if purpose and not (shot and shot.story_purpose):
        package["story_purpose"] = purpose
    return package


#: How a serial still fills the tall frame: one picture, the people high in it. The first
#: episode's stills of scenes 3, 4 and 7 (2026-10-11, f06808c9) came back as the same picture
#: three times, stacked, on both candidates: their prompts described a camera path over time
#: and a chain of moments, and said nothing of the frame; scenes 1 and 2, one moment each,
#: were fine. The factual compile says the same of its frame (COMPOSITION_SENTENCE).
SERIAL_FRAME_SENTENCE = (
    "One continuous picture fills the whole tall frame, the people in its upper two thirds."
)
#: The paper and the glass in a serial still carry no writing: the look forbids written words,
#: and the vision gate still read lettering and number grids on a ledger drawn for «pauses
#: before the number» (2026-10-12, 08:03, scene 4 of f06808c9, twice). Said without the
#: words the prompt check reads as a request for text («lettering», «digits»).
#: 2026-10-15 11:22Z (episode 2, scenes 5 and 7): the sentence used to say «every screen is
#: dark or a plain soft glow», and the Director locked her refusals on those very words — a
#: screen named is a screen drawn, lit, in a room the plan gave none; the room's own sentence
#: (`series_look.room_sentence`) says where a monitor exists and that it is dark. No screen is
#: named here; the paper is named only as what it is when present.
SERIAL_BLANK_SENTENCE = (
    "The desk surfaces are plain and clear of plates, labels and signs, and any sheet of "
    "paper is blank."
)
#: A function word left hanging at the end of a cut phrase ("wearing", "with", "in a").
_DANGLING_TAIL = re.compile(
    r"(?:\s+\b(?:wearing|with|in|a|an|the|and|or|but|over|of|on|at|to|for|under|as|his|her"
    r"|their|its)\b)+$",
    re.IGNORECASE,
)


def _clean_cut(text: str) -> str:
    """A cut phrase without a function word hanging at its end."""
    if re.search(
        r"\b(?:behind|beside|with|towards?|for|to|near|opposite|past)\s+(?:her|him|them|it)$",
        text.rstrip(" ,;:-"),
        re.IGNORECASE,
    ):
        return text.rstrip(" ,;:-")
    return _DANGLING_TAIL.sub("", text.rstrip(" ,;:-")).rstrip(" ,;:-")


def _still_moment(action: str) -> str:
    """The first moment of a serial beat's action, for its still: each person's clause up to
    its first later moment («then», «finally», «eventually», «next,»). The character's
    identity/position introduction stays beside the first action, never replacing it.
    A clause that opens with a later moment is left out. An image model draws a chain of
    moments as stacked panels (2026-10-11, f06808c9), and a chain joined by commas alone
    («opens both hands as if starting a pitch, the gesture stalls halfway and dies, he
    restarts his sentence») is still a chain (2026-10-12, 08:01, scene 3 twice more); the
    whole chain is the motion prompt's (`compose_serial_motion`)."""
    kept: list[str] = []
    for clause in re.split(r";\s*", " ".join(str(action or "").split()).rstrip(". ")):
        part = clause.strip()
        if not part or lint.SEQUENCE_OPENER.match(part):
            continue
        marks = [
            found.start()
            for found in (lint.STILL_THEN.search(part), lint.LATER_MOMENT.search(part))
            if found
        ]
        if marks:
            part = _then_head(part, min(marks))
        # The camera's path and a tempo are the clip's, never the picture's (2026-10-13).
        part = _clean_cut(lint.without_tempo(lint.static_clause(_first_moment(part))))
        if part:
            kept.append(part)
    return "; ".join(kept)


#: After a comma, a new moment: a pronoun or «then» opening it, or a verb of motion in its
#: first three words («pauses before», «the gesture stalls», «restarts his») — never a tail
#: that only describes the same moment («arms crossed», «eyes on the street», «hands on
#: hips», «a brass pen in hand»), which stays.
_MOMENT_OPENER = re.compile(r"^(?:he|she|they|it|we|then|now|next|and then)\b", re.IGNORECASE)
_SPATIAL_INTRO = re.compile(
    r"^(?:behind|beside|next to|in front of|opposite)\s+(?:her|him|them|it)$", re.IGNORECASE
)
_MOMENT_VERB = re.compile(
    r"\b(?:pauses?|stalls?|dies|restarts?|holds?|lets?|waits?|stops?|starts?|begins?|ends?"
    r"|goes|comes?|says?|answers?|replies|shrugs?|sighs?|freezes?|grins?|frowns?|blinks?"
    r"|swallows?|exhales?|inhales?|straightens?|settles?|folds?|slides?|flips?|picks?|sets?"
    r"|places?|puts?|checks?|reads?|clicks?|scrolls?|stares?|squints?|tilts?|hovers?|rests?"
    r"|lands?|falls?|collapses?|spreads?|counts?|lists?|mouths?|murmurs?|snaps?|slams?|sips?"
    r"|drinks?|eats?|bites?|chews?|glares?|peers?|flinches|winces?|clears|closes?|opens?"
    r"|lowers?|raises?|drops?|lifts?|turns?|looks?|leans?|nods?|shakes?|taps?|points?)\b",
    re.IGNORECASE,
)


def _next_moment(tail: str) -> bool:
    words = tail.split()
    if not words:
        return False
    if _MOMENT_OPENER.match(tail):
        return True
    if words[0].lower().endswith("ing"):
        # A participle after the name's comma («Kael, leaning back, arms crossed») describes
        # this moment; a new one has its own finite verb.
        return False
    head = " ".join(words[:3])
    return bool(_MOMENT_VERB.search(head) or lint.SUBJECT_MOTION.search(head))


def _first_moment(clause: str) -> str:
    """One person's clause up to the comma that begins its next moment; the descriptive
    tails of the same moment («leaning back, arms crossed») stay."""
    head, sep, rest = clause.partition(",")
    while sep:
        has_action = bool(_MOMENT_VERB.search(head) or lint.SUBJECT_MOTION.search(head))
        if _next_moment(rest.strip()) and has_action and not _SPATIAL_INTRO.fullmatch(head.strip()):
            break
        more, sep, rest = rest.partition(",")
        head = f"{head},{more}"
    return head.strip()


def _serial_framing(package: dict[str, Any], look: dict[str, Any], focus: str) -> str:
    """The still's camera: the look's fixed framing for the shot's size, the focus named;
    without a look, the first clause of the plan's camera (its framing, before its path)."""
    sizes = look.get("shot_sizes") or {}
    framing = str(sizes.get(str(package.get("shot_size") or "")) or "").replace("{name}", focus)
    framing = " ".join(framing.split()).rstrip(". ")
    if framing:
        return framing
    camera = " ".join(str(package.get("camera") or "").split())
    return _clean_cut(re.split(r"[,;:]", camera, maxsplit=1)[0]) if camera else ""


def serial_partial_characters(package: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Canonical clothing for people whose body parts enter a single's frame."""
    framed = {
        str(c.get("id") or c.get("name"))
        for c in package.get("in_frame") or []
        if isinstance(c, dict)
    }
    action = _still_moment(str(package.get("action") or ""))
    partial = []
    for character in package.get("characters") or []:
        if (
            not isinstance(character, dict)
            or str(character.get("id") or character.get("name")) in framed
        ):
            continue
        name = _short_name(character.get("name"))
        if not name:
            continue
        for clause in re.split(r"[;.!?]", action):
            if re.search(
                rf"\b{re.escape(name)}['’]s\s+[^;.!?]*\b"
                r"(?:shoulder|upper arm|forearm|hand|elbow)\b",
                clause,
                re.IGNORECASE,
            ):
                if re.search(
                    r"\b(?:shoulder|upper arm|forearm|hand|elbow)\s+(?:is |remains? )?"
                    r"(?:absent|invisible|not visible)\b|\bno shoulder\b",
                    clause,
                    re.IGNORECASE,
                ):
                    continue
                partial.append({**character, "visible_description": clause.strip()})
                break
    return partial


def partial_clothing_sentence(character: Mapping[str, Any]) -> str:
    name = _short_name(character.get("name"))
    outfit = " ".join(str(character.get("outfit") or "").split()).rstrip(". ")
    return (
        (
            f"The visible clothing of {name} matches the canonical outfit: {outfit}. "
            f"Only the body parts specified for {name} enter the frame; the face stays outside it."
        )
        if outfit
        else ""
    )


def compose_serial_prompt(package: dict[str, Any], look: dict[str, Any]) -> str:
    """The text the model receives for a serial shot, the series' look first, word for word.

    Then the room, the fixed framing for the shot's size, how one picture fills the tall
    frame, the people in frame (each as their bible describes them) and the first moment of
    the action. Required content is never cut to fit: the model-aware linter holds an
    oversized prompt for rewrite before payment. Expression, background and continuity
    stay too: a correction in those fields must not disappear under a length cap.

    2026-10-11 (f06808c9): the stills of scenes 3, 4 and 7 came back as the same picture
    three times, stacked, on both candidates. Their prompts carried the plan's camera as a
    path over time («a slow tilt down from her face to the ledger and back up») and the
    action as a chain («taps …, pauses …, then lays the pen flat»): an image model draws a
    chain as panels. The path's move and the whole chain are the motion prompt's.
    """
    people = [c for c in package.get("in_frame") or [] if isinstance(c, dict)]
    focus = _short_name(people[0].get("name")) if people else "the speaker"
    framing = _serial_framing(package, look, focus)
    # Said in sentences, never under a template label: «Camera:» and «Action:» were the
    # rubrics the first episode's stills carried (2026-10-11, f06808c9), the prompt check
    # refused them (TEMPLATE_LABEL) on every rewrite, and the Director and the Video Editor
    # went round in circles while the storyboard waited.
    action = _still_moment(str(package.get("action") or ""))
    head = [
        str(look.get("block") or "").strip(),
        f"Location: {package['location']}." if package.get("location") else "",
        # The room's own furniture, from the look's table (`series_look.room_sentence`),
        # never the block's: on 2026-10-15 the block put glowing monitors in Sarah's
        # penthouse and no rewrite could take them out (episode 2, 2d276038).
        room_sentence(look, package.get("location")),
        _sentence(framing) if framing else "",
        SERIAL_FRAME_SENTENCE,
        # Always (the Owner, 2026-10-15: «indicațiile primului prompt să fie bune, chiar
        # perfecte»): the room of the office serial always has desks, screens and paper, and
        # episode 2's scenes 2, 5 and 6 paid for monitors with content and ruled paper where
        # the plan named none. The cap no longer cuts the people (2026-10-14), so the sentence
        # costs nothing.
        SERIAL_BLANK_SENTENCE,
    ]
    if action and not action.endswith("."):
        action += "."

    # The old 980-character fit cut Sarah's pose after Marcus's action. Keep every
    # canonical identity and first moment, even on overflow, so lint can reject the
    # complete candidate instead of passing an incomplete instruction to the GPU.
    who = "; ".join(
        _identity(
            person,
            sum(len(str(person.get(key) or "")) for key in ("name", "face_hair", "outfit")) + 32,
        )
        for person in people
    )
    parts = [*head, f"In frame, facing the viewer: {who}." if who else "", _sentence(action)]
    parts.extend(partial_clothing_sentence(person) for person in serial_partial_characters(package))
    text = " ".join(part for part in parts if part)
    # The exclusions are the look's own words already ("No written words ..."); a list of
    # them under «Avoid:» is read literally by an image model and is never said here.
    for prefix, value in (
        ("", package.get("emotion")),
        ("Behind them, ", package.get("background")),
        ("As in the shot before: ", package.get("continuity")),
    ):
        said = " ".join(str(value or "").split()).rstrip(". ")
        if not said:
            continue
        if prefix and said[:1].isupper() and not said.startswith(("AMN", "I ")):
            said = said[:1].lower() + said[1:]
        text = f"{text} {_sentence(prefix + said)}"
    return text


#: The move table's size for each size of the series look's shot sizes (`serial_shot_size`).
_SERIAL_MOVE_SIZES: dict[str, str] = {
    "establishing": "wide",
    "two_shot": "medium",
    "single": "medium",
    "close": "close",
}


def _serial_camera_move(package: dict[str, Any], previous: list[str]) -> str:
    """One serial shot's camera move: the plan's own (`choose_camera_move`), unless it is the
    move of the scene before, when the shot's size chooses another, so a writer who names
    one move for every beat does not make a film of one movement (SAME_CAMERA_EVERY_SCENE)."""
    size = _SERIAL_MOVE_SIZES.get(str(package.get("shot_size") or ""), "medium")
    explicit = str(package.get("camera_move") or "").strip().lower()
    if explicit in lint.CAMERA_MOVES:
        return explicit
    if [key for key, _ in lint.camera_moves(_flatten(package.get("camera")))] == ["static"]:
        return "static"
    move = choose_camera_move(package, size, previous)
    if previous and move == previous[-1]:
        move = choose_camera_move({**package, "camera": "", "camera_move": ""}, size, previous)
    return move


#: What keeps the serial's people themselves while they move (2026-10-11, 45dc313; the
#: features named since 2026-10-15 16:41Z, a4ecf40a scene 6: «the model let the face slip
#: from one frame to the next» — her cause: the face was never fixed as its own clause).
SERIAL_FACES_SENTENCE = "Their faces stay expressive and the same people throughout."
#: Who is in a serial clip, and nobody else: said with the shot's names (`_cast_names`),
#: the tail fixed so a lock on it is the composer's (`scene_rewrite._composer_sentences`).
#: 2026-10-15 16:46Z, a4ecf40a scene 7: a single on Sarah, and «a second man appears behind
#: her from the middle frame onward» — her cause: the words never said one person, nobody
#: entering, from the first frame to the last.
SERIAL_CAST_TAIL = "nobody else enters or appears behind."
SERIAL_CAST_SENTENCE = (
    "Only {names} in the frame from first to last, the same {faces} and features throughout; "
    + SERIAL_CAST_TAIL
)


def _cast_names(package: dict[str, Any]) -> list[str]:
    """The shot's people as the clip names them, in the plan's order, each once."""
    names: list[str] = []
    for key in ("in_frame", "characters"):
        for person in package.get(key) or []:
            short = _short_name(person.get("name")) if isinstance(person, dict) else ""
            if short and short not in names:
                names.append(short)
    return names


def serial_cast_sentence(package: dict[str, Any]) -> str:
    """`SERIAL_CAST_SENTENCE` for this shot's people; empty when the plan names none."""
    names = _cast_names(package)
    if not names:
        return ""
    said = names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]
    return SERIAL_CAST_SENTENCE.format(names=said, faces="face" if len(names) == 1 else "faces")


#: The life of a serial shot beyond its lines: the people's bodies move as they speak, and
#: the room — the office picture's lamps and plants, in every room of the studio's house —
#: moves with them («Mișcare v2», 2026-10-11: the first board's clips held their people
#: still while they spoke).
SERIAL_LIFE_SENTENCE = (
    "As they speak their hands gesture, heads turn and shoulders shift, and behind them the "
    "lamp light flickers softly and the plants stir."
)
#: Where a serial clip ends, from the plan's ``ending_frame``. 2026-10-12, f06808c9 scene 3:
#: the film's QC found «ending frame shows Marcus and Sarah in profile facing each other
#: instead of facing the viewer», and no rewrite could reach the clip's ending — the composer
#: never read the field. Said right after the action, so it survives the word budget before
#: the faces and the room do; ``{ending}`` already carries its preposition when the plan
#: wrote one («with her eyes on the pen»).
SERIAL_ENDING_SENTENCE = "The shot ends on {ending}."
_ENDING_PREPOSITION = re.compile(r"^(?:on|with|at|in|as)\b", re.IGNORECASE)
#: An ending the writer already began with the composer's own words («The shot ends on …»,
#: «The clip ends with …», «Ending on …»): those words are dropped before the sentence is said,
#: or the clip is asked «The shot ends on the shot ends on …» (2026-10-12, f06808c9 scene 4:
#: the rewrite's ending_frame began «The shot ends on the same medium close-up»).
_ENDING_LEAD = re.compile(
    r"^(?:(?:the\s+(?:shot|clip|scene|frame)|it)\s+(?:ends|closes|finishes|settles)\b"
    r"(?:\s+(?:on|with|at|in)\b)?|ending\s+(?:on|with|at|in)\b)[\s:;,.–—-]*",
    re.IGNORECASE,
)
_POSSESSIVE = re.compile(r"['’]s$")


def _action_moments(action: str) -> list[list[str]]:
    """A serial beat's action as each person's clause («;») cut into its moments, in order:
    a clause's comma that opens a new moment (`_first_moment`) begins the next one."""
    clauses: list[list[str]] = []
    for clause in re.split(r";\s*", " ".join(str(action or "").split()).rstrip(". ")):
        rest = clause.strip()
        moments: list[str] = []
        while rest:
            head = _first_moment(rest)
            if not head:
                break
            moments.append(head)
            rest = rest[len(head) :].lstrip(" ,")
        if moments:
            clauses.append(moments)
    return clauses


def _shorter_actions(action: str) -> list[str]:
    """The action said with fewer of its later moments, longest first: one later moment
    taken off at a time — from the person with the most left, the later person on a tie —
    never anyone's first moment; then each person's first moment alone (`_still_moment`)."""
    clauses = _action_moments(action)
    found: list[str] = []
    while clauses and any(len(moments) > 1 for moments in clauses):
        most = max(len(moments) for moments in clauses)
        cut = max(index for index, moments in enumerate(clauses) if len(moments) == most)
        clauses[cut] = clauses[cut][:-1]
        said = "; ".join(
            ", ".join(_clean_cut(moment) for moment in moments if _clean_cut(moment))
            for moments in clauses
        )
        found.append(_sentence(said))
    first = _still_moment(action)
    if first:
        found.append(_sentence(first))
    return [said for index, said in enumerate(found) if said and said not in found[:index]]


#: The fewest words a later person's first moment is cut to before that person is left out of
#: the action said beside the ending: a name and a verb, and what the verb acts on.
_MOMENT_MIN_WORDS = 4


def _word_level_actions(raw: str) -> list[str]:
    """The action said with only each person's first moment, the later persons' moments cut
    word by word from their end (never below `_MOMENT_MIN_WORDS`) and then left out, the last
    person first; finally the first person's first moment alone. Review of 68fa0b4
    (2026-10-12): three people's first moments, or one clause of 56 words, did not fit beside
    the ending, and the ending was dropped."""
    firsts = [moments[0] for moments in _action_moments(raw) if moments and moments[0]]
    found: list[str] = []
    for person in range(len(firsts) - 1, 0, -1):
        words = firsts[person].split()
        for size in range(len(words) - 1, _MOMENT_MIN_WORDS - 1, -1):
            cut = _clean_cut(" ".join(words[:size]))
            said = "; ".join(_clean_cut(moment) for moment in [*firsts[:person], cut])
            found.append(_sentence(said))
        firsts = firsts[:person]
        found.append(_sentence("; ".join(_clean_cut(moment) for moment in firsts)))
    if firsts:
        found.append(_sentence(_clean_cut(firsts[0])))
    return [said for index, said in enumerate(found) if said and said not in found[:index]]


def _action_for_ending(raw: str, action: str, kept: tuple[str, ...]) -> str | None:
    """The action as it may be said beside the shot's ending and its move: whole when they
    fit the motion prompt's word budget and the vendor cap together, else with its later
    moments left out, down to each person's first moment, then the later persons' first
    moments cut at word level and left out, down to the first person's first moment, before
    the ending would be. None when not even that fits.

    2026-10-12, f06808c9 scene 3: the rewrite's ending («Marcus's hands fallen to his sides,
    Sarah's dry half-smile just forming») and a 45-word action did not fit 95 words together;
    the composer kept the action whole and dropped the ending, two rewrites composed to the
    same prompt, and her review found «finalul cerut … a fost șters». The ending is where the
    clip must arrive, and the moments before it are what the clip can reach on its own: when
    one of them has to go, a later moment goes first."""
    fixed = [*kept, lint.MOTION_CLOSING]

    def fits(said: str) -> bool:
        whole = " ".join([*fixed, said])
        return lint.utf16_units(whole) <= lint.DEFAULT_PROMPT_MAX_UTF16

    if not action or fits(action):
        return action
    candidates = [*_shorter_actions(raw), *_word_level_actions(raw)]
    return next((said for said in candidates if fits(said)), None)


def serial_motion(package: dict[str, Any], look: dict[str, Any]) -> tuple[str, bool]:
    """`compose_serial_motion`'s prompt, and whether the plan's ending had to be left out
    (``ending_dropped``): not even the first person's first moment fits beside it, with the
    move said short (`MOVE_SHORT`). A dropped ending is where the clip must arrive and is not
    said: the caller asks the editor (free) to shorten the action before anything is bought
    (review of 68fa0b4, 2026-10-12)."""
    del look  # the look is in the picture; the movement is the beat's
    action = _sentence(" ".join(str(package.get("action") or "").split()))
    feeling = " ".join(
        str(package.get("motion_emotion") or package.get("emotion") or "").split()
    ).rstrip(". ")
    ending = _ending_content(package.get("ending_frame"))
    # Never «The shot ends on the shot ends on …» (`_ENDING_LEAD`): the writer's own lead-in is
    # dropped, repeatedly if it was written twice.
    while _ENDING_LEAD.match(ending):
        shorter = _ENDING_LEAD.sub("", ending, count=1).strip(" .;,")
        if shorter == ending:
            break
        ending = shorter
    ending_sentence = ""
    if ending and not lint.camera_moves(ending):
        names = {
            _short_name(person.get("name"))
            for key in ("in_frame", "characters")
            for person in package.get(key) or []
            if isinstance(person, dict) and person.get("name")
        }
        first = _POSSESSIVE.sub("", ending.split()[0].strip(",;:.'’"))
        if first not in names and not first.isupper():
            ending = ending[:1].lower() + ending[1:]
        ending_sentence = _sentence(
            SERIAL_ENDING_SENTENCE.replace("on {ending}", "{ending}").format(ending=ending)
            if _ENDING_PREPOSITION.match(ending)
            else SERIAL_ENDING_SENTENCE.format(ending=ending)
        )
    move = str(package.get("camera_move") or "static")
    two_beats = move != "static" and _seconds_of(package) >= TWO_BEAT_SECONDS
    move_sentence = MOVE_SENTENCES.get(move, MOVE_SENTENCES["static"])
    dropped = bool(ending and not ending_sentence)
    if ending_sentence:
        raw = str(package.get("action") or "")
        fitted = _action_for_ending(raw, action, (move_sentence, ending_sentence))
        if fitted is None:
            # The move said short before the ending is given up (review of 68fa0b4).
            short = MOVE_SHORT.get(move, MOVE_SHORT["static"])
            fitted = _action_for_ending(raw, action, (short, ending_sentence))
            if fitted is not None:
                move_sentence = short
        if fitted is None:
            # Nothing of the action fits beside the ending: the action is said whole, as
            # before, the ending is left out and the caller is told.
            dropped = True
            ending_sentence = ""
        else:
            action = fitted
    items = [
        (0, 0, move_sentence),
        (1, 1, action),
        (2, 2, ending_sentence),
        (2, 3, serial_cast_sentence(package)),
        (3, 4, SERIAL_FACES_SENTENCE),
        (4, 5, SERIAL_LIFE_SENTENCE),
        (6, 6, _sentence(feeling) if feeling else ""),
        (5, 7, END_BEAT if two_beats else ""),
        (0, 9, lint.MOTION_CLOSING),
    ]
    required = " ".join([move_sentence, action, ending_sentence, lint.MOTION_CLOSING])
    word_budget = max(MOTION_MAX_WORDS, len(required.split()))
    prompt = _fit_sentences(items, lint.DEFAULT_PROMPT_MAX_UTF16, word_budget)
    if len(prompt.split()) < MOTION_MIN_WORDS:
        prompt = _fit_sentences(
            [*items, (6, 6, MOTION_PAD)], lint.DEFAULT_PROMPT_MAX_UTF16, word_budget
        )
    if ending_sentence and ending_sentence not in prompt:
        dropped = True  # the vendor's cap took it after all
    return prompt, dropped


def serial_ending_dropped(package: dict[str, Any], look: dict[str, Any]) -> bool:
    """Whether `compose_serial_motion` leaves this package's ``ending_frame`` out: the action
    is too long to say beside it even cut to the first person's first moment. A rewrite that
    composes to a dropped ending asks the editor to shorten the action (free) before it is
    stored and anything is bought on it."""
    return serial_motion(package, look)[1]


def compose_serial_motion(package: dict[str, Any], look: dict[str, Any]) -> str:
    """The movement of a serial shot: the shot's own camera move (``camera_move``, a held
    camera when none) with its path and tempo, the beat's whole action as movement (its
    chain of moments included: a still is one moment, a clip is the chain), where the shot
    ends (``ending_frame``, since 2026-10-12; when the two do not fit together, the action's
    later moments give way before the ending does, `_action_for_ending`), the people's faces
    kept, the life of their bodies and of the room, the feeling, a second beat of camera on a
    beat of TWO_BEAT_SECONDS or more, and the closing every motion prompt carries.

    The feeling is ``motion_emotion`` when the Director's motion rewrite gave one
    (`scene_rewrite`: the still is composed from ``emotion`` too, so a rewrite of the
    movement alone may not touch it), else the shot's ``emotion``. The ending is left out
    when it names a camera move of its own (the clip has exactly one, ``camera_move``) and
    is said without its chain words; a name keeps its capital, anything else is lower-cased
    after «The shot ends on».

    Until 2026-10-11 a serial scene had no motion prompt at all: the motion step sent the
    still's words again (`assembler._motion_prompt`), look block, room and rubrics included.
    When not even the first person's first moment fits beside the ending, the move is said
    short (`MOVE_SHORT`); when that fails too the ending is left out and `serial_motion`
    says so (``ending_dropped``).
    """
    return serial_motion(package, look)[0]


def compose_prompt(package: dict[str, Any], bible: dict[str, Any]) -> str:
    """The text the video model actually receives, in the order a model reads best.

    Subject and action first, because that is the shot; then the world, the camera, the light;
    then what must match the shot before it; and the exclusions last. Trimmed to a length
    that keeps the important half readable — a thousand meaningless words teach nothing.
    """
    # Each value is said once. When the shot plan was missing, the writer's single line filled
    # the subject, the action, the environment and the lighting, and the model received the
    # same sentence four times with nothing about light or place in it.
    seen: set[str] = set()

    def once(value: Any) -> str:
        said = " ".join(str(value or "").split()).rstrip(". ")
        if not said or said.casefold() in seen:
            return ""
        seen.add(said.casefold())
        return said

    characters = package.get("characters") or []
    who = "; ".join(
        f"{c.get('name')}: {c.get('face_hair')}, wearing {c.get('outfit')}"
        for c in characters
        if isinstance(c, dict)
    )
    style = ", ".join(
        part
        for part in (str(bible.get("style") or "").strip(), str(bible.get("realism") or "").strip())
        if part
    )
    parts = [once(package.get("subject")), once(package.get("action"))]
    for label, value in (
        ("Character", who),
        ("Environment", package.get("environment")),
        ("Camera", package.get("camera")),
        ("Lighting", package.get("lighting")),
        ("Composition", package.get("composition")),
        ("Motion", package.get("motion")),
        ("Emotion", package.get("emotion")),
        ("Background", package.get("background")),
        ("Style", style),
        ("Palette", bible.get("palette")),
        ("Continuity", package.get("continuity")),
    ):
        said = once(value)
        if said:
            parts.append(f"{label}: {said}")
    parts.append(f"Avoid: {', '.join(str(a) for a in (package.get('avoid') or []))}")
    text = " ".join(f"{part}." for part in parts if part)
    return cut_at_sentence(text, MAX_PROMPT_CHARS)


def cut_at_sentence(text: str, limit: int) -> str:
    """``text`` on one line within ``limit`` UTF-16 units, cut after its last whole sentence.

    A prompt sliced at a character count ends mid-word, and the model reads the fragment as
    an instruction. With no sentence end inside the limit the cut is at the last whole word;
    only a single word longer than the limit is cut inside itself.
    """
    said = " ".join(str(text or "").split())
    if limit <= 0:
        return ""
    if lint.utf16_units(said) <= limit:
        return said
    used = 0
    end = 0
    for index, char in enumerate(said):
        used += lint.utf16_units(char)
        if used > limit:
            break
        end = index + 1
    head = said[:end]
    stops = [m.end() for m in re.finditer(r"[.!?](?=\s|$)", said[: end + 1]) if m.end() <= end]
    if stops:
        return head[: stops[-1]]
    if said[end : end + 1] == " ":
        return head.rstrip()
    if " " in head:
        return head.rsplit(" ", 1)[0].rstrip(" ,;:")
    return head


# ------------------------------------------------------------------ the compiler
#
# compile_prompts (2026-09-27, after the Nepal film): two prompts per filmed scene, each
# written for the model that reads it, from the shot plan's package and the film's bible.
#
# - The still prompt goes to the image model (seedream5_pro): 60-120 words of plain
#   photographic English that open with the film's look block, then the frame (shot size,
#   lens, angle), the subject, the people as the bible allows them, a 9:16 composition
#   with the lower quarter calm for captions, and the light. No codes, no hex, no "Camera:"
#   or "Motion:" line, no quotations, no "Avoid:" list: at most two inline exclusions.
# - The motion prompt goes with the approved still to the video model: 20-70 words that
#   never describe the picture again, only exactly one camera move from the enum, one motion
#   of the world, one speed word, and the closing line. Each video model has its dialect:
#   veo takes its exclusions as negativePrompt nouns and no negation in its promptText;
#   seedance and wan take short constraint sentences; Runway gen4 only positive words.
# - Caps come from the model's contract and are met by leaving out whole sentences, the
#   least important first, never by slicing.

LIVE_KIND = "LIVE"
DEFAULT_STILL_MODEL = "seedream5_pro"
DEFAULT_MOTION_MODEL = "seedance2_5"
STILL_MAX_WORDS = lint.STILL_WORDS[1]
MOTION_MIN_WORDS, MOTION_MAX_WORDS = lint.MOTION_WORDS

# «Mișcare v2» (the Owner, 2026-10-11, on the live clips of film aa170155 and the serial's
# first board f06808c9: «Pe video pare doar un zoom, și mișcări mici. Nu este capabil de mai
# mult? De cursivitate? De mișcări mai ample?»). The prompts asked for exactly that: «Slow
# push-in toward the subject.», «Static camera, held steady.», «Background details remain
# stable throughout the shot.», «barely moving». A video model does what it is told. Every
# move below is now said with its tempo and its path (where it starts, where it ends), a clip
# of TWO_BEAT_SECONDS or more gets a second beat of camera (the move eases into a hold), the
# plan's action is said as the subject's own movement, and the world keeps moving. What
# protects the picture stays: one move per clip, no text, faces as the bible says, the
# identity and continuity sentences, the closing line; and the clip QC's floors are minimums.

#: How each camera move of the enum is said. Each sentence names exactly one move (as
#: prompt_lint.camera_moves reads it), carries its tempo (prompt_lint.SPEED_WORDS) and its
#: path, and spells its own key, so a stored package's move is readable in its prompt. The
#: older keys keep their "slow": a plan or a rewrite that names them by name asked for that.
#: The move sentences name no framing of their own since 2026-10-15 17:19Z (a4ecf40a scenes 6
#: and 8: «dolly in from a wide view to a close framing» on a shot the plan fixes as a close-up —
#: the Director refused the words twice and no rewrite could change a composer sentence) and no
#: pace (scene 7: «tracking left at walking pace» on a seated subject). The framing is the
#: shot's, the move only tightens, widens or slides.
MOVE_SENTENCES: dict[str, str] = {
    "static": (
        "Static camera on a fixed tripod, steady, the life of the scene moving inside the "
        "fixed frame."
    ),
    "slow push-in": (
        "Slow push-in toward the subject, steady all the way, the framing tightening on it."
    ),
    "slow pull-back": (
        "Slow pull-back from the subject, steady all the way, the space opening around it."
    ),
    "dolly in": (
        "Steady dolly in toward the subject, the framing tightening, the foreground sliding "
        "past the lens."
    ),
    "dolly out": ("Steady dolly out from the subject, the space around it widening into view."),
    "slow pan left": (
        "Slow pan left, smooth and with a clear start and end, sweeping from the right side "
        "of the scene across to the subject."
    ),
    "slow pan right": (
        "Slow pan right, smooth and with a clear start and end, sweeping from the left side "
        "of the scene across to the subject."
    ),
    "tracking left": (
        "Steady tracking left alongside the subject, the background sliding past behind it."
    ),
    "tracking right": (
        "Steady tracking right alongside the subject, the background sliding past behind it."
    ),
    "tilt up": (
        "Smooth tilt up from the base of the scene to its top, steady, ending on the subject."
    ),
    "tilt down": (
        "Smooth tilt down from the top of the scene, steady, settling on the subject below."
    ),
    "aerial drift forward": (
        "Steady aerial drift forward over the scene, the ground sliding beneath, the horizon "
        "opening ahead."
    ),
    "pedestal up": (
        "Steady pedestal up from low at the subject to eye level, the scene rising into view "
        "behind it."
    ),
    "crane up": (
        "Steady crane up from the subject, rising and revealing the whole scene below as the "
        "camera climbs."
    ),
    "crane down": (
        "Steady crane down from high above, descending and settling on the subject as the "
        "scene closes in around it."
    ),
    "slow orbit": (
        "Slow orbit around the subject, steady, a quarter turn from its left side to its "
        "front, the background wheeling behind it."
    ),
    "handheld drift": (
        "Smooth handheld drift, the frame alive and easing slowly from the left of the "
        "subject toward its centre through the whole shot."
    ),
    "rack focus": (
        "Smooth rack focus from the foreground to the subject behind it, the focus pulling "
        "steadily as the subject moves."
    ),
}
#: Each move said short: the same one move and its tempo, without its path. Only a serial clip
#: whose action and ending cannot both be said beside the whole sentence gets it (review of
#: 68fa0b4, 2026-10-12: the ending, where the clip must arrive, was dropped instead).
MOVE_SHORT: dict[str, str] = {
    "static": "Static camera on a fixed tripod, steady.",
    "slow push-in": "Slow push-in toward the subject.",
    "slow pull-back": "Slow pull-back from the subject.",
    "dolly in": "Steady dolly in toward the subject.",
    "dolly out": "Steady dolly out from the subject.",
    "slow pan left": "Slow pan left across the scene.",
    "slow pan right": "Slow pan right across the scene.",
    "tracking left": "Steady tracking left alongside the subject.",
    "tracking right": "Steady tracking right alongside the subject.",
    "tilt up": "Smooth tilt up to the subject.",
    "tilt down": "Smooth tilt down to the subject.",
    "aerial drift forward": "Steady aerial drift forward over the scene.",
    "pedestal up": "Steady pedestal up to eye level.",
    "crane up": "Steady crane up from the subject.",
    "crane down": "Steady crane down to the subject.",
    "slow orbit": "Slow orbit around the subject.",
    "handheld drift": "Smooth handheld drift toward the subject.",
    "rack focus": "Smooth rack focus to the subject.",
}
#: The move said for an intent whose move is not in the table (a package edited by hand).
DEFAULT_MOVE = "dolly in"

#: The moves that suit each shot size, best first, for a plan that named none. "static" is
#: never chosen for a plan that did not ask for it: the Nepal clips, asked for "no camera
#: movement" on every scene, came back almost still (mean YDIF about 1.1 of 255). Nor are
#: "slow orbit" and "rack focus": an orbit turns the people in frame toward the camera, a
#: rack focus moves nothing by itself; both are a plan's deliberate choice, never a default.
SIZE_MOVES: dict[str, tuple[str, ...]] = {
    "aerial": ("aerial drift forward", "crane up", "tracking right", "dolly in"),
    "wide": ("tracking right", "dolly in", "crane up", "tracking left", "dolly out"),
    "medium": ("dolly in", "tracking left", "crane down", "handheld drift"),
    "close": ("dolly in", "crane down", "tracking right", "tilt up"),
    "detail": ("dolly in", "crane down", "tilt down", "pedestal up"),
}
#: A clip this long gets two beats of camera: the move, then (said without "then") a hold.
TWO_BEAT_SECONDS = 7.0
#: The second beat: the move eases into a hold while the scene goes on moving. Said in words
#: that name no move of the enum, so the prompt still names exactly one (CAMERA_COUNT).
END_BEAT = (
    "In the final seconds the camera eases to a steady hold on the subject, and everything "
    "in the frame keeps moving."
)
#: The amplitude of a shot's movement: AMPLE is the rule; MEASURED is one step down, for a
#: redo of a clip whose movement deformed the picture (clip QC: faces, warping, a broken
#: shot). The Director's rewrite may set ``motion_amplitude`` on the package; the compiler
#: never dials it down by itself.
AMPLE = "ample"
MEASURED = "measured"
AMPLITUDES = (AMPLE, MEASURED)
MEASURED_SENTENCE = (
    "The move stays smooth and moderate, and every shape and edge keeps its form from the "
    "first frame to the last."
)

COMPOSITION_SENTENCE = (
    "Vertical 9:16 frame, main subject in the upper two thirds, lower quarter calm and uncluttered."
)
STILL_EXCLUSIONS = "No text, no logo."
PEOPLE_SENTENCE = (
    "Any people appear only as small distant figures seen from behind, faces turned away."
)
#: The same rule for any frame that is not wide — a medium shot, a close-up, a detail of hands,
#: a back, a shoulder — where «small distant figures» contradicts the shot's own scale (19:47Z,
#: the same scene rewritten as a medium shot: refused four more rounds for the wide clause).
#: 2026-10-15 18:45Z,
#: 7c26a7ce scene 2 (the scientist's hands lifting the bar, a detail shot): the Director
#: refused the wide-frame clause six rounds running, and the Editor's rewrite could not
#: remove a sentence the composer always says — a tool defect, not his.
CLOSE_PEOPLE_SENTENCE = (
    "The person is seen only from behind, the face turned away from the camera and never shown."
)
#: The bible's face rule said for a scene that shows nobody: it never asks for figures, and
#: the linter reads it as the rule kept (`prompt_lint.NO_FACE_STATED`). Said positively, with
#: no word for a person in it: until 2026-10-12 it was «There are no people in the frame.»,
#: and five of the Director's briefs that day (Higgs-2 scenes 1, 3, 5; the cyclotron's 4, 5)
#: diagnosed it — an image model reads past the negation and draws the people it names —
#: asked for it to be deleted, and the next compile put it back (ADR-POSITIVE-PROMPTS-ONLY).
NO_PEOPLE_SENTENCE = "The frame holds only the place and the things named."
FACES_CONSTRAINT = (
    "The people remain seen from behind throughout, faces turned away from the camera."
)
#: Said when a motion prompt is under its word floor. Until 2026-10-11: "The movement stays
#: smooth and unhurried." (prompt_lint.LEGACY_STILLNESS).
MOTION_PAD = "Everything in the frame keeps moving smoothly through the whole clip."
MOTIONLESS_PAD = (
    "The lighting, object geometry and background remain consistent throughout the shot."
)
MOTIONLESS_END_BEAT = "In the final seconds the camera eases to a steady hold."
#: The world's motion when the plan names none. Setting-neutral: an airless scene gets no
#: haze or wind from it. Until 2026-10-11: "Background details remain stable throughout the
#: shot." — the stillness the Owner then saw in every clip.
DEFAULT_WORLD_MOTION = (
    "Shadows drift and the light shifts across the scene, its smallest details stirring."
)
_MOTIONLESS_WORLD = re.compile(
    r"\bnothing\s+(?:(?:in|around)\s+(?:the\s+)?(?:world|scene|background)\s+)?moves\b",
    re.IGNORECASE,
)
#: A chain word inside a plan's motion or action, read for the video model: the chain is
#: wanted (it is the clip's sequence), the word is not (THEN_CHAIN blocks on seedance), so
#: "pauses, then lays the pen flat" is said as "pauses, lays the pen flat". "Since then",
#: "by then", "back then" are about the past and stay (prompt_lint.STILL_THEN's rule).
_CHAIN_WORD = re.compile(
    r",?\s*\b(?:(?:and\s+)?(?<!\bsince )(?<!\buntil )(?<!\btill )(?<!\bby )(?<!\bback )"
    r"(?<!\beven )(?<!\bjust )then|after\s+that|afterwards|next,)\b\s*,?\s*",
    re.IGNORECASE,
)
VEO_NEGATIVE = ("text", "subtitles", "logo", "watermark")
VEO_FACES = "human faces"

_COLOUR_WORDS = re.compile(
    r"\b(?:blue|blues|gold|golden|grey|gray|greys|brown|browns|green|greens|red|reds|amber"
    r"|ochre|teal|orange|yellow|purple|violet|pink|crimson|beige|cyan|magenta|silver"
    r"|palette|hue|tones?)\b",
    re.IGNORECASE,
)
_CAMERA_WORDS = re.compile(
    r"\b(?:camera|lens|shot|pan|pans|panning|tilt\w*|zoom\w*|dolly|static|locked|tracking"
    r"|handheld|orbit\w*|push|pull|crane|frame|framing|angle|movement)\b",
    re.IGNORECASE,
)
_PERCENT = re.compile(r"\d\s?%|\bper\s?cent\b", re.IGNORECASE)
_FACE_KEPT = re.compile(r"\bfrom\s+behind\b|\bdistant\b", re.IGNORECASE)
_QUOTE_MARKS = re.compile('["“”„]')
_NOT_A_PERSON = re.compile(r"\b(?:no|without|not\s+a|zero)\s+(?:\w+\s+)?$")


#: A pointer at another scene said after what it qualifies, with the words that carry it:
#: "the void of scenes 2 and 3", "the tunnel from scene 1", "a tunnel similar to scene 2's",
#: "drift as in scene 2", "a street seen in the previous scene".
_TRAILING_POINTER = re.compile(
    r"(?:\s*,)?\s+(?:(?:seen|shown|used|introduced|established)\s+)?"
    r"(?:(?:similar|identical|equal|comparable)\s+)?"
    r"(?:as|like|from|of|in|than|to)\s+(?:in\s+)?(?:the\s+)?"
    rf"(?:{lint.SCENE_REFERENCE.pattern})\s*$",
    re.IGNORECASE,
)
#: A pointer said as the owner or the label of a thing: "scene 1's tunnel", "the previous
#: scene's street", "the scene 1 tunnel". What is left is the thing itself: "the tunnel".
_OWNING_POINTER = re.compile(
    rf"(?:\bthe\s+)?(?:{lint.SCENE_REFERENCE.pattern})(?<='s)\s+"
    rf"|\bthe\s+(?:{lint.SCENE_NUMBERED})\s+(?=[a-z])",
    re.IGNORECASE,
)
#: "Identical to the tunnel": once the pointer is gone, the likeness points at nothing.
_LIKENESS = re.compile(
    r"^(?:the\s+)?(?:same|identical|similar|matching)\s+(?:to|as)\s+", re.IGNORECASE
)
#: "The same void as scene 2": once the pointer is gone, "same" points at nothing.
_SAME_AS = re.compile(r"\b(?:same|identical|matching)\s+", re.IGNORECASE)
#: What a pointer leaves when it was not said around a whole picture: "Back tunnel" (from
#: "Back in the scene 1 tunnel"), "to the tunnel", "A tunnel similar", "lit the same".
_BROKEN_START = re.compile(
    r"^(?:back|again|once|still|also|too|to|of|as|than|like|from|by|with|for|and|or|but"
    r"|similar|identical|same|matching)\b",
    re.IGNORECASE,
)
_BROKEN_END = re.compile(
    r"\b(?:similar|identical|same|like|matching|equal|comparable)$", re.IGNORECASE
)
#: A plan that asks for a layout around its pictures: "Split screen of the forest and the
#: cleared land", "A before-and-after view of the glacier". What follows is said as one.
_PANEL_FRAMING = re.compile(
    r"^(?:(?:a|an|the)\s+)?(?:split[- ]?screen|before[- ]and[- ]after|side[- ]by[- ]side"
    r"|diptych|triptych|polyptych|montage|(?:photo\s+)?collage)"
    r"(?:\s+(?:views?|images?|shots?|comparisons?|pictures?|photos?|frames?|panels?"
    r"|compositions?|layouts?))?\s+(?:of|showing|with|between|comparing)\s+",
    re.IGNORECASE,
)
#: "The street before and after the flood": the first moment is "before the flood".
_BEFORE_AND_AFTER = re.compile(r"\bbefore[- ]and[- ]after\b(?=\s+\w)", re.IGNORECASE)


def without_scene_reference(part: str) -> str:
    """The clause with its pointer at another scene taken out; "" when nothing whole is left.

    An image or video model cannot know what "scene 1" looks like (film babcf272, 2026-10-09:
    "the identical tunnel from scene 1"). A pointer said after a whole picture or as its
    owner leaves that picture: "The same near-black void as scene 2" is "The near-black
    void", "scene 1's tunnel" is "the tunnel". Any other pointer takes its clause with it
    ("Back in the scene 1 tunnel" left "Back tunnel"; review, 2026-10-09).
    """
    if not lint.SCENE_REFERENCE.search(part):
        return part
    left = _OWNING_POINTER.sub("the ", _TRAILING_POINTER.sub("", part))
    left = _SAME_AS.sub("", _LIKENESS.sub("", left.strip()))
    left = " ".join(left.split()).strip(" ,;:-'")
    if (
        len(left.split()) < 2
        or lint.SCENE_REFERENCE.search(left)
        or lint.dangling(left)
        or not re.search(r"[A-Za-z]", left)
        or _BROKEN_START.match(left)
        or _BROKEN_END.search(left)
    ):
        return ""
    return left


def _then_head(part: str, start: int) -> str:
    """The words of a clause before its later moment, without a hanging "and"."""
    head = part[:start].rstrip(" ,;:-")
    return re.sub(r"(?:\s+\b(?:and|or|but)\b)+$", "", head, flags=re.IGNORECASE).strip()


_SUBJECT_CAMERA_ORIENTATION = re.compile(
    r"\b(?:with\s+)?(?:his|her|their|its|the)\s+"
    r"(?:back|backs|shoulder|shoulders|side|sides|face|faces|front|profile)\s+"
    r"(?:turned\s+)?(?:to|towards?|away\s+from)\s+(?:the\s+)?camera\b",
    re.IGNORECASE,
)


def _clauses_of(text: Any, *, motion: bool = False) -> list[str]:
    """The clauses of a plan field that may enter a prompt, in the plan's words.

    Dropped: codes, hex colours (their parentheses too), a negation ("no camera movement"
    is still about the camera), a percentage, a chart, a black screen or a title (those
    scenes are composed locally), writing, a quotation, a label such as "Direction:", a
    value that says nothing ("None", "n/a"), the head of a broken sentence (a clause that
    ends in "the", "of", "and"...), and a pointer at another scene ("from scene 1"; the rest
    of its clause stays when it is whole). For the motion prompt also anything about the
    camera, a colour or a "then" chain.

    The still prompt is one moment, the first frame of the shot (film babcf272, 2026-10-09:
    a field that listed three moments came back as three stacked panels). Its fields are
    read up to the first later moment: the words before a "then", "dissolves into" or "cuts
    to" are kept, and the rest of that clause and every later clause of the field are not
    ("finally", "later", "next", "secondly"...). A field that says "First ..." is read for
    that first moment only. A later-moment word that opens the field is about the scene
    before it ("Finally, the cluster settles" is this shot's one moment) and is taken off.
    A layout is read as its first picture: "Before: X. After: Y" is X, "Split screen of X"
    is X, "the street before and after the flood" is "the street before the flood". A
    parenthetical aside is closed up, never split into fragments (prompt_lint.without_asides).
    """
    said = _flatten(text).replace("’", "'").replace("‘", "'")
    said = lint.without_asides(re.sub(r"\(\s*\)", "", _HEX_COLOUR.sub("", said)))

    def usable(part: str) -> str:
        part = without_scene_reference(part)
        if not motion:
            # A still is one frozen moment (the Owner, 2026-10-13: «în promptul de imagine nu
            # are ce să caute indicații de mișcare»): the camera's movement leaves the clause
            # (a clause that only moves the camera is the motion's alone), and so do a tempo
            # and a span of the clip.
            part = lint.without_tempo(lint.static_clause(part))
            if not part:
                return ""
        if (
            not re.search(r"[A-Za-z]", part)
            or lint.NONE_WORD.match(part)
            or lint.dangling(part)
            or lint.ENUM_CODE.search(part)
            or lint.NEGATION.search(part)
            or lint.INLINE_EXCLUSION.search(part)
            or _PERCENT.search(part)
            or lint.classify_kind_phrase(part)
            or _TEXT_REQUEST.search(part)
            or _QUOTE_MARKS.search(part)
        ):
            return ""
        camera_instruction = _SUBJECT_CAMERA_ORIENTATION.sub("", part)
        if motion and (
            any(
                match.group(0).casefold() not in ("locked", "static", "movement")
                for match in _CAMERA_WORDS.finditer(camera_instruction)
            )
            or lint.camera_moves(part)
            or lint.THEN_CHAIN.search(part)
        ):
            return ""
        return part

    kept: list[str] = []
    opened = False  # a clause of the field has been read
    first_only = False  # the field said "First ...": a still shows that moment only
    panelled = False  # a clause was labelled as one picture of a layout ("Before:")
    # Motion lists are one proposition: splitting "no figure, reflection, or ghost image
    # appears" at commas loses its negation and asks the model for a ghost. Positive object
    # lists likewise need their shared predicate ("flask, stand and valve stay locked").
    clauses: list[str] = []
    for proposition in re.split(r"[;.!?]\s*|\s*\(|\)\s*|\s+-{1,2}\s+|\s*—\s*", said):
        if motion:
            # A later-moment clause or scene pointer must not erase its independent
            # neighbours. Keep ordinary object lists and the scope of negations whole.
            independent = lint.THEN_CHAIN.search(proposition) or lint.SCENE_REFERENCE.search(
                proposition
            )
            scoped_negative = lint.NEGATION.search(proposition) or lint.INLINE_EXCLUSION.search(
                proposition
            )
            clauses.extend(
                proposition.split(",") if independent and not scoped_negative else [proposition]
            )
        else:
            for clause in proposition.split(","):
                if lint.NEGATION.search(clause) or lint.INLINE_EXCLUSION.search(clause):
                    # Its negation scopes the rest of this list, up to the next proposition.
                    break
                clauses.append(clause)
    for clause in clauses:
        raw = " ".join(clause.split()).strip(" -:/")
        if motion:
            part = usable(_LABEL_PREFIX.sub("", raw))
            if part:
                kept.append(part)
            continue
        if not re.search(r"[A-Za-z]", raw):
            continue
        if lint.PANEL_LABEL.match(raw):
            if panelled:
                break
            panelled = True
        part = _LABEL_PREFIX.sub("", raw)
        part = _BEFORE_AND_AFTER.sub("before", _PANEL_FRAMING.sub("", part))
        first = lint.FIRST_OPENER.match(part)
        if first:
            first_only = True
            part = part[first.end() :]
        elif not opened:
            part = lint.LATER_START.sub("", part)
        elif lint.SEQUENCE_OPENER.match(part):
            break
        opened = True
        marks = [
            found.start()
            for found in (lint.STILL_THEN.search(part), lint.LATER_MOMENT.search(part))
            if found
        ]
        if marks:
            head = usable(_then_head(part, min(marks)))
            if head:
                kept.append(head)
            break
        said_something = bool(re.search(r"[A-Za-z]", part))
        part = "" if lint.PANEL_LAYOUT.search(part) else usable(part)
        if part:
            kept.append(part)
        if first_only and said_something:
            break
    return kept


def _phrase(clauses: list[str], max_words: int) -> str:
    """Whole clauses joined while they fit ``max_words``; a first clause alone that does
    not fit is kept to its first ``max_words`` words, never ending on "the", "of" or "and"
    (a subject that is one long sentence still names its subject)."""
    fitted: list[str] = []
    count = 0
    for clause in clauses:
        words = len(clause.split())
        if count + words > max_words:
            if not fitted:
                head = clause.split()[:max_words]
                while len(head) > 1 and lint.dangling(" ".join(head)):
                    head.pop()
                fitted.append(" ".join(head))
            break
        fitted.append(clause)
        count += words
    return ", ".join(fitted)


def _sentence(text: str) -> str:
    said = " ".join(str(text or "").split()).strip(" ,;:")
    if not said:
        return ""
    said = said[:1].upper() + said[1:]
    return said if said.endswith((".", "!", "?")) else f"{said}."


def _person_window(text: str, start: int) -> str:
    """The words around a person mention, as prompt_lint reads them: its own sentence,
    three words before and six after."""
    offset = 0
    for sentence in re.split(r"(?<=[.!?;])\s+", text):
        begin = text.find(sentence, offset)
        if begin <= start < begin + len(sentence):
            words = list(re.finditer(r"\S+", sentence))
            index = next(
                (i for i, w in enumerate(words) if w.start() <= start - begin < w.end()), 0
            )
            first = words[max(0, index - 3)].start()
            last = words[min(len(words) - 1, index + 6)].end()
            return sentence[first:last]
        offset = begin + len(sentence)
    return ""


def hide_faces(text: str) -> str:
    """Every person the text shows, kept from behind: "seen from behind" is added after a
    person mention that has neither "from behind" nor "distant" among its nearby words."""
    said = text
    for _ in range(32):
        changed = False
        for match in lint.PERSON.finditer(said):
            before = said[max(0, match.start() - 16) : match.start()].lower()
            if _NOT_A_PERSON.search(before):
                continue
            if _FACE_KEPT.search(_person_window(said, match.start())):
                continue
            said = f"{said[: match.end()]} seen from behind{said[match.end() :]}"
            changed = True
            break
        if not changed:
            break
    return said


#: Who else a shot may show, besides the linter's people (`prompt_lint.PERSON`): the trades a
#: factual film names (a physicist at a bench), someone said by a pronoun, and the parts of a
#: person a face rule leaves in frame. Read only to decide whether a scene shows anybody, so a
#: scene of objects can be said to be empty (`NO_PEOPLE_SENTENCE`); a word missed here only
#: keeps the older sentence, never a face.
_ALSO_PEOPLE = re.compile(
    r"\b(?:scientists?|physicists?|chemists?|engineers?|researchers?|technicians?|operators?"
    r"|astronauts?|cosmonauts?|inventors?|professors?|teachers?|assistants?|pilots?|crew"
    r"|staff|team|audience|spectators?|passengers?|drivers?|miners?|sailors?|guards?|police"
    r"|firefighters?|athletes?|players?|dancers?|musicians?|artists?|writers?|journalists?"
    r"|reporters?|customers?|visitors?|tourists?|scholars?|colleagues?|someone|somebody"
    r"|anyone|everyone|he|she|him|his|her|hers|hands?|fingers?|silhouettes?|humans?"
    r"|individuals?|adults?|youths?|teens?|teenagers?|babies|baby|guests?|patients?)\b",
    re.IGNORECASE,
)


def _shows_people(text: str) -> bool:
    # A unit of distance is not an actor. Do not inject people into a still because
    # a plan says «a finger's-width gap» or «a hand's breadth».
    text = re.sub(
        r"\b(?:fingers?|hands?)(?:['’]s)?[-\s]+(?:width|breadth|span|length)\b",
        "small",
        text,
        flags=re.IGNORECASE,
    )
    for pattern in (lint.PERSON, _ALSO_PEOPLE):
        for match in pattern.finditer(text):
            if match.group(0).lower() == "hand" and text[match.end() :].startswith("-drawn"):
                continue
            before = text[max(0, match.start() - 16) : match.start()].lower()
            if not _NOT_A_PERSON.search(before):
                return True
    return False


def shot_frame(camera: Any, shot_type: Any = "") -> tuple[str, str]:
    """(size, sentence) of the plan's frame: the shot size, the lens and the angle, in
    words. Anything the plan said about moving the camera stays out of the still."""
    text = f"{_flatten(camera)} ".lower()
    fallback = str(shot_type or "").lower().replace("_", " ")
    size = ""
    label = ""
    for source in (text, fallback):
        if re.search(r"extreme\s+wide", source):
            size, label = "wide", "Extreme wide shot"
        elif re.search(r"\baerial\b|\bdrone\b|bird'?s[- ]eye", source):
            size, label = "aerial", "Aerial wide shot"
        elif re.search(r"medium[- ](?:wide|long)", source):
            size, label = "wide", "Medium wide shot"
        elif re.search(r"\bwide\b|\bestablishing\b|\blong shot\b", source):
            size, label = "wide", "Wide establishing shot"
        elif re.search(r"medium[- ]close", source):
            size, label = "close", "Medium close-up shot"
        elif re.search(r"extreme\s+close|\bmacro\b|\bdetail\b|\binsert\b", source):
            size, label = "detail", "Detail shot"
        elif re.search(r"close[- ]?up|closeup", source):
            size, label = "close", "Close-up shot"
        elif re.search(r"\bmedium\b|\bmid[- ]shot\b", source):
            size, label = "medium", "Medium shot"
        if size:
            break
    if not size:
        size, label = "medium", "Medium shot"
    parts = [label]
    lens = re.search(r"\b(\d{2,3})\s?mm\b", text)
    if lens:
        parts.append(f"{lens.group(1)}mm lens")
    angle = re.search(r"\b(low|high|eye[- ]level|overhead|top[- ]down)(?:\s+angle)?\b", text)
    if angle:
        word = angle.group(1).replace(" ", "-")
        parts.append(word if word in ("overhead", "top-down") else f"{word} angle")
    return size, _sentence(", ".join(parts))


def choose_camera_move(
    package: dict[str, Any],
    size: str,
    previous: list[str] | tuple[str, ...] = (),
    *,
    avoid: Sequence[str] = (),
) -> str:
    """The one camera move a scene's clip makes.

    The plan's own choice wins: its ``camera_move`` field, else the one move its camera
    text names ("static" and "no movement" name none). Otherwise the move that suits the
    shot size, never the move of the scene before, so the film's camera varies, and none of
    ``avoid`` (the compiler keeps an orbit away from people shown from behind: a quarter
    turn around them shows their faces).
    """
    stated = str(package.get("camera_move") or "").strip().lower()
    if stated in lint.CAMERA_MOVES:
        return stated
    named = [
        move for move, _ in lint.camera_moves(_flatten(package.get("camera"))) if move != "static"
    ]
    if len(named) == 1:
        return named[0]
    choices = SIZE_MOVES.get(size) or SIZE_MOVES["medium"]
    last = previous[-1] if previous else None
    allowed = [move for move in choices if move not in avoid] or list(choices)
    return next((move for move in allowed if move != last), allowed[0])


def _fit_sentences(items: list[tuple[int, int, str]], cap: int, max_words: int) -> str:
    """Sentences chosen by rank (0 first), said in their order.

    First the word budget decides what the prompt says; then the contract's cap (UTF-16
    units) takes whole sentences out of that prompt, the least important first, so a capped
    prompt is always the uncapped one with sentences left out, never a slice of it. When
    not even one sentence fits the cap, the first is cut at its last whole word.
    """

    def choose(pool: list[tuple[int, int, str]], limit: int | None) -> list[tuple[int, str]]:
        chosen: list[tuple[int, str]] = []
        for _rank, order, text in sorted(pool):
            if not text:
                continue
            candidate = " ".join(t for _, t in sorted([*chosen, (order, text)]))
            if len(candidate.split()) <= max_words and (
                limit is None or lint.utf16_units(candidate) <= limit
            ):
                chosen.append((order, text))
        return chosen

    said = {order for order, _ in choose(items, None)}
    chosen = choose([item for item in items if item[1] in said], cap)
    if not chosen:
        first = next((text for _rank, _order, text in sorted(items) if text), "")
        return cut_at_sentence(first, cap)
    return " ".join(text for _, text in sorted(chosen))


def _motion_family(model_id: Any) -> str | None:
    return lint.model_family(model_id) if isinstance(model_id, str) else None


def _contract_model(contract: Any, key: str, default: str) -> str:
    if isinstance(contract, dict):
        for name in (key, "model") if key == "model_id" else (key,):
            value = contract.get(name)
            if isinstance(value, str) and value:
                return value
    return default


def _continuous(text: Any) -> str:
    """A plan's motion or action as one continuous movement: its chain words taken out, the
    chain itself kept ("taps the pen, pauses, then lays it flat" is the clip's sequence)."""
    return " ".join(_CHAIN_WORD.sub(", ", _flatten(text)).replace(" ,", ",").split())


def _seconds_of(package: dict[str, Any]) -> float:
    """The scene's planned length in seconds, 0 when the package does not say."""
    value = package.get("seconds")
    if isinstance(value, bool) or not isinstance(value, int | float | str):
        return 0.0
    try:
        return max(0.0, float(value))
    except ValueError:
        return 0.0


def _motion_intent(
    package: dict[str, Any], move: str, faces_banned: bool, people: bool
) -> dict[str, Any]:
    """What moves in the scene, model-neutral: the move, the world's motion, the subject's,
    the clip's length and the movement's amplitude.

    The world's motion is the first clause of the plan's motion, then its action, then its
    environment, that names something the world does (cloud, wind, dust, shadows, curtains)
    in at least three words; the subject's is what else the plan's motion says, and then
    every clause of the plan's action that carries a verb of motion (prompt_lint.
    SUBJECT_MOTION: stands, walks to the window, turns, hands over the ledger; spins, pulses)
    and was not said already. Neither describes the picture. Chains are kept as sequences
    without their "then" (`_continuous`).
    """
    from_motion = _clauses_of(_continuous(package.get("motion")), motion=True)
    from_action = _clauses_of(_continuous(package.get("action")), motion=True)
    candidates = [
        *from_motion,
        *from_action,
        *_clauses_of(package.get("environment"), motion=True),
    ]
    explicit_stillness = next((c for c in from_motion if _MOTIONLESS_WORLD.search(c)), "")
    world = explicit_stillness or next(
        (
            clause
            for clause in candidates
            if lint.ENVIRONMENT_MOTION.search(clause)
            and not _shows_people(clause)
            and len(clause.split()) >= 3
        ),
        "",
    )
    subject_clauses = [c for c in from_motion if c != world]
    said = {clause.casefold() for clause in subject_clauses} | {world.casefold()}
    action_clauses: list[str] = []
    for clause in from_action:
        key = clause.casefold()
        if key in said or not lint.SUBJECT_MOTION.search(clause):
            continue
        said.add(key)
        action_clauses.append(clause)
    subject = ", ".join(subject_clauses)
    amplitude = str(package.get("motion_amplitude") or AMPLE).strip().lower()
    return {
        "camera_move": move,
        "world": _sentence(world) if world else DEFAULT_WORLD_MOTION,
        "subject": _sentence(subject),
        "subject_clauses": [_sentence(clause) for clause in subject_clauses],
        "action_clauses": [_sentence(clause) for clause in action_clauses],
        "seconds": _seconds_of(package),
        "amplitude": amplitude if amplitude in AMPLITUDES else AMPLE,
        "constraints": _scene_constraints(package),
        "faces_banned": faces_banned,
        "people": people,
        "ending_frame": str(package.get("ending_frame") or ""),
    }


def _intent_clauses(intent: dict[str, Any], key: str) -> list[str]:
    """A stored intent's list of sentences under ``key``; none for an intent from before."""
    value = intent.get(key)
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item or "").strip()]


def render_motion(
    intent: dict[str, Any], family: str | None, cap: int = lint.DEFAULT_PROMPT_MAX_UTF16
) -> tuple[str, str | None]:
    """(promptText, negativePrompt or None) for one video model, from a motion intent.

    The camera's move with its path and tempo opens; the world's motion follows; then every
    clause of the plan's motion and the action's verbs of motion, each its own sentence; a
    clip of TWO_BEAT_SECONDS or more ends its camera on a hold (END_BEAT); a MEASURED
    amplitude says the move stays moderate and the shapes keep their form; the face rule and
    the closing line end it. A stored intent of a film planned before 2026-10-11 is said in
    these words too: its stillness world ("remain stable") is replaced, its missing length
    reads as one beat.
    """
    move = str(intent.get("camera_move") or "")
    camera = MOVE_SENTENCES.get(move, MOVE_SENTENCES[DEFAULT_MOVE])
    positive_only = family in ("veo", "gen4")
    closing = lint.VEO_MOTION_CLOSING if positive_only else lint.MOTION_CLOSING
    faces = bool(intent.get("faces_banned"))
    constraint = (FACES_CONSTRAINT if intent.get("people") else NO_PEOPLE_SENTENCE) if faces else ""
    negative = None
    if family == "veo":
        negative = ", ".join(
            [*((VEO_FACES,) if faces else ()), *VEO_NEGATIVE, *(intent.get("constraints") or [])]
        )
    # Every clause of the plan's motion, each its own sentence, in the plan's order: the
    # motion prompt names the visible subject in full (2026-10-11, aa170155 scene 4: "Slow
    # pull-back that widens the view. Dust motes drift slowly in the beam" named nothing, and
    # the model improvised people; the Director's brief named it). The plan's exclusions are
    # never said as "no ...": a video model reads the words, not the negation; they reach the
    # negative channel of a model that has one.
    clauses = intent.get("subject_clauses")
    subjects = clauses if isinstance(clauses, list) else [str(intent.get("subject") or "")]
    actions = _intent_clauses(intent, "action_clauses")
    world = str(intent.get("world") or "")
    if not world or world in lint.LEGACY_STILLNESS:
        world = DEFAULT_WORLD_MOTION
    at_rest = bool(_MOTIONLESS_WORLD.search(" ".join([world, *map(str, subjects)])))
    if at_rest and move == "static":
        camera = MOVE_SHORT["static"]
    amplitude = str(intent.get("amplitude") or AMPLE)
    seconds = _seconds_of(intent)
    two_beats = amplitude != MEASURED and move != "static" and seconds >= TWO_BEAT_SECONDS
    ending = _ending_sentence(intent.get("ending_frame"))
    required = [
        camera,
        *[str(c) for c in subjects],
        *actions,
        world if world != DEFAULT_WORLD_MOTION else "",
        ending,
        constraint,
        closing,
    ]
    if lint.utf16_units(" ".join(required)) > cap:
        camera = MOVE_SHORT.get(move, camera)
        required[0] = camera
    # The 95-word target is editorial guidance, not a vendor limit. It must not erase
    # the action or endpoint when both fit the model's actual UTF-16 contract.
    word_budget = max(MOTION_MAX_WORDS, len(" ".join(required).split()))
    items = [
        (0, 0, camera),
        (2 if world != DEFAULT_WORLD_MOTION else 4, 1, world),
        *[(2, 10 + index, str(clause)) for index, clause in enumerate(subjects)],
        *[(3, 100 + index, clause) for index, clause in enumerate(actions)],
        (5, 800, (MOTIONLESS_END_BEAT if at_rest else END_BEAT) if two_beats else ""),
        (1, 850, MEASURED_SENTENCE if amplitude == MEASURED else ""),
        (1, 870, ending),
        (0, 900, constraint),
        (0, 1000, closing),
    ]
    prompt = _fit_sentences(items, cap, word_budget)
    if len(prompt.split()) < MOTION_MIN_WORDS:
        prompt = _fit_sentences(
            [*items, (6, 8, MOTIONLESS_PAD if at_rest else MOTION_PAD)], cap, word_budget
        )
    return prompt, negative


def _ending_content(value: Any) -> str:
    """Remove an unusable continuity pointer without deleting the other visible clauses."""
    ending = strip_on_screen_text(_continuous(value)).strip(" .;,")
    if lint.SCENE_REFERENCE.search(ending):
        parts = re.split(r"\s*(?:[,;]|[—–]|\s+-\s+)\s*", ending)
        ending = ", ".join(part for raw in parts if (part := without_scene_reference(raw)))
    return ending


def _ending_sentence(value: Any) -> str:
    ending = _ending_content(value)
    while _ENDING_LEAD.match(ending):
        ending = _ENDING_LEAD.sub("", ending, count=1).strip(" .;,")
    if not ending or lint.camera_moves(ending):
        return ""
    if ending.split()[0].casefold() in ("the", "a", "an"):
        ending = ending[:1].lower() + ending[1:]
    return _sentence(
        f"The shot ends {ending}"
        if _ENDING_PREPOSITION.match(ending)
        else f"The shot ends on {ending}"
    )


def incomplete_plan_fields(
    package: Mapping[str, Any], *, layers: tuple[str, ...] = ("still", "motion")
) -> list[str]:
    """Find broken saved clauses without deleting them or guessing their missing words."""
    fields: set[str] = set()
    if "still" in layers:
        fields.update(
            (
                "subject",
                "action",
                "environment",
                "camera",
                "lighting",
                "composition",
                "emotion",
                "background",
                "continuity",
            )
        )
    if "motion" in layers:
        fields.update(("action", "environment", "motion", "ending_frame", "motion_emotion"))
    cast = [
        character
        for key in ("characters", "in_frame")
        for character in package.get(key) or []
        if isinstance(character, dict)
    ]
    issues: list[str] = []
    for field in sorted(fields):
        text = " ".join(str(package.get(field) or "").split())
        if not text:
            continue
        for clause in re.split(r"[;.!?](?:\s+|$)", text):
            clause = clause.strip(" ,;:.")
            if lint.dangling(clause):
                issues.append(
                    f"{field}: fragment incomplet «{clause}»; editorul trebuie să rescrie "
                    "fraza integral înainte de aprobarea promptului"
                )
        # A formerly clipped locked garment ("and sky-blue") matches the beginning of
        # its canonical clause ("and sky-blue tie"), not a complete garment. Keep the
        # source intact; only the editor and Director may choose the corrected wording.
        tail = re.findall(r"\w+(?:[-']\w+)*", text.casefold())
        for character in cast:
            for garment in _clauses(character.get("outfit"), ",;"):
                canonical = re.findall(r"\w+(?:[-']\w+)*", garment.casefold())
                for size in range(len(canonical) - 1, 1, -1):
                    if tail[-size:] == canonical[:size]:
                        issue = (
                            f"{field}: ținuta lui {_short_name(character.get('name'))} este "
                            f"incompletă; fragmentul canonic trebuie să fie «{garment}»"
                        )
                        if issue not in issues:
                            issues.append(issue)
                        break
    if "still" in layers and package.get("still_prompt"):
        sent = " ".join(re.findall(r"\w+(?:-\w+)*", str(package["still_prompt"]).casefold()))
        for person in serial_partial_characters(package):
            for garment in _clauses(person.get("outfit"), ",;"):
                expected = " ".join(re.findall(r"\w+(?:-\w+)*", garment.casefold()))
                if expected and expected not in sent:
                    issues.append(
                        f"still_prompt: ținuta vizibilă a lui {_short_name(person.get('name'))} "
                        f"lipsește; păstrați partea corpului cerută și descrieți «{garment}»"
                    )
    return issues


def composition_issues(
    package: Mapping[str, Any],
    still: str,
    motion: str,
    *,
    layers: tuple[str, ...] = ("still", "motion"),
) -> list[str]:
    """Required meaning lost during composition must block, never masquerade as a repair."""
    issues = incomplete_plan_fields({**package, "still_prompt": still}, layers=layers)
    ending = str(package.get("ending_frame") or "").strip()
    if ending and "motion" in layers:
        expected = _ending_sentence(ending)
        if not expected or expected.casefold() not in motion.casefold():
            issues.append(
                "ending_frame nu ajunge integral în promptul video; scrieți un final vizibil "
                "concis, fără instrucțiuni de cameră"
            )
    if package.get("in_frame"):
        for character in package.get("in_frame") or []:
            if not isinstance(character, dict):
                continue
            outfit = _clauses(character.get("outfit"), ",;")
            if "still" in layers and outfit and outfit[0].casefold() not in still.casefold():
                issues.append(
                    f"ținuta canonică a lui {_short_name(character.get('name'))} "
                    "a fost eliminată; scurtați acțiunea"
                )
        first = _still_moment(str(package.get("action") or ""))
        for clause in first.split(";"):
            clause = clause.strip(" .")
            if "still" in layers and clause and clause.casefold() not in still.casefold():
                issues.append(
                    f"poza pierde o condiție a primului cadru: {clause}; "
                    "scurtați planul păstrând fiecare personaj"
                )
            normalized_motion = " ".join(lint.without_tempo(motion).split()).casefold()
            if "motion" in layers and clause and clause.casefold() not in normalized_motion:
                issues.append(
                    f"mișcarea pierde prezența sau acțiunea inițială: {clause}; "
                    "păstrați fiecare personaj din primul cadru"
                )
    elif "motion" in layers:
        intent = package.get("motion_intent")
        if isinstance(intent, dict):
            if (
                intent.get("faces_banned")
                and intent.get("people")
                and intent.get("camera_move") == "slow orbit"
            ):
                issues.append(
                    "slow orbit poate întoarce camera spre o față interzisă; "
                    "alegeți o mișcare care păstrează vederea din spate"
                )
            world = str(intent.get("world") or "")
            for clause in [
                *_intent_clauses(intent, "subject_clauses"),
                *_intent_clauses(intent, "action_clauses"),
                *([world] if world and world != DEFAULT_WORLD_MOTION else []),
            ]:
                if clause.casefold() not in motion.casefold():
                    issues.append(
                        f"mișcarea pierde o condiție: {clause}; "
                        "scurtați planul fără a pierde această acțiune"
                    )
    return issues


def _scene_constraints(package: dict[str, Any]) -> list[str]:
    """The plan's own exclusions as plain nouns for a model's negative channel (veo's
    negativePrompt); the generic text/face rules already have their channels.

    Camera instructions are represented by the one selected move, never repeated as a
    competing move in a constraint. No physical detail is inferred from an exclusion, and
    none is ever said in a positive prompt as "no ...".
    """
    generic = {item.casefold() for item in DEFAULT_NEGATIVES}
    result: list[str] = []
    for item in package.get("avoid") or []:
        text = " ".join(str(item).split()).strip(" .")
        if not text or text.casefold() in generic or _CAMERA_WORDS.search(text):
            continue
        if lint.ENUM_CODE.search(text) or _HEX_COLOUR.search(text):
            continue
        text = re.sub(r"^(?:avoid|no|without)\s+", "", text, flags=re.IGNORECASE)
        if text and text.casefold() not in {value.casefold() for value in result}:
            result.append(text)
    return result


def compile_prompts(
    package: dict[str, Any],
    bible: dict[str, Any] | None,
    contract: dict[str, Any] | None = None,
    *,
    previous_moves: list[str] | tuple[str, ...] = (),
    look: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """The still prompt, the motion prompt and the negative prompt for one scene.

    ``contract`` names the video model (``model_id``), optionally the still model
    (``still_model_id``, seedream5_pro by default), and the prompt caps as the vendor's
    contract states them (``prompt_max``, an int or a per-task dict; 1000 UTF-16 units by
    default). A scene composed locally (DATA_CARD, TITLE_CARD, BLACK) gets no prompt at all:
    it never reaches a paid model. Deterministic: the same package gives the same prompts.
    """
    kind = str(package.get("scene_kind") or LIVE_KIND).upper()
    bible = bible if isinstance(bible, dict) else {}
    motion_model = _contract_model(contract, "model_id", DEFAULT_MOTION_MODEL)
    family = _motion_family(motion_model)
    if kind != LIVE_KIND:
        return {
            "scene_kind": kind,
            "still_prompt": "",
            "motion_prompt": "",
            "negative_prompt": None,
            "look_block": "",
            "camera_move": "",
            "shot_size": "",
            "motion_family": family or "generic",
            "motion_intent": None,
        }
    faces_banned = bool(lint.bible_face_rule(bible))
    still_family = _motion_family(_contract_model(contract, "still_model_id", DEFAULT_STILL_MODEL))
    factual_look = look or load_factual_look()
    # A scene's own place and light are authoritative: the look's place, season, weather and
    # daylight are left unsaid where the scene names its own (2026-10-11, aa170155: "A real
    # location as it is today, Early autumn, None indoors. Soft diffuse daylight" over a
    # 1930s lamp-lit desk at night drew the daylight and a beige lamp). The rendering, the
    # palette, the lens and the grain stay: they are the one look of the film.
    omit: set[str] = set()
    if _clauses_of(package.get("environment")):
        omit |= PLACE_SLOTS
    if _clauses_of(package.get("lighting")):
        omit |= LIGHT_SLOTS
    block = look_block(bible, factual_look, omit=omit)
    size, frame = shot_frame(package.get("camera"), package.get("shot_type"))

    def said(field: str) -> str:
        text = _sentence(", ".join(_clauses_of(package.get(field))))
        return hide_faces(text) if faces_banned else text

    subject = said("subject")
    action = said("action")
    if action and subject and action.casefold() == subject.casefold():
        action = ""
    environment = said("environment")
    if environment and environment.casefold() in (subject.casefold(), action.casefold()):
        environment = ""
    light = ", ".join(_clauses_of(package.get("lighting")))
    if light and not re.search(r"\blight", light, re.IGNORECASE):
        # "The glow of the spheres" (babcf272) said as "Light The glow of ..." was no sentence.
        if re.match(r"(?:the|a|an|its|their|his|her|this|that|one)\b", light, re.IGNORECASE):
            light = f"lit by {light[:1].lower()}{light[1:]}"
        else:
            light = f"light {light}"
    cast = _cast_sentence(package.get("characters"), faces_banned)
    people = _shows_people(" ".join((subject, action, environment, cast)))
    # An object that carries its own markings (a thermometer's scale, `markings`): the still
    # keeps them and says so instead of «No text» (the Owner, 2026-10-13).
    marked = planned_markings(
        package.get("subject"),
        package.get("action"),
        package.get("environment"),
        package.get("writer_visual"),
    )
    items = [
        (0, 0, block),
        (0, 1, frame),
        (0, 2, subject),
        (0, 3, cast),
        (3, 4, action),
        (1, 5, environment),
        # How people are kept faceless where the scene shows them; a scene of objects is said
        # to be empty of people instead. The first, said in a scene of objects, asked the model
        # for figures (2026-10-11, cyclotron scene 4: two objects on a desk came back with
        # people, and the clip turned their faces to the camera; the Director's brief named it).
        (
            0,
            6,
            (
                (PEOPLE_SENTENCE if size in ("wide", "aerial") else CLOSE_PEOPLE_SENTENCE)
                if people
                else NO_PEOPLE_SENTENCE
            )
            if faces_banned
            else "",
        ),
        (5, 7, COMPOSITION_SENTENCE),
        (2, 8, _sentence(light)),
        # The plan's own exclusions are never said here as "no ...": an image model reads the
        # words literally (config/factual_look.json's note; the lint refuses them on veo).
        # They stay in the package's `avoid` and reach a model's negative channel where it
        # has one (`render_motion`).
        (0, 9, still_exclusions(marked) if still_family != "gen4" else markings_kept(marked)),
    ]
    still = _fit_sentences(items, lint.prompt_cap(contract, "still"), STILL_MAX_WORDS)
    # People kept faceless are shown from behind: an orbit around them turns their faces to
    # the camera, so it is never the compiler's choice for such a scene (a plan may ask).
    move = choose_camera_move(
        package, size, previous_moves, avoid=("slow orbit",) if faces_banned and people else ()
    )
    intent = _motion_intent(package, move, faces_banned, people)
    intent["constraints"] = _scene_constraints(
        {
            **package,
            "avoid": [*(bible.get("avoid") or []), *(package.get("avoid") or [])],
        }
    )
    motion, negative = render_motion(intent, family, lint.prompt_cap(contract, "motion"))
    return {
        "scene_kind": kind,
        "still_prompt": still,
        "motion_prompt": motion,
        "negative_prompt": negative,
        "look_block": block,
        "camera_move": move,
        "shot_size": size,
        "motion_family": family or "generic",
        "motion_intent": intent,
        "composition_issues": composition_issues(
            {**package, "motion_intent": intent}, still, motion
        ),
    }


def _cast_sentence(characters: Any, faces_banned: bool) -> str:
    """The film's characters as the picture shows them: their look in words, never their
    name (a name means nothing to an image model and can be drawn as writing). When faces
    are forbidden, only what they wear, seen from behind."""
    described: list[str] = []
    for character in characters if isinstance(characters, list) else []:
        if not isinstance(character, dict):
            continue
        outfit = ", ".join(_clauses_of(character.get("outfit")))
        if faces_banned:
            if outfit:
                described.append(f"a figure seen from behind wearing {outfit}")
            continue
        look = ", ".join(_clauses_of(character.get("face_hair")))
        parts = [part for part in (look, f"wearing {outfit}" if outfit else "") if part]
        if parts:
            described.append(", ".join(parts))
    return _sentence("; ".join(described))


def compile_film_prompts(
    packages: list[dict[str, Any]],
    bible: dict[str, Any] | None,
    contract: dict[str, Any] | None = None,
    *,
    contracts: dict[int, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """compile_prompts for every scene of a film in order, so the camera varies from one
    filmed scene to the next. ``contracts`` may give a scene (by its ``scene_index``) its
    own model's contract: the model is chosen per scene, by cost (the Owner, 2026-09-27)."""
    moves: list[str] = []
    look = load_factual_look()
    compiled: list[dict[str, Any]] = []
    for package in packages:
        index = package.get("scene_index")
        terms = (contracts or {}).get(int(index)) if isinstance(index, int) else None
        item = compile_prompts(package, bible, terms or contract, previous_moves=moves, look=look)
        if item["camera_move"]:
            moves.append(item["camera_move"])
        compiled.append(item)
    return compiled


def motion_prompt_for(
    package: dict[str, Any], model_id: Any, contract: dict[str, Any] | None = None
) -> tuple[str, str | None]:
    """(promptText, negativePrompt or None) for the model that films this scene.

    A package the compiler wrote carries its motion intent, so the prompt is said again in
    the dialect of whichever model the scene is bought on. A package from before the
    compiler has none: its stored motion prompt is used as it is (empty when it has none).
    """
    intent = package.get("motion_intent") if isinstance(package, dict) else None
    if isinstance(intent, dict) and intent.get("camera_move") in lint.CAMERA_MOVES:
        return render_motion(intent, _motion_family(model_id), lint.prompt_cap(contract, "motion"))
    stored = " ".join(str((package or {}).get("motion_prompt") or "").split())
    negative = (package or {}).get("negative_prompt")
    return stored, negative if isinstance(negative, str) and negative else None


def _run(
    engine: Engine,
    registry: Any,
    agent_id: str,
    task: str,
    prompt: str,
    template: str,
    correlation: str,
    summary: str,
    max_tokens: int,
    *,
    native_thinking: bool = False,
) -> dict[str, Any] | None:
    """One agent call whose failure is a degradation, not an exception."""
    from app.agents.services import run_agent_task  # noqa: PLC0415
    from app.agents.structured import (  # noqa: PLC0415
        JSON_ONLY,
        NATIVE_THINKING,
        THINKING_SUFFIX,
    )

    try:
        result = run_agent_task(
            engine,
            registry,
            agent_id,
            task,
            prompt,
            template + THINKING_SUFFIX if native_thinking else template,
            correlation,
            summary=summary,
            max_tokens=max_tokens,
            temperature=0.3,
            emit_message=False,
            extra=NATIVE_THINKING if native_thinking else JSON_ONLY,
        )
    except (ValueError, RuntimeError) as exc:
        logger.info("prompt_agent_unavailable", extra={"reason": str(exc)[:160]})
        return None
    if result["status"] != "SUCCEEDED" or not (result.get("output_text") or "").strip():
        logger.info("prompt_agent_no_answer", extra={"status": result["status"]})
        return None
    return result


# ------------------------------------------------------------------ learning, and the package


#: The words two lessons are compared by: letters and digits, accents taken off, lower case.
_LESSON_WORD = re.compile(r"[a-z0-9]+")
#: The «not» inside «don't», «doesn’t», «can't», made a word of its own before the accents and
#: the apostrophe are taken off (they would leave «don» and «t»).
_NOT_CONTRACTION = re.compile(r"n['’]t\b", re.IGNORECASE)
#: Words that say nothing about a defect: two lessons do not repeat each other by sharing them.
#: «unverified» is what `prompt_lessons` says after an unproven lesson, so a lesson read back
#: from it compares as written. The last two lines are the scaffold every picture lesson is
#: written in (review of a9f84ea,
#: 2026-10-12): any two lessons share «camera», «prompt», «clip» or «scene» whatever they
#: mean, and that shared scaffold let «Keep the camera static.» pass for the lesson that
#: corrected it. «not» and «never» are no filler (`_NEGATIONS`).
_LESSON_FILLER = frozenset(
    {
        "the", "and", "for", "with", "that", "this", "are", "was", "were", "but", "its",
        "his", "her", "their", "from", "into", "onto", "per", "has", "have", "had", "one",
        "when", "then", "than", "who", "what", "which", "they", "them", "there", "every",
        "any", "all", "each", "only", "also", "must", "should", "will", "can",
        "does", "did", "out", "over", "under", "same", "too", "very", "more", "less", "own",
        "unverified",
        "model", "prompt", "still", "clip", "motion", "picture", "image", "scene", "shot",
        "frame", "describe", "camera", "movement",
    }
)  # fmt: skip
#: The words that turn a rule around, each read as «not» whatever its length. Review of
#: 68fa0b4 (2026-10-12): «not» and «never» were filler and «no» and «do» too short to count, so
#: «Do not keep the camera static.» passed for «Keep the camera static.» said again — the wrong
#: rule was refreshed under the correction's run, and the correction's passing picture then
#: confirmed it.
_NEGATIONS = frozenset(
    {
        "not", "never", "no", "nor", "dont", "doesnt", "didnt", "cant", "cannot", "wont",
        "isnt", "arent", "nu", "niciodata", "nicio", "niciun", "nici",
    }
)  # fmt: skip
#: Romanian words read as the English word of the same direction.
_POLARITY_ALIASES = {"fara": "without", "evita": "avoid", "evitati": "avoid"}
#: What a lesson's direction is read from (`_polarity`): two lessons that differ in these say
#: opposite things, however many other words they share, and the newer is kept as a correction.
_POLARITY_WORDS = frozenset({"not", "avoid", "without", "instead", "stop"})
#: An id in a lesson: a whole UUID, or eight or more hexadecimal characters that may be the
#: head of one («f06808c9»), as the studio's own notes shorten a storyboard's id. A head is
#: refused only when a storyboard's id begins with it, so a date («20261012») is not an id.
_LESSON_UUID = re.compile(
    r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.IGNORECASE
)
_LESSON_HEX = re.compile(r"\b[0-9a-f]{8,32}\b", re.IGNORECASE)
#: A scene or a shot named by its number, in English or Romanian, read on the lesson without
#: its accents: «Scene 5 repeats the lab bench», «scenei 4», «shot 3», «scenes 1, 4» are notes
#: on one film (review of a9f84ea, 2026-10-12), and so are «scene three», «the third shot»,
#: «scena a 4-a», «cadrul al 3-lea» (review of 68fa0b4). A length is not a number of a scene:
#: «a shot 5 seconds long», «every shot 2-3 s» stay rules; «one» is no number here («give
#: every shot one clear action» is a rule), nor are «first» and «last», which every film has.
_SCENE_NOUN = (
    r"(?:scenes?|scena|scenei|scenele|scenelor|shots?|beats?|cadrul|cadrului|cadrele|cadru)"
)
_NUMBER_WORD = (
    r"(?:two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|fifteen"
    r"|sixteen|seventeen|eighteen|nineteen|twenty|doi|doua|trei|patru|cinci|sase|sapte|opt"
    r"|noua|zece)"
)
_NOT_A_LENGTH = (
    rf"(?!(?:\s*(?:-|to|or|sau|la)\s*(?:\d+|{_NUMBER_WORD}))?\s*"
    r"(?:s|sec|secs|seconds?|secunde|secunda|%|px|mm|fps|frames?|cadre|x)\b)"
)
_ORDINAL_EN = (
    r"(?:the\s+second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth|eleventh|twelfth"
    r"|\d{1,3}(?:st|nd|rd|th))"
)
_ORDINAL_RO = (
    r"(?:a\s+(?:\d{1,3}-a|doua|treia|patra|cincea|sasea|saptea|opta|noua|zecea)"
    r"|al\s+(?:\d{1,3}-lea|doilea|treilea|patrulea|cincilea|saselea|saptelea|optulea|noualea"
    r"|zecelea))"
)
_LESSON_SCENE_NUMBER = re.compile(
    rf"\b{_SCENE_NOUN}\s*(?:no\.?|nr\.?|number|numarul|#)?\s*(?:\d{{1,3}}|{_NUMBER_WORD})\b"
    rf"{_NOT_A_LENGTH}"
    rf"|\b{_ORDINAL_EN}\s+{_SCENE_NOUN}\b"
    rf"|\b{_SCENE_NOUN}\s+{_ORDINAL_RO}\b"
    rf"|\b{_ORDINAL_RO}\s+{_SCENE_NOUN}\b"
)
#: The head of a stored lesson after the marker: its scope, «[?]» while no picture has proven
#: it, «[new]» while the Director has not read it beside the live lessons
#: (`reconcile_prompt_lessons`), «[from:…]» every source that taught it (heads of their ids,
#: «!» before one whose picture showed the defect again), «[over:…]» the lessons it replaced
#: (heads of their rows, given back if it is refuted). «prompt lesson: [serial][?] …»; a row
#: written before scopes has none of it and reads as "all", confirmed.
_LESSON_PREFIX = re.compile(
    r"^\[(serial|factual|all)\]((?:\[(?:\?|new|from:[^\[\]]*|over:[^\[\]]*)\])*)\s*",
    re.IGNORECASE,
)
_LESSON_TAG = re.compile(r"\[([^\[\]]*)\]")
#: How many sources and replaced lessons a row names, the newest kept: the memory keeps 600
#: characters of a row (`memory.MAX_CONTENT`) and the lesson itself up to 400.
_SOURCES_KEPT = 8
_OVER_KEPT = 6
#: A film's own title is named in a lesson when this share of its words of meaning is in it
#: (review of 68fa0b4, 2026-10-12: one phrase shared with any title in the studio, «in real
#: time», «space telescope», refused a general rule).
TITLE_SHARE = 0.6


def _plain(text: str) -> str:
    """The text without accents, in lower case: how lessons are compared and read."""
    return unicodedata.normalize("NFKD", str(text or "")).encode("ascii", "ignore").decode().lower()


def _fold(word: str) -> str:
    """A word's singular, as two lessons said in other words should match («stills», «still»)."""
    if len(word) > 4 and word.endswith("ies"):
        return word[:-3] + "y"
    if len(word) > 3 and word.endswith("s") and not word.endswith(("ss", "us", "is")):
        return word[:-1]
    return word


def lesson_words(text: str) -> frozenset[str]:
    """The words of a lesson that carry its meaning, normalised (accents, case, punctuation,
    plurals, filler and the scaffold of every picture lesson taken out) so a lesson said again
    in other order still matches. Every negation is the word «not» (`_NEGATIONS`): it turns
    the rule around and is never filler."""
    found: set[str] = set()
    said = _plain(_NOT_CONTRACTION.sub(" not", str(text or "")))
    for word in _LESSON_WORD.findall(said):
        if word in _NEGATIONS:
            found.add("not")
            continue
        if len(word) <= 2 or word in _LESSON_FILLER:
            continue
        folded = _POLARITY_ALIASES.get(word) or _fold(word)
        if folded.startswith("avoid"):
            folded = "avoid"
        if folded not in _LESSON_FILLER:
            found.add(folded)
    return frozenset(found)


def _polarity(text: str) -> frozenset[str]:
    """The words that set a lesson's direction (`_POLARITY_WORDS`) it says."""
    return lesson_words(text) & _POLARITY_WORDS


def lesson_overlap(a: str, b: str) -> float:
    """How much of lesson ``a`` lesson ``b`` already says: the share of ``a``'s content words
    found in ``b`` (1.0 when ``a`` is ``b`` said again or a part of it, 0.0 when they share
    nothing). Measured from the NEW lesson (``a``): a short older rule that shares two words
    with a longer correction does not say the correction (review of a9f84ea, 2026-10-12: the
    shorter one's share let «Keep the camera static.» block the lesson that corrected it).

    A lesson with no meaningful words matches only a lesson that is the same text."""
    ours, theirs = lesson_words(a), lesson_words(b)
    if not ours:
        same = " ".join(_plain(a).split()) == " ".join(_plain(b).split())
        return 1.0 if same else 0.0
    return len(ours & theirs) / len(ours)


def _same_text(a: str, b: str) -> bool:
    """The same words in the same order, whatever the case, accents and punctuation."""
    return _LESSON_WORD.findall(_plain(a)) == _LESSON_WORD.findall(_plain(b))


def _repeat_share(new: str, old: str) -> float:
    """How much of ``new`` ``old`` says, for the store's word comparison (the fallback when no
    Director reads it): `lesson_overlap`, except that a lesson of fewer than `LESSON_MIN_WORDS`
    content words is compared word for word only (review of 68fa0b4, 2026-10-12: «Keep the
    camera still.» is {keep}, and one word swallowed or retired unrelated lessons)."""
    if _same_text(new, old):
        return 1.0
    if len(lesson_words(new)) < LESSON_MIN_WORDS:
        return 0.0
    return lesson_overlap(new, old)


def _says_again(a: str, b: str) -> bool:
    """Whether two lessons say the same thing, read either way (`_repeat_share`)."""
    return max(_repeat_share(a, b), _repeat_share(b, a)) >= LESSON_OVERLAP


def _head(value: Any) -> str:
    """The first eight letters and digits of an id: how a lesson row names its sources and the
    rows it replaced within the memory's 600 characters."""
    return re.sub(r"[^0-9a-z]", "", str(value or "").lower())[:8]


def _merged(*groups: Iterable[str]) -> tuple[str, ...]:
    """The heads of every group in order, each once."""
    return tuple(dict.fromkeys(head for group in groups for head in group if head))


def _quoted(text: str, limit: int = 80) -> str:
    said = " ".join(str(text or "").split())
    return said if len(said) <= limit else said[: limit - 1].rstrip() + "…"


def _scope_of(serial: bool) -> str:
    return SCOPE_SERIAL if serial else SCOPE_FACTUAL


def _checked_scope(scope: str) -> str:
    said = str(scope or "").strip().lower()
    if said not in LESSON_SCOPES:
        raise ValueError(f"A prompt lesson's scope is one of {LESSON_SCOPES}, not {scope!r}")
    return said


def lesson_scope(session: Session, storyboard_id: str | None) -> str:
    """The scope a lesson learned on this film is kept under: "serial" for an episode of the
    office serial, "factual" for any other film, "all" when the film is not found."""
    board = session.get(Storyboard, storyboard_id) if storyboard_id else None
    if board is None:
        return SCOPE_ALL
    return _scope_of(_is_serial(board, session.get(ScriptDraft, board.script_draft_id)))


@dataclass(frozen=True)
class _StoredLesson:
    """One lesson row as the store reads it: its text, scope, whether it is proven yet,
    whether the Director has read it, every source that taught it and what it replaced."""

    id: str
    text: str
    scope: str
    provisional: bool
    source_id: str | None
    created_at: str
    unread: bool = False
    sources: tuple[str, ...] = ()
    failed: frozenset[str] = frozenset()
    over: tuple[str, ...] = ()


def _read_lesson(row: Any) -> _StoredLesson | None:
    body = str(row.content or "")[len(LESSON_MARKER) :].strip()
    found = _LESSON_PREFIX.match(body)
    scope, provisional, unread = SCOPE_ALL, False, False
    sources: list[str] = [_head(row.source_id)] if row.source_id else []
    failed: set[str] = set()
    over: list[str] = []
    if found:
        scope = found.group(1).lower()
        for tag in _LESSON_TAG.findall(found.group(2)):
            said = tag.strip().lower()
            if said == "?":
                provisional = True
            elif said == "new":
                unread = True
            elif said.startswith("from:"):
                for item in said[len("from:") :].split(","):
                    head = _head(item.strip().lstrip("!"))
                    if not head:
                        continue
                    sources.append(head)
                    if item.strip().startswith("!"):
                        failed.add(head)
            elif said.startswith("over:"):
                over.extend(_head(item) for item in said[len("over:") :].split(","))
        body = body[found.end() :].strip()
    if not body:
        return None
    return _StoredLesson(
        id=str(row.id),
        text=body,
        scope=scope,
        provisional=provisional,
        source_id=str(row.source_id) if row.source_id else None,
        created_at=str(row.created_at or ""),
        unread=unread,
        sources=_merged(sources),
        failed=frozenset(failed),
        over=_merged(over),
    )


def _lesson_content(
    text: str,
    scope: str,
    provisional: bool,
    *,
    source_id: str | None = None,
    unread: bool = False,
    sources: Sequence[str] = (),
    failed: Iterable[str] = (),
    over: Sequence[str] = (),
) -> str:
    """The row's content: the marker, the head (`_LESSON_PREFIX`) and the lesson. A row with
    one source (its own ``source_id``) and nothing replaced reads as before
    («prompt lesson: [serial][?] …»)."""
    own = _head(source_id)
    bad = set(failed)
    listed = list(_merged(sources))
    kept_over = list(_merged(over))

    def build() -> str:
        tags = f"[{scope}]" + ("[?]" if provisional else "") + ("[new]" if unread else "")
        if any(head != own for head in listed) or bad & set(listed):
            tags += "[from:" + ",".join(("!" if h in bad else "") + h for h in listed) + "]"
        if kept_over:
            tags += "[over:" + ",".join(kept_over) + "]"
        return f"{LESSON_MARKER} {tags} {text}"

    listed, kept_over = listed[-_SOURCES_KEPT:], kept_over[-_OVER_KEPT:]
    content = build()
    while len(content) > 600 and (len(listed) > 1 or kept_over):
        if len(kept_over) > 1 or (kept_over and len(listed) <= 1):
            kept_over = kept_over[1:]
        else:
            listed = listed[1:]
        content = build()
    return content


def _lesson_rows(session: Session, *, live: bool = True, count: int | None = None) -> Any:
    from app.agents.models import MemoryRecord  # noqa: PLC0415

    query = select(MemoryRecord).where(
        MemoryRecord.memory_class == "STRATEGY",
        MemoryRecord.content.like(f"{LESSON_MARKER}%"),
    )
    if live:
        query = query.where(MemoryRecord.invalidated_at.is_(None))
    query = query.order_by(MemoryRecord.created_at.desc(), MemoryRecord.id.desc())
    if count is not None:
        query = query.limit(count)
    return session.scalars(query)


def _live_lessons(
    session: Session, scopes: set[str] | None = None, *, count: int | None = LESSONS_SCANNED
) -> list[_StoredLesson]:
    """The newest ``count`` live lessons (every one when None), newest first, of ``scopes``
    (all if None)."""
    lessons = (_read_lesson(row) for row in _lesson_rows(session, count=count))
    return [
        lesson
        for lesson in lessons
        if lesson is not None and (scopes is None or lesson.scope in scopes)
    ]


def _compare_scopes(scope: str) -> set[str]:
    """The live lessons a lesson of ``scope`` is read beside: its own kind's and the studio's."""
    return {scope, SCOPE_ALL}


def _refuted_lessons(session: Session, scopes: set[str]) -> list[_StoredLesson]:
    """The newest `LESSONS_COMPARED` lessons of ``scopes`` a picture refuted (withdrawn with a
    reason that begins with `REFUTED_RO`), newest first."""
    from app.agents.models import MemoryRecord  # noqa: PLC0415

    rows = session.scalars(
        select(MemoryRecord)
        .where(
            MemoryRecord.memory_class == "STRATEGY",
            MemoryRecord.content.like(f"{LESSON_MARKER}%"),
            MemoryRecord.invalidated_at.is_not(None),
            MemoryRecord.invalidation_reason.like("retras%"),
        )
        .order_by(MemoryRecord.invalidated_at.desc(), MemoryRecord.id.desc())
        .limit(LESSONS_COMPARED)
    )
    found: list[_StoredLesson] = []
    for row in rows:
        if not str(row.invalidation_reason or "").startswith(REFUTED_RO):
            continue
        lesson = _read_lesson(row)
        if lesson is not None and lesson.scope in scopes:
            found.append(lesson)
    return found


def _lesson_stamp(session: Session) -> str:
    """A moment later than every lesson row's own, written with its microseconds: the store
    orders lessons by it, and a lesson that replaced another carries the moment the other was
    retired (`withdraw_prompt_lessons` gives the older back by it, for the rows written before
    «[over:…]»). Two lessons recorded in one tick of the clock would otherwise be newest in no
    defined order."""
    from datetime import UTC, datetime, timedelta  # noqa: PLC0415

    from app.agents.models import MemoryRecord  # noqa: PLC0415

    now = datetime.now(UTC)
    newest = session.scalar(
        select(MemoryRecord.created_at)
        .where(
            MemoryRecord.memory_class == "STRATEGY",
            MemoryRecord.content.like(f"{LESSON_MARKER}%"),
        )
        .order_by(MemoryRecord.created_at.desc())
        .limit(1)
    )
    try:
        last = datetime.fromisoformat(str(newest)) if newest else None
    except ValueError:
        last = None
    if last is not None and last.tzinfo is not None and last >= now:
        now = last + timedelta(microseconds=1)
    return now.isoformat(timespec="microseconds")


def _retire(session: Session, lesson: _StoredLesson, reason: str, stamp: str) -> None:
    from app.agents.memory import invalidate  # noqa: PLC0415

    row = invalidate(session, lesson.id, reason)
    row.invalidated_at = stamp


def _put(session: Session, lesson: _StoredLesson, stamp: str) -> _StoredLesson | None:
    """Store ``lesson`` as a new row written at ``stamp`` (its id is the new row's)."""
    stored = remember(
        session,
        memory_class="STRATEGY",
        content=_lesson_content(
            lesson.text,
            lesson.scope,
            lesson.provisional,
            source_id=lesson.source_id,
            unread=lesson.unread,
            sources=lesson.sources,
            failed=lesson.failed,
            over=lesson.over,
        ),
        source_type="run" if lesson.source_id else "system",
        source_id=lesson.source_id,
        agent_id=None,
    )
    if stored is None:
        return None
    stored.created_at = stamp
    session.flush()
    return _read_lesson(stored)


def _restore(
    session: Session, lesson: _StoredLesson, reason: str, stamp: str, **changes: Any
) -> _StoredLesson | None:
    """The row retired (``reason``) and the lesson stored again with ``changes``: the memory is
    never edited, so a lesson that changes state is a new row (`memory` module)."""
    from dataclasses import replace  # noqa: PLC0415

    _retire(session, lesson, reason, stamp)
    return _put(session, replace(lesson, **changes), stamp)


def _new_lesson(
    text: str, scope: str, provisional: bool, source_id: str | None, unread: bool
) -> _StoredLesson:
    return _StoredLesson(
        id="",
        text=text,
        scope=scope,
        provisional=provisional,
        source_id=source_id,
        created_at="",
        unread=unread,
        sources=_merged([_head(source_id)]),
    )


def prompt_lessons(
    session: Session, limit: int = LESSONS_GIVEN, *, scope: str | None = None
) -> list[str]:
    """What the studio has learned about how its picture models read instructions, for the
    writers of ``scope`` ("serial" or "factual", each with the "all" lessons; None: every
    scope): the confirmed lessons first, then the unverified ones (said with
    `UNVERIFIED_SUFFIX`), each newest first, each said once, ``limit`` in all; after them the
    newest refuted diagnoses (`REFUTED_PREFIX`, `LESSONS_REFUTED_GIVEN`), which
    `fit_with_lessons` sets apart and `lessons_rule` explains.

    Written after a picture failed quality control and the Director understood why: if a
    wording keeps producing the wrong camera move, a stacked still or lettering on a ledger,
    that is a fact about the model, and every next prompt must know it (2026-10-12, the Owner:
    «trebuie să înțeleagă de ce apar defectele și la viitoarele prompturi să se asigure că nu
    mai sunt»). Of two lessons of one group that say the same thing (`_says_again`) only the
    newer is given — a narrower lesson that corrects a studio-wide one is given in its place to
    its own kind of film. Review of 68fa0b4 (2026-10-12): an unverified lesson never hides a
    confirmed one (each group is read on its own, the writers are told the newer wins), and a
    third of the places (`LESSONS_UNVERIFIED_SHARE`) is kept for the newest unverified ones,
    which twelve confirmed lessons used to crowd out.
    """
    if limit <= 0:
        return []
    scopes = None if scope is None else {_checked_scope(scope), SCOPE_ALL}
    live = _live_lessons(session, scopes)

    def once(group: list[_StoredLesson]) -> list[_StoredLesson]:
        kept: list[_StoredLesson] = []
        for lesson in group:  # newest first: the newer of two that say it again is given
            if not any(_says_again(newer.text, lesson.text) for newer in kept):
                kept.append(lesson)
        return kept

    confirmed = once([lesson for lesson in live if not lesson.provisional])
    unverified = once([lesson for lesson in live if lesson.provisional])
    reserve = min(len(unverified), -(-limit // LESSONS_UNVERIFIED_SHARE))
    confirmed = confirmed[: max(0, limit - reserve)]
    unverified = unverified[: limit - len(confirmed)]
    given = [lesson.text for lesson in confirmed] + [
        lesson.text + UNVERIFIED_SUFFIX for lesson in unverified
    ]
    live_texts = [lesson.text for lesson in live]
    refuted: list[str] = []
    for lesson in _refuted_lessons(session, scopes or set(LESSON_SCOPES)):
        if len(refuted) >= LESSONS_REFUTED_GIVEN:
            break
        if any(_same_text(lesson.text, text) for text in live_texts) or any(
            _says_again(lesson.text, said) for said in refuted
        ):
            continue
        refuted.append(lesson.text)
    return given + [REFUTED_PREFIX + text for text in refuted]


def _title_words(title: str) -> list[str]:
    said = " ".join(str(title or "").split())
    if said.lower().startswith("storyboard:"):
        said = said.split(":", 1)[1]
    return _LESSON_WORD.findall(_plain(said))


def _title_named(text: str, titles: Iterable[str], *, whole_only: bool = False) -> str | None:
    """The title of a film the lesson names: the whole title, or (``whole_only`` False: the
    lesson's own film) at least `TITLE_SHARE` of the title's words of meaning, two at least. A
    title of fewer than two words of meaning is not looked for («Higgs» alone is a word a rule
    may use), and against every film in the studio (``whole_only``) one of fewer than three.
    Review of 68fa0b4 (2026-10-12): three words in a row of any title in the studio refused
    general rules that shared a phrase with one («… in real time …», «space telescope»)."""
    said_words = _LESSON_WORD.findall(_plain(text))
    said = f" {' '.join(said_words)} "
    folded = {_fold(word) for word in said_words}
    for title in titles:
        words = _title_words(title)
        meaningful = list(dict.fromkeys(w for w in words if len(w) > 2 and w not in _LESSON_FILLER))
        if len(meaningful) < (3 if whole_only else 2):
            continue
        whole = f" {' '.join(words)} " in said
        found = [word for word in meaningful if _fold(word) in folded]
        share = len(found) / len(meaningful)
        if whole or (not whole_only and len(found) >= 2 and share >= TITLE_SHARE):
            return " ".join(str(title).split()).removeprefix("Storyboard:").strip()
    return None


def lesson_is_general(
    text: str, titles: Iterable[str] = (), *, whole_only: bool = False
) -> str | None:
    """Why ``text`` is not a rule for every next prompt, in words; None when it is one.

    Not a rule: an empty lesson; one longer than `LESSON_MAX_CHARS` (a report, refused whole
    and never cut: a cut rule is obeyed as written); one that names a record by its whole id;
    one that names a scene or a shot by its number, in digits, in words or as an ordinal
    («Scene 5 repeats the lab bench», «the third shot», «scena a 4-a»: a note on one film, and
    «scene 5» in a prompt is read literally); one that names a film of ``titles`` — the film it
    was learned on, by its whole title or most of it, or (``whole_only``) any film by its
    whole title (2026-10-12, review of a9f84ea: the Director's picture note, stored bare, made
    one film's scene a rule for every film)."""
    said = " ".join(str(text or "").split())
    if not said:
        return "lecția e goală"
    if len(said) > LESSON_MAX_CHARS:
        return f"lecția are peste {LESSON_MAX_CHARS} de caractere: e un raport, nu o regulă"
    if _LESSON_UUID.search(said):
        return "lecția numește o înregistrare după id; nu e o regulă pentru orice prompt"
    if _LESSON_SCENE_NUMBER.search(_plain(said)):
        return "lecția numește o scenă sau un cadru după număr; nu e o regulă pentru orice prompt"
    title = _title_named(said, titles, whole_only=whole_only)
    if title:
        return f"lecția numește filmul «{title}»; nu e o regulă pentru orice prompt"
    return None


def _names_an_id(session: Session, text: str) -> bool:
    """Whether a lesson names a storyboard (or any record) by its id: a whole UUID, or the
    head of a storyboard's id as the studio's notes shorten it («f06808c9»)."""
    if _LESSON_UUID.search(text):
        return True
    heads = {match.group(0).lower() for match in _LESSON_HEX.finditer(text)}
    for head in sorted(heads):
        found = session.scalar(
            select(Storyboard.id).where(Storyboard.id.startswith(head, autoescape=True)).limit(1)
        )
        if found is not None:
            return True
    return False


def _film_titles(session: Session, storyboard_id: str) -> list[str]:
    """The titles the film is known by: its storyboard's and its script's."""
    board = session.get(Storyboard, storyboard_id)
    if board is None:
        return []
    script = session.get(ScriptDraft, board.script_draft_id) if board.script_draft_id else None
    titles = [str(board.title or ""), str(script.title or "") if script is not None else ""]
    return [title for title in dict.fromkeys(titles) if title.strip()]


def lesson_refusal(
    session: Session, lesson: str, *, storyboard_id: str | None = None
) -> str | None:
    """Why `record_prompt_lesson` would refuse ``lesson`` as no rule, in words; None when it
    is one: `lesson_is_general` against the title of the film it was learned on
    (``storyboard_id``) — or, when the caller does not say which film, against every film's
    whole title — and the head of a storyboard's id («f06808c9»)."""
    said = " ".join(str(lesson or "").split())
    if storyboard_id:
        why = lesson_is_general(said, _film_titles(session, storyboard_id))
    else:
        titles = [str(title) for title in session.scalars(select(Storyboard.title)) if title]
        why = lesson_is_general(said, titles, whole_only=True)
    if why:
        return why
    if _names_an_id(session, said):
        return "lecția numește un film după id; nu e o regulă pentru orice prompt"
    return None


def _refuted_again(session: Session, text: str, scope: str) -> str | None:
    """Why a lesson a picture already refuted is not learned again: the same words, or said
    again in the same direction, by a lesson `withdraw_prompt_lessons` withdrew (finding 5 of
    the review of 68fa0b4, 2026-10-12: a refuted lesson was learned again at once and the same
    wrong fix was paid for again)."""
    direction = _polarity(text)
    for refuted in _refuted_lessons(session, _compare_scopes(scope)):
        if _polarity(refuted.text) != direction:
            continue
        if _repeat_share(text, refuted.text) >= LESSON_CONTAINED:
            return (
                f"lecția a mai fost învățată («{_quoted(refuted.text)}») și o imagine făcută "
                "după ea a arătat același defect: nu e cauza lui, se caută alta"
            )
    return None


def _said(reasons: list[str] | None, why: str) -> None:
    logger.info("prompt_lesson_not_stored", extra={"reason": why[:200]})
    if reasons is not None:
        reasons.append(why)


def record_prompt_lesson(
    session: Session,
    lesson: str,
    *,
    source_id: str | None = None,
    scope: str = SCOPE_ALL,
    provisional: bool = False,
    storyboard_id: str | None = None,
    reasons: list[str] | None = None,
) -> bool:
    """Keep one lesson about prompting for every next film of ``scope``, with where it came
    from (``source_id``: the run that learned it, by which `confirm_prompt_lessons` and
    `withdraw_prompt_lessons` find it). ``provisional``: no picture has proven it yet.
    ``storyboard_id``: the film it was learned on, whose title it may not name. ``reasons``,
    when given, receives why a lesson was not stored, in Romanian.

    Not stored (False):

    - what `lesson_refusal` refuses — empty, over `LESSON_MAX_CHARS`, a scene or shot by its
      number, the film's title, a storyboard's id;
    - a lesson a picture already refuted, said again in the same direction (`_refuted_again`);
    - a lesson the store already holds word for word (of its scope or "all"): ABSORBED — that
      lesson is learned again and comes back to the top with this source added to its sources
      (never its text under this source alone: review of 68fa0b4, 2026-10-12), proven if
      either was.

    Otherwise it is stored and True is returned. When live lessons of its scope exist it is
    stored «[new]»: the Director reads it beside them (`reconcile_prompt_lessons`, free) and
    decides which it REPEATS (merged, sources kept), CORRECTS (retired, given back if this one
    is refuted) or is UNRELATED to; with no Director or model the words decide
    (`_read_by_words`). Until then both are given, and the writers are told the newer wins.
    Inside the caller's transaction: no model is asked here.
    """
    scope = _checked_scope(scope)
    text = " ".join(str(lesson or "").split())
    why = lesson_refusal(session, text, storyboard_id=storyboard_id) or _refuted_again(
        session, text, scope
    )
    if why:
        _said(reasons, why)
        return False
    known = _live_lessons(session, _compare_scopes(scope))[:LESSONS_COMPARED]
    stamp = _lesson_stamp(session)
    same = next((older for older in known if _same_text(text, older.text)), None)
    if same is not None:
        _restore(
            session,
            same,
            REFRESHED_RO,
            stamp,
            provisional=same.provisional and provisional,
            sources=_merged(same.sources, [_head(source_id)]),
        )
        _said(
            reasons,
            f"lecția e deja știută cu aceleași cuvinte («{_quoted(same.text)}»): a revenit "
            "prima, cu sursa ei adăugată",
        )
        return False
    stored = _put(session, _new_lesson(text, scope, provisional, source_id, bool(known)), stamp)
    return stored is not None


# ------------------------------------------------------------------ the Director reads a lesson


class _LessonRelation(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: int
    relation: str = Field(pattern="^(REPEATS|CORRECTS|UNRELATED)$")
    why: str = Field(default="", max_length=300)

    @field_validator("relation", mode="before")
    @classmethod
    def _upper(cls, value: Any) -> Any:
        return str(value or "").strip().upper() if isinstance(value, str) else value

    @field_validator("why", mode="before")
    @classmethod
    def _clip(cls, value: Any) -> Any:
        return " ".join(value.split()) if isinstance(value, str) else value


class LessonReading(BaseModel):
    """The Director's reading of a new lesson beside the live ones, by their ids."""

    model_config = ConfigDict(extra="ignore")
    relations: list[_LessonRelation] = Field(default_factory=list, max_length=60)


_LESSON_READING_INSTRUCTIONS = (
    "You are the Director. The studio keeps lessons about how its picture and clip models "
    "misread prompts, and every writer of a prompt follows them as rules. A new lesson has "
    "just been learned (new_lesson below). Read it beside each of the studio's live lessons "
    "(live_lessons, by id) and decide how it relates to each: REPEATS when it says the same "
    "rule, in any words; CORRECTS when it contradicts the older lesson or replaces it, so "
    "both cannot be followed, or it says the older one named the wrong rule or the wrong "
    "cause; UNRELATED for anything else, a lesson about something different that shares "
    "words included. A corrected lesson is retired, and given back if a picture later refutes "
    "the new one; a repeated one is kept once, with every source that taught it. Return only "
    'JSON: {"relations": [{"id": 1, "relation": "REPEATS" | "CORRECTS" | "UNRELATED", '
    '"why": "a few words, in Romanian"}]} — one item per live lesson; one left out is '
    "UNRELATED.\n"
)


def _can_ask(registry: Any) -> bool:
    if registry is None:
        return False
    ids = getattr(registry, "registered_ids", None)
    try:
        return bool(ids()) if callable(ids) else True
    except Exception:  # noqa: BLE001 - a registry that cannot say has nobody to ask
        return False


def _directors_reading(
    engine: Engine, registry: Any, director_id: str, lesson: _StoredLesson, correlation: str
) -> dict[str, Any] | None:
    """Ask the Director (free) how ``lesson`` relates to each live lesson of its scope.

    Returns {"relations": {row id: REPEATS|CORRECTS|UNRELATED}, "why": {row id: words},
    "run_id"} — or {"unavailable": why, "run_id"} when her answer did not validate twice or
    the call failed; None (nothing asked) when no live lesson is there to compare."""
    from app.agents.structured import structured_run  # noqa: PLC0415 - agents import media

    with Session(engine) as session:
        candidates = [
            older
            for older in _live_lessons(session, _compare_scopes(lesson.scope))
            if older.id != lesson.id
        ][:LESSONS_COMPARED]
    if not candidates:
        return None
    payload = {
        "new_lesson": {
            "lesson": lesson.text,
            "for": lesson.scope,
            "proven": not lesson.provisional,
        },
        "live_lessons": [
            {
                "id": number,
                "lesson": older.text,
                "for": older.scope,
                "proven": not older.provisional,
            }
            for number, older in enumerate(candidates, start=1)
        ],
    }
    try:
        parsed, first, second = structured_run(
            engine,
            registry,
            director_id,
            LESSON_READING_TASK,
            _LESSON_READING_INSTRUCTIONS
            + wrap_in_inert_boundary(_dumps(payload), "prompt-lessons"),
            LESSON_READING_TEMPLATE,
            correlation,
            LessonReading,
            '{"relations": [{"id": 1, "relation": "REPEATS|CORRECTS|UNRELATED", "why": "..."}]}',
            summary=f"Citesc lecția nouă «{_quoted(lesson.text, 60)}» lângă cele știute.",
            max_tokens=2000,
            temperature=0.1,
        )
    except Exception as exc:  # noqa: BLE001 - the words decide when she cannot be asked
        return {"unavailable": f"citirea nu s-a putut face ({type(exc).__name__})", "run_id": None}
    run = second or first
    if parsed is None:
        detail = str(run.get("error_detail") or run.get("status") or "fără răspuns")
        return {"unavailable": _quoted(detail, 160), "run_id": run.get("id")}
    relations: dict[str, str] = {}
    whys: dict[str, str] = {}
    for item in parsed.relations:
        if 1 <= item.id <= len(candidates):
            relations[candidates[item.id - 1].id] = item.relation
            whys[candidates[item.id - 1].id] = item.why
    return {"relations": relations, "why": whys, "run_id": run.get("id")}


def _read_by_words(session: Session, lesson: _StoredLesson) -> dict[str, Any]:
    """The fallback when no Director reads a new lesson: the words decide, as the store did
    until 2026-10-12. The live lesson that says most of it (`_repeat_share`, at least
    `LESSON_OVERLAP`) is CORRECTED by it when they say opposite things (`_polarity`) or it says
    more, and ABSORBS it when it already says it all (`LESSON_CONTAINED`) in at least as many
    words — the new lesson's sources join it. A studio-wide lesson corrected by a narrower one
    stays for the other kind of film."""
    known = [
        older
        for older in _live_lessons(session, _compare_scopes(lesson.scope))
        if older.id != lesson.id
    ][:LESSONS_COMPARED]
    closest: _StoredLesson | None = None
    share = 0.0
    for older in known:  # newest first: on a tie the newest is the one compared
        said = _repeat_share(lesson.text, older.text)
        if said >= LESSON_OVERLAP and said > share:
            closest, share = older, said
    stamp = _lesson_stamp(session)
    if closest is None:
        _restore(session, lesson, READ_RO, stamp, unread=False)
        return {}
    same_way = _polarity(lesson.text) == _polarity(closest.text)
    says_all = len(lesson_words(closest.text)) >= len(lesson_words(lesson.text))
    if same_way and share >= LESSON_CONTAINED and says_all:
        _retire(session, lesson, ABSORBED_RO, stamp)
        _restore(
            session,
            closest,
            REFRESHED_RO,
            stamp,
            provisional=closest.provisional and lesson.provisional,
            sources=_merged(closest.sources, lesson.sources),
            failed=closest.failed | lesson.failed,
            over=_merged(closest.over, lesson.over),
        )
        return {"absorbed_into": closest.text}
    _retire(session, closest, SUPERSEDED_RO, stamp)
    _restore(
        session,
        lesson,
        READ_RO,
        stamp,
        unread=False,
        over=_merged(lesson.over, [_head(closest.id)]),
    )
    if closest.scope == SCOPE_ALL and lesson.scope != SCOPE_ALL:
        _put(session, _narrowed(closest, lesson.scope), _lesson_stamp(session))
    return {"corrects": [closest.text]}


def _narrowed(lesson: _StoredLesson, corrected_on: str) -> _StoredLesson:
    """A studio-wide lesson corrected on one kind of film, kept for the other kind, which
    taught nothing against it (given back whole if the correction is refuted, `_give_back`)."""
    from dataclasses import replace  # noqa: PLC0415

    other = SCOPE_FACTUAL if corrected_on == SCOPE_SERIAL else SCOPE_SERIAL
    return replace(lesson, scope=other, unread=False)


def _read_by_her(
    session: Session, lesson: _StoredLesson, reading: Mapping[str, Any]
) -> dict[str, Any]:
    """Her reading applied: each lesson she says it CORRECTS is retired (`SUPERSEDED_RO`) and
    named in its «[over:…]» — a studio-wide one corrected on one kind of film stays the other
    kind's rule; each it REPEATS is merged into it (the longer words, the wider scope, proven if
    either was, every source of both); the new lesson stored again, read."""
    from dataclasses import replace  # noqa: PLC0415

    from app.agents.models import MemoryRecord  # noqa: PLC0415

    stamp = _lesson_stamp(session)
    merged = replace(lesson, unread=False)
    corrects: list[str] = []
    repeats: list[str] = []
    narrowed: list[_StoredLesson] = []
    for row_id, relation in dict(reading.get("relations") or {}).items():
        row = session.get(MemoryRecord, row_id)
        older = _read_lesson(row) if row is not None and row.invalidated_at is None else None
        if older is None or older.id == lesson.id or relation == "UNRELATED":
            continue
        if relation == "CORRECTS":
            _retire(session, older, SUPERSEDED_RO, stamp)
            merged = replace(merged, over=_merged(merged.over, [_head(older.id)]))
            corrects.append(older.text)
            if older.scope == SCOPE_ALL and lesson.scope != SCOPE_ALL:
                narrowed.append(_narrowed(older, lesson.scope))
            continue
        _retire(session, older, REFRESHED_RO, stamp)
        longer = len(lesson_words(older.text)) > len(lesson_words(merged.text))
        merged = replace(
            merged,
            text=older.text if longer else merged.text,
            scope=SCOPE_ALL if older.scope == SCOPE_ALL else merged.scope,
            provisional=merged.provisional and older.provisional,
            sources=_merged(merged.sources, older.sources),
            failed=merged.failed | older.failed,
            over=_merged(merged.over, older.over),
        )
        repeats.append(older.text)
    _retire(session, lesson, READ_RO, stamp)
    _put(session, merged, stamp)
    for kept in narrowed:
        _put(session, kept, _lesson_stamp(session))
    return {"corrects": corrects, "repeats": repeats}


def _settle_reading(
    session: Session,
    lesson_id: str,
    reading: Mapping[str, Any] | None,
    director_id: str | None,
    correlation: str,
) -> bool:
    """One new lesson read (her reading, or the words when she gave none), and the event that
    records what was decided — her reading always, the words' only when they changed
    something or she could not answer. False when the lesson is no longer live and unread."""
    from app.agents.models import MemoryRecord  # noqa: PLC0415

    row = session.get(MemoryRecord, lesson_id)
    lesson = _read_lesson(row) if row is not None and row.invalidated_at is None else None
    if lesson is None or not lesson.unread:
        return False
    by_her = reading is not None and "unavailable" not in reading
    outcome = (
        _read_by_her(session, lesson, reading or {}) if by_her else _read_by_words(session, lesson)
    )
    if not (by_her or outcome or (reading or {}).get("unavailable")):
        return True
    append_event(
        session,
        LESSON_READ_EVENT,
        "memory_record",
        lesson_id,
        1,
        {
            "lesson": lesson.text,
            "scope": lesson.scope,
            "read_by": "director" if by_her else "words",
            "agent_id": director_id if by_her else None,
            "run_id": (reading or {}).get("run_id"),
            "corrects": list(outcome.get("corrects") or []),
            "repeats": list(outcome.get("repeats") or []),
            "absorbed_into": outcome.get("absorbed_into"),
            "unavailable": (reading or {}).get("unavailable"),
        },
        correlation,
    )
    return True


def reconcile_prompt_lessons(
    engine: Engine, registry: Any, correlation_id: str | None = None
) -> int:
    """The Director reads each new lesson («[new]», `record_prompt_lesson`) beside the live
    lessons of its scope and decides which it REPEATS, CORRECTS or is UNRELATED to (one
    structured call each, free: the Owner, 2026-10-12, «LLM-ul este pe abonament! NU COSTĂ
    BANI»); what she decided is applied and recorded (`LESSON_READ_EVENT`). With no registry,
    no Director, or an answer that does not validate twice, the words decide
    (`_read_by_words`). Returns how many lessons were read. Every writer of words a picture is
    made from calls it before reading the lessons; it never raises.

    Review of 68fa0b4 (2026-10-12): a correction that shares few words with the rule it
    corrects did not displace it, both were given, and the old confirmed one won. Her reading
    retires it; until she reads, both are given and the writers are told the newer wins."""
    correlation = correlation_id or str(uuid4())
    try:
        with Session(engine) as session:
            pending = [lesson for lesson in _live_lessons(session, count=None) if lesson.unread]
            director = agent_for_role(session, "Director") if pending else None
            director_id = str(director.id) if director is not None else None
    except Exception as exc:  # noqa: BLE001 - a writer goes on without the reading
        logger.warning("prompt_lessons_not_read", extra={"error": type(exc).__name__})
        return 0
    if not pending:
        return 0
    asking = director_id is not None and _can_ask(registry)
    pending.reverse()  # oldest first: a lesson is read before the ones learned after it
    read = 0
    for lesson in pending[:LESSONS_READ_AT_ONCE] if asking else pending:
        try:
            reading = (
                _directors_reading(engine, registry, director_id or "", lesson, correlation)
                if asking
                else None
            )
            with Session(engine) as session, session.begin():
                lock_for_write(session)
                if _settle_reading(session, lesson.id, reading, director_id, correlation):
                    read += 1
        except Exception as exc:  # noqa: BLE001 - one lesson unread never stops a writer
            logger.warning(
                "prompt_lesson_not_read", extra={"lesson": lesson.id, "error": type(exc).__name__}
            )
    return read


# ------------------------------------------------------------------ proven, or refuted


def _taught_by(session: Session, source_ids: Iterable[Any]) -> list[_StoredLesson]:
    """The live lessons any of ``source_ids`` taught (one of their sources), oldest first."""
    wanted = {_head(source) for source in source_ids if _head(source)}
    if not wanted:
        return []
    lessons = [
        lesson for lesson in _live_lessons(session, count=None) if wanted & set(lesson.sources)
    ]
    return sorted(lessons, key=lambda lesson: (lesson.created_at, lesson.id))


def confirm_prompt_lessons(session: Session, source_ids: Iterable[Any]) -> int:
    """The unverified lessons one of ``source_ids`` taught become confirmed: a picture made
    after them passed with every finding gone. Each is stored again without its «[?]»
    (`CONFIRMED_RO` on the old row). Returns how many.

    2026-10-12 (review of a9f84ea): a lesson was never verified and never retired — the
    review's guess of a cause was a rule for every next film from the moment it was said.
    Review of 68fa0b4: a lesson learned again keeps every source that taught it, so the first
    review's passing picture still confirms it."""
    confirmed = 0
    for lesson in _taught_by(session, source_ids):
        if not lesson.provisional:
            continue
        _restore(session, lesson, CONFIRMED_RO, _lesson_stamp(session), provisional=False)
        confirmed += 1
    return confirmed


def _give_back(session: Session, lesson: _StoredLesson) -> int:
    """The lessons ``lesson`` replaced (its «[over:…]», and for a row written before them the
    rows retired `SUPERSEDED_RO` at the moment it was written) stored again as they were — the
    same lesson said again excepted, and one already live again. A narrower copy of a
    studio-wide lesson (`_read_by_her`) goes back into it. Returns how many."""
    from app.agents.models import MemoryRecord  # noqa: PLC0415

    marked = [
        MemoryRecord.memory_class == "STRATEGY",
        MemoryRecord.content.like(f"{LESSON_MARKER}%"),
        MemoryRecord.invalidation_reason == SUPERSEDED_RO,
    ]
    rows: dict[str, Any] = {}
    for head in lesson.over:
        for row in session.scalars(
            select(MemoryRecord).where(*marked, MemoryRecord.id.startswith(head))
        ):
            rows[str(row.id)] = row
    for row in session.scalars(
        select(MemoryRecord).where(*marked, MemoryRecord.invalidated_at == lesson.created_at)
    ):
        rows[str(row.id)] = row
    from dataclasses import replace  # noqa: PLC0415

    given = 0
    for row in sorted(rows.values(), key=lambda item: (str(item.created_at), str(item.id))):
        older = _read_lesson(row)
        if older is None or older.id == lesson.id:
            continue
        if _same_text(lesson.text, older.text) or (
            _polarity(lesson.text) == _polarity(older.text)
            and _repeat_share(lesson.text, older.text) >= LESSON_CONTAINED
        ):
            continue  # the same lesson learned again: withdrawn with it
        twins = [k for k in _live_lessons(session, count=None) if _same_text(k.text, older.text)]
        if any(twin.scope in (older.scope, SCOPE_ALL) for twin in twins):
            continue  # already live again
        stamp = _lesson_stamp(session)
        sources = older.sources
        for twin in twins:
            _retire(session, twin, REFRESHED_RO, stamp)
            sources = _merged(sources, twin.sources)
        if _put(session, replace(older, unread=False, sources=sources), stamp) is not None:
            given += 1
    return given


def withdraw_prompt_lessons(session: Session, source_ids: Iterable[Any], reason: str) -> int:
    """The unverified lessons one of ``source_ids`` taught, whose picture still shows the
    finding: what they said was not why the defect appeared. A lesson is withdrawn (``reason``,
    or `WITHDRAWN_RO`, always beginning with `REFUTED_RO`) once every source that taught it has
    failed; while another source has not decided, the failure is written on it
    (`SOURCE_FAILED_RO`) and it stays. A withdrawn lesson gives back what it had replaced
    (`_give_back`), and is not learned again (`record_prompt_lesson`); a confirmed lesson is
    never withdrawn by this. Returns how many were withdrawn.

    Review of 68fa0b4 (2026-10-12): a refresh moved a lesson to its newest source, so another
    review's failure deleted a lesson the first had proven."""
    said = " ".join(str(reason or "").split()) or WITHDRAWN_RO
    if not said.startswith(REFUTED_RO):
        said = f"{REFUTED_RO}: {said}"
    wanted = {_head(source) for source in source_ids if _head(source)}
    withdrawn = 0
    for lesson in _taught_by(session, source_ids):
        if not lesson.provisional:
            continue
        failed = lesson.failed | (wanted & set(lesson.sources))
        stamp = _lesson_stamp(session)
        if set(lesson.sources) - failed:
            _restore(session, lesson, SOURCE_FAILED_RO, stamp, failed=frozenset(failed))
            continue
        _retire(session, lesson, said, stamp)
        withdrawn += 1
        _give_back(session, lesson)
    return withdrawn


def production_package(engine: Engine, storyboard_id: str) -> dict[str, Any]:
    """Everything the generator is given, and everything a person needs to audit it.

    The Owner's list, from the rows the studio already keeps: the idea and why it should
    exist, the trusted sources, the fact check, the message, the hook, the script and its
    timeline, the call to action, the visual bible, the character references, the shot list
    with a full prompt each, the audio intent, the continuity rules, the exclusions, the
    expected duration, the quality requirement and the approval status.
    """
    from app.factual.models import SourceSnapshot, TopicIdea  # noqa: PLC0415
    from app.factual.story_review import latest_review  # noqa: PLC0415

    with Session(engine) as session:
        board = session.get(Storyboard, storyboard_id)
        if board is None:
            raise PromptError(f"Storyboard {storyboard_id} not found")
        script = session.get(ScriptDraft, board.script_draft_id)
        topic = session.get(TopicIdea, script.topic_id) if script else None
        review = latest_review(session, script.id) if script else None
        claims = (
            list(
                session.scalars(
                    select(FactualClaim).where(FactualClaim.topic_id == script.topic_id)
                )
            )
            if script
            else []
        )
        sources = (
            list(
                session.scalars(
                    select(SourceSnapshot).where(SourceSnapshot.topic_id == script.topic_id)
                )
            )
            if script
            else []
        )
        scenes = list(
            session.scalars(
                select(StoryboardScene)
                .where(StoryboardScene.storyboard_id == storyboard_id)
                .order_by(StoryboardScene.scene_index)
            )
        )
        story = dict(script.story_json or {}) if script else {}
        bible = dict(board.visual_bible_json or {})
        offset = 0.0
        timeline = []
        for scene in scenes:
            timeline.append(
                {
                    "scene_index": scene.scene_index,
                    "from_seconds": round(offset, 2),
                    "to_seconds": round(offset + float(scene.duration_seconds), 2),
                    "story_purpose": scene.story_purpose,
                    "narration": scene.voiceover_segment,
                }
            )
            offset += float(scene.duration_seconds)
        return {
            "idea": {
                "title": topic.title if topic else "",
                "topic": topic.topic if topic else "",
                "angle": topic.angle if topic else "",
                "scores": dict(topic.scores_json or {}) if topic else {},
            },
            "why_this_video_should_exist": dict(topic.thesis_json or {}) if topic else {},
            "trusted_sources": [
                {"url": s.url, "publisher": s.publisher, "fetched_at": s.fetched_at}
                for s in sources
            ],
            "fact_check": [
                {"claim": c.claim_text, "status": c.status, "confidence": c.confidence}
                for c in claims
            ],
            "core_message": story.get("core_message", ""),
            "audience_takeaway": story.get("takeaway", ""),
            "hook": story.get("hook", ""),
            "script": {
                "title": script.title if script else "",
                "voiceover": script.voiceover_full_text if script else "",
                "target_seconds": script.target_duration_seconds if script else 0,
                "estimated_seconds": story.get("estimated_seconds"),
            },
            "timeline": timeline,
            "cta": {"text": story.get("cta", ""), "kind": story.get("cta_kind", "")},
            "master_visual_bible": bible,
            "character_references": [
                ref for scene in scenes for ref in (scene.character_ids_json or [])
            ],
            "shot_list": [
                {
                    "scene_index": scene.scene_index,
                    "story_purpose": scene.story_purpose,
                    "seconds": scene.duration_seconds,
                    "prompt": scene.visual_prompt,
                    "package": dict(scene.prompt_json or {}),
                }
                for scene in scenes
            ],
            "audio_intent": [
                {
                    "scene_index": scene.scene_index,
                    "intent": (scene.prompt_json or {}).get("audio_intent", ""),
                }
                for scene in scenes
            ],
            "continuity_rules": bible.get("continuity_rules", []),
            "negative_constraints": bible.get("avoid", list(DEFAULT_NEGATIVES)),
            "expected_duration_seconds": round(offset, 2),
            "quality_requirement": bible.get("quality_target", ""),
            "approval": {
                "script_status": script.status if script else "",
                "storyboard_status": board.status,
                "story_review": review.verdict if review else "NONE",
                "story_review_at": review.created_at if review else None,
                # Who let the story through, as the record says (S10): a serial episode the
                # Owner approved without the Director's reading reads as his approval here,
                # never as her review. A factual script has no source and shows None.
                "story_review_source": (review.notes_json or {}).get("source") if review else None,
                "approved_by": (review.notes_json or {}).get("approved_by") if review else None,
                "director_review": (
                    (review.notes_json or {}).get("director_review") if review else None
                ),
                "story_review_notes": (
                    list((review.notes_json or {}).get("notes") or []) if review else []
                ),
            },
        }
