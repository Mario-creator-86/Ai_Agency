"""Well-formed, deterministic Kael shot replies for simulated end-to-end days.

All text is supplied by the fake model itself. Production still/motion lint and
character-continuity gates stay enabled; no vendor is called by this fixture.
"""

from __future__ import annotations

import json
import re


#: A shot plan with a different frame and subject per scene, as a real Video Editor writes
#: one: the end-to-end stand-in answers every scene alike, which the sheet's lint rightly
#: BLOCKs in PRODUCTION ("every filmed scene has the same framing"). The fake editor
#: must also return complete Kael-owned still/motion vendor texts and camera_move; legacy
#: plan-only shots are correctly rejected by the production prompt gate.
VARIED_SHOTS = (
    (
        "a wide, low angle, 24mm lens",
        "the observatory dome on a cold hillside at night",
        "the dome turns slowly, its shutter opening",
    ),
    (
        "a medium shot, eye-level, 50mm lens",
        "the segmented golden mirror of a telescope",
        "a faint reflection drifts across the segments",
    ),
    (
        "a detail shot, macro, 85mm lens",
        "a cloud of red dust around a young star",
        "the dust thins slowly and light shows through",
    ),
    (
        "an aerial shot, high angle",
        "an empty field under a clear starry sky",
        "the stars wheel slowly overhead",
    ),
)


def _serial_fake_shot(scene: dict, index: int, move: str) -> dict:
    """Fixture Kael answer based on the episode's real cast, not the factual astronomy plan.

    The first moment and canonical clothing enter the still, and the unchanged first
    moment and exact ending enter motion. Production lint and gates remain unchanged.
    """
    from app.media.prompt_agent import (
        _ending_sentence,
        _serial_package,
        _short_name,
        serial_still_moment,
    )
    from app.media.series_look import load_series_look, room_sentence

    look = load_series_look()
    probe = _serial_package({"action": ""}, None, scene, look)
    people = probe["in_frame"]
    focus = _short_name(people[0].get("name")) if people else "the speaker"
    action = "; ".join(
        f"{_short_name(person.get('name'))} stands beside the office desk"
        for person in people
    ) or "the speaker stands beside the office desk"
    probe["action"] = action
    first_moment = serial_still_moment(probe)
    identities = "; ".join(
        f"{_short_name(person.get('name'))}, "
        f"{str(person.get('face_hair') or '').split(';')[0]}, "
        f"wearing {person.get('outfit') or 'office clothes'}"
        for person in people
    )
    # Reduced test payloads can omit location; keep the test serial in its
    # canonical Content room rather than replacing a missing room with the house.
    place = str(scene.get("location") or "Content, floor 2")
    still_prompt = " ".join(part for part in (
        str(look.get("block") or ""),
        room_sentence(look, place),
        f"A single, eye-level, vertical office shot of {focus}, facing the viewer.",
        f"The characters retain their canonical appearances: {identities}." if identities else "",
        f"{first_moment}.",
    ) if part)
    ending_frame = f"with {focus} standing beside the office desk"
    motion_prompt = (
        f"A steady {move} at a measured pace. {action}. "
        f"{_ending_sentence(ending_frame)}"
    )
    return {
        "scene_index": index,
        "story_purpose": "EVIDENCE",
        "subject": f"{focus} in the {place}",
        "action": action,
        "environment": place,
        "camera": "medium eye-level office shot",
        "camera_move": move,
        "lighting": "the warm amber lamps of the series look",
        "composition": "vertical office shot with the characters facing the viewer",
        "motion": action,
        "emotion": "quiet focus",
        "background": "wooden desks, amber lamps and bookshelves",
        "continuity": "the same room and canonical clothes across the episode",
        "ending_frame": ending_frame,
        "audio_intent": "office ambience, clear spoken dialogue",
        "transition": "cut",
        "avoid": ["writing in the picture"],
        "still_prompt": still_prompt,
        "motion_prompt": motion_prompt,
        "negative_prompt": "letters, logos",
    }


def make_shot_plan(prompt: str) -> str:
    indices = sorted({int(n) for n in re.findall(r'"scene_index":\s*(\d+)', prompt)}) or [1]
    payload_match = re.search(
        r'<untrusted_source_evidence hash="approved-film">\s*(.*?)\s*</untrusted_source_evidence>',
        prompt, re.DOTALL,
    )
    payload = json.loads(payload_match.group(1)) if payload_match else {}
    episode = (payload.get("episode") or {}) if isinstance(payload, dict) else {}
    serial_scenes = {
        int(item["scene_index"]): item
        for item in episode.get("scenes", [])
        if isinstance(item, dict) and isinstance(item.get("scene_index"), int)
    }
    planned = []
    for index in indices:
        camera, subject, action = VARIED_SHOTS[(index - 1) % len(VARIED_SHOTS)]
        move = ("dolly in", "tracking left", "crane up", "slow pan right")[(index - 1) % 4]
        if index in serial_scenes:
            planned.append(_serial_fake_shot(serial_scenes[index], index, move))
            continue
        still_prompt = (
            f"Documentary photograph, {camera}. The first instant shows {subject} "
            "at a remote observatory beneath a dark, clear sky. Cold moonlight "
            "illuminates the foreground, with one warm lamp behind the subject. "
            "A single continuous vertical 9:16 frame, carefully composed."
        )
        ending_frame = f"{subject}, centred"
        motion_prompt = (
            f"A steady {move} at a measured pace while {action}. "
            "The world and subject remain consistent in one uninterrupted shot. "
            f"The shot ends on {ending_frame}."
        )
        planned.append(
            {
                "scene_index": index,
                "story_purpose": "EVIDENCE",
                "camera_move": move,
                "still_prompt": still_prompt,
                "motion_prompt": motion_prompt,
                "negative_prompt": "letters, logos",
                "subject": subject,
                "action": action,
                "environment": "a remote observatory far from any city",
                "camera": camera,
                "lighting": "moonlight from the left, one warm lamp behind",
                "composition": "vertical, the subject in the lower third",
                "motion": action,
                "emotion": "quiet anticipation",
                "background": "stars, unmoving",
                "continuity": "the same night sky as the previous shot",
                "ending_frame": ending_frame,
                "audio_intent": "wind, distant",
                "transition": "cut",
                "avoid": ["text of any kind"],
            }
        )
    return json.dumps({"shots": planned})

