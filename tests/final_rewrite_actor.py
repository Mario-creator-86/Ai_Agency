"""Explicit final-text responses for the historical scripted rewrite actors.

Only test providers use this adapter. Production never fabricates a model response.
"""

import json
import re


def final_answer(prompt, answer):
    if not isinstance(answer, dict):
        return answer
    match = re.search(
        r'<untrusted_source_evidence hash="scene-rewrite">\n(.*?)\n</untrusted_source_evidence>',
        prompt,
        re.DOTALL,
    )
    data = json.loads(match.group(1))
    out = dict(answer)
    before = data["prompts_sent"]["still"]
    layer = data["director_brief"]["layer"]
    out.setdefault(
        "still_prompt",
        before
        if layer == "motion"
        else ". ".join(
            str(answer[k]).rstrip(".")
            for k in ("subject", "action", "environment", "camera", "lighting")
            if answer.get(k)
        )
        + ". Faces not visible.",
    )
    # This actor explicitly says its chosen movement and ending; the application must
    # retain this exact string, not derive prose from those planning fields.
    out.setdefault(
        "motion_prompt",
        str(answer.get("camera_move") or "Static camera")
        + ". "
        + ". ".join(str(answer[k]).rstrip(".") for k in ("motion", "ending_frame") if answer.get(k))
        + ".",
    )
    return out


def final_review(review):
    """The scripted Director names the final field instead of a retired planning field."""
    if not isinstance(review, dict):
        return review
    out = json.loads(json.dumps(review))
    for item in out.get("findings", []):
        if item.get("field") in ("motion", "ending_frame", "emotion"):
            item["field"] = "motion_prompt"
    return out
