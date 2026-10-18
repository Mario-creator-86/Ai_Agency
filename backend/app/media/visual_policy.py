"""Effective policy for agent context; historical packages remain immutable."""

from __future__ import annotations

import re
from copy import deepcopy
from typing import Any

# Full clauses only: never remove a mixed rule or a scene-specific rear composition.
_RETIRED = re.compile(
    r"(?:no (?:human |visible )?faces?(?: (?:appear|visible))?|"
    r"(?:human )?faces? (?:must (?:not|never) be (?:visible|shown)|"
    r"(?:are |is )?(?:forbidden|hidden))|"
    r"(?:avoid|hide) (?:all |human )?faces?|"
    r"(?:people|characters|scientists) (?:must |should )?(?:only |always )?"
    r"(?:be (?:seen|shown|filmed) (?:only )?from behind|face away from (?:the )?camera)|"
    r"faces?|facial features|eye contact|front[- ]facing (?:people|characters|views?)|"
    r"any visible face in the frame|faces turned toward (?:the )?camera|facing the camera)",
    re.IGNORECASE,
)
POLICY_NOTE = (
    "Under explicit face_policy ALLOW, permit visible faces, frontal/three-quarter views, "
    "eye contact, "
    "close-ups and natural expressions; it does not require frontal framing. Retired blanket "
    "face bans in historical feedback are not current requirements under ALLOW. "
    "Without ALLOW/REQUIRE, retain the existing face policy. Preserve explicit artistic "
    "orientation unless Sarah approves a plan correction. A demand to show chest medals "
    "from behind is a PLAN_CONFLICT: identify the incompatible clauses and obtain a coherent "
    "editorial plan before approving a purchase. Judge attributes anywhere in words_to_send; "
    "do not request a phrase already present or transfer still requirements to motion."
    " When correcting a scene-specific orientation conflict, return editorial_visual_intent "
    "with the complete approved replacement plan. This supersedes only the orientation "
    "of the old plan; retain its people, objects, location, lighting and narrative purpose. "
    "The candidate and its replacement intent must be reviewed together before storing."
    " An editorial_authority event is an existing Owner-approved plan correction. Its "
    "editorial_visual_intent supersedes the old scene's orientation in writer_visual, "
    "continuity, avoid and the visual bible, while their other requirements remain. "
    "Do not undo that correction to satisfy superseded orientation clauses."
)


def orientation_conflict(package: dict[str, Any], bible: dict[str, Any]) -> bool:
    """A narrow physical contradiction, not a ban on artistic rear views."""
    text = " ".join(
        str(package.get(k) or "")
        for k in (
            "writer_visual",
            "subject",
            "action",
            "composition",
            "continuity",
            "ending_frame",
        )
    ).lower()
    return bool(
        re.search(r"from behind|from the back|backs? (?:of|to)|rear view", text)
        and re.search(r"medals?", text)
        and re.search(r"chest|front of (?:their|each|the) (?:jacket|chest)", text)
    )


def effective_policy(
    record: dict[str, Any], bible: dict[str, Any]
) -> tuple[dict[str, Any], list[dict[str, str]]]:
    """Retire only recognized whole blanket-ban clauses under explicit ALLOW/REQUIRE."""
    shown = deepcopy(record)
    retired: list[dict[str, str]] = []
    if str(bible.get("face_policy") or "").upper() not in ("ALLOW", "REQUIRE"):
        return shown, retired
    for key in ("avoid", "continuity", "continuity_rules", "rules", "people_rule"):
        value = shown.get(key)
        if not isinstance(value, (str, list)):
            continue

        def clean(text: str, field: str = key) -> str:
            # A sentence with multiple requirements stays intact for editorial diagnosis.
            clauses = re.split(r"(?<=[.!?;])\s+", text)
            kept = []
            for clause in clauses:
                plain = clause.strip().rstrip(".;!?")
                if _RETIRED.fullmatch(plain):
                    retired.append(
                        {
                            "field": field,
                            "original": plain,
                            "reason": (
                                f"Blanket face ban superseded by face_policy {bible['face_policy']}"
                            ),
                        }
                    )
                else:
                    kept.append(clause)
            return " ".join(kept)

        if isinstance(value, list):
            shown[key] = [cleaned for item in value if (cleaned := clean(str(item)))]
        else:
            shown[key] = clean(value)
    return shown, retired
