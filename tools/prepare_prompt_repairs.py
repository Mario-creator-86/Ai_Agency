"""Compile nine recorded examples into offline proposals; never writes studio records."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.media.prompt_agent import (  # noqa: E402
    compile_prompts,
    compose_serial_motion,
    compose_serial_prompt,
    composition_issues,
    motion_prompt_for,
)
from app.media.prompt_lint import BLOCK, LintScene, lint_scene, utf16_units  # noqa: E402
from app.media.series_look import load_series_look  # noqa: E402

SERIAL_ID = "f06808c9-40d4-4f40-a980-84b6a5540348"
PARTICLE_ID = "babcf272-0667-41b9-ae70-27304eef92ca"
CYCLOTRON_ID = "aa170155-56c7-4e29-9616-e1e917fb243e"

# Editorial proposals for the frozen examples, not a runtime rewrite heuristic.
PATCHES = {
    (SERIAL_ID, 1): {
        "subject": "Marcus at his desk, Sarah's shoulder at the doorway edge.",
        "action": (
            "Marcus holds his hands above the keyboard; Sarah's shoulder stays at the doorway edge."
        ),
        "camera_move": "static",
        "ending_frame": (
            "Marcus turned toward the doorway, hands above the keys, Sarah's "
            "shoulder still at the edge."
        ),
    },
    (SERIAL_ID, 2): {
        "action": "Marcus counts on his fingers; Sarah sets down her cup, then raises her chin.",
        "ending_frame": (
            "Sarah's chin raised, Marcus's open hand between them, both facing the viewer."
        ),
    },
    (SERIAL_ID, 4): {
        "background": (
            "The calculator with its paper roll, a jar of sharpened pencils and two untouched "
            "cups of tea stay on Nadia's desk. Warm lamplight and bookshelves fill the quiet "
            "office behind her."
        ),
        "action": (
            "Nadia taps the brass pen on the blank green ledger, then lays it flat;"
            " Sarah's shoulder and arm stay at the right edge."
        ),
        "camera_move": "static",
        "ending_frame": (
            "Nadia's pen flat on the blank green ledger, Sarah's shoulder still at the right edge."
        ),
    },
    (SERIAL_ID, 6): {
        "action": "Sarah holds the doorframe; Marcus lowers his head; Kael's chair is empty.",
        "ending_frame": (
            "Sarah's hand on the doorframe, Marcus's head tilted, Kael's empty "
            "chair between them and the viewer."
        ),
    },
    (SERIAL_ID, 7): {
        "action": (
            "Sarah smiles at notes; Marcus holds a marker over a blank board, then "
            "lowers it and turns toward Sarah."
        ),
        "ending_frame": "Marcus turned toward Sarah, marker lowered, both smiling.",
    },
    (CYCLOTRON_ID, 3): {
        "subject": (
            "Two hollow D-shaped brass electrodes in a round chamber about ten "
            "centimetres across, straight edges facing across a narrow "
            "millimetre-scale gap, between two round flat iron magnet poles."
        ),
        "ending_frame": (
            "The narrow gap between two straight brass electrode edges, softly "
            "glowing, the curved D-shaped backs visible on both sides."
        ),
    },
    (PARTICLE_ID, 5): {
        "subject": (
            "A stable cluster of glowing white spheres representing an atom in a "
            "near-black abstract space."
        ),
        "action": (
            "The white spheres draw close into a stable cluster, their orbits "
            "settling into a steady hold."
        ),
        "environment": "A near-black abstract space around the white cluster.",
        "camera": "Medium shot on the atom cluster, 85mm lens.",
        "lighting": "White glow from the spheres with faint blue binding fields between them.",
        "composition": "The single white cluster centred in the vertical frame.",
        "motion": "The spheres settle into gentle oscillation and hold together.",
        "background": "Near-black space around the white cluster.",
        "continuity": "White spheres and blue binding fields retain their shape and colour.",
        "ending_frame": (
            "The white spheres held in one stable cluster, thin blue fields between them."
        ),
        "transition": "Hold on the cluster; fade to black during assembly.",
    },
}


def prepare(rows: list[dict]) -> dict:
    look = load_series_look()
    examples = []
    for row in rows:
        source = row["source"]
        old = row["package"]
        fields = PATCHES.get((source["storyboard_id"], source["scene"]), {})
        proposed = {**copy.deepcopy(old), **fields}
        if source["kind"] == "serial":
            proposed["still_prompt"] = compose_serial_prompt(proposed, look)
            proposed["motion_prompt"] = compose_serial_motion(proposed, look)
        else:
            proposed.update(compile_prompts(proposed, row["bible"], {"model_id": source["model"]}))
        motion, negative = motion_prompt_for(proposed, source["model"])
        issues = composition_issues(proposed, proposed["still_prompt"], motion)
        findings = lint_scene(
            LintScene(
                scene=source["scene"],
                still_prompt=proposed["still_prompt"],
                motion_prompt=motion,
                model_id=source["model"],
                composition_issues=tuple(issues),
            ),
            bible=row["bible"],
        )
        canonical = old.get("in_frame") or old.get("characters") or []
        needs_story = source["storyboard_id"] == PARTICLE_ID
        review = [
            "Sarah must compare every current QC finding with these actual compiled words.",
            (
                "Check the current storyboard, canonical characters, claims and "
                "accepted source image; this snapshot can be stale."
            ),
            "A local lint pass is not a Director TREATS decision or visual acceptance.",
        ]
        if canonical:
            review.append(
                "Compare all visible clothing, props and framing with the complete "
                "character bible and references, not only the minimum compiler identity"
                " clauses."
            )
        if source["scene"] == 1 and source["kind"] == "serial":
            review.append(
                "Marcus/Sarah: the stored subject says Sarah is absent but the "
                "action/cast includes her at the doorway. This draft keeps her shoulder"
                " visible; Sarah/showrunner must settle that narrative conflict."
            )
        if source["scene"] == 4 and source["kind"] == "serial":
            review.append(
                "The recorded accepted image wore the wrong clothes. Rejudge the "
                "existing still against Nadia's plum blouse/violet cardigan; a motion "
                "prompt cannot change that first frame. Keep Sarah as a shoulder/arm, "
                "not a second full person."
            )
        if needs_story:
            review.append(
                "Marcus/Sarah must approve removing the atom-to-tunnel dissolve: this "
                "draft remains in one conceptual shot. Verify the Higgs/mass/binding "
                "explanation against the original verified claims; no new factual "
                "approval is supplied here."
            )
        if source["kind"] == "factual":
            review.append(
                "Check scientific fidelity and whether any time compression/conceptual "
                "effects require disclosure; this tool tests transport, not scientific "
                "accuracy."
            )
        examples.append(
            {
                **source,
                "status": "OFFLINE_DRAFT_NOT_DIRECTOR_APPROVED",
                "auto_apply": False,
                "historical_rejected_board": source["board_status"] == "REJECTED",
                "repair_owner": "Marcus + Sarah, then Kael" if needs_story else "Kael + Sarah",
                "required_layer": "story/shot plan"
                if needs_story
                else "still"
                if fields.get("action") or fields.get("subject")
                else "motion",
                "source_package_sha256": hashlib.sha256(
                    json.dumps(old, sort_keys=True, ensure_ascii=False).encode()
                ).hexdigest(),
                "field_changes": {k: {"before": old.get(k), "after": v} for k, v in fields.items()},
                "before": {"still": old.get("still_prompt"), "motion": old.get("motion_prompt")},
                "after": {
                    "still": proposed["still_prompt"],
                    "motion": motion,
                    "negative": negative,
                },
                "compiled_motion_sha256": hashlib.sha256(motion.encode()).hexdigest(),
                "canonical_characters": canonical,
                "composition_issues": issues,
                "blocks": [f.as_dict() for f in findings if f.severity == BLOCK],
                "warnings": [f.as_dict() for f in findings if f.severity != BLOCK],
                "prompt_units": {
                    "still": utf16_units(proposed["still_prompt"]),
                    "motion": utf16_units(motion),
                },
                "required_review": review,
                "proposed_package": proposed,
            }
        )
    return {
        "method": (
            "Frozen recorded examples and deterministic compilers; no providers, "
            "live database writes or approvals."
        ),
        "examples": examples,
        "examples_blocked": sum(bool(e["blocks"]) for e in examples),
    }


def markdown(result: dict) -> str:
    lines = [
        "# Propuneri locale de prompturi — 14 octombrie 2026",
        "",
        "«Înainte» sunt cuvintele stocate în snapshot-ul scenei; nu certifică ce s-a trimis "
        "efectiv la GPU. «Propunere» este text compus local, fără o cerere nouă către model.",
        "",
        (
            "Sunt nouă exemple revizuite offline. Nu sunt aplicate în producție și "
            "nu au aprobarea Directoarei. "
        )
        + (
            "Textele de mai jos sunt cele compuse efectiv; trecerea lint-ului nu "
            "garantează calitatea imaginii sau corectitudinea științifică."
        ),
        "",
        (
            "Nu redeschideți filme respinse/închise. Pentru un film încă deschis: "
            "dosar actual → diagnosticul lui Sarah → "
        )
        + (
            "agentul potrivit → rescriere → Sarah verifică fiecare constatare în "
            "promptul compus → request identic în jurnal → QC pe noul rezultat."
        ),
        "",
    ]
    for item in result["examples"]:
        lines += [
            f"## {item['title']} — scena {item['scene']}",
            "",
            f"Starea înregistrată: {item['board_status']}. Responsabil: {item['repair_owner']}. "
            f"Strat propus: {item['required_layer']}. Blocaje deterministe: {len(item['blocks'])}.",
            "",
            "### Ce se modifică",
            "",
        ]
        lines += [
            f"- `{name}`: {change['before']} → {change['after']}"
            for name, change in item["field_changes"].items()
        ]
        if not item["field_changes"]:
            lines += [
                (
                    "Corecție de compunere: referința la altă scenă nu mai șterge toate "
                    "clauzele vizibile ale finalului."
                )
            ]
        for layer, name in (("still", "Imagine"), ("motion", "Mișcare")):
            lines += [
                "",
                f"### {name} — înainte",
                "",
                str(item["before"][layer] or ""),
                "",
                f"### {name} — propunere compusă",
                "",
                item["after"][layer],
            ]
        lines += ["", "### Verificări necesare înainte de folosire", ""]
        lines += [f"- {text}" for text in item["required_review"]]
        lines += [
            "",
            f"Amprentă a promptului video compus: `{item['compiled_motion_sha256']}`.",
            "",
        ]
    return "\n".join(lines)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input", type=Path, default=ROOT / "tests/fixtures/prompt_contract_followup.json"
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = prepare(json.loads(args.input.read_text(encoding="utf-8")))
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    args.output.with_suffix(".md").write_text(markdown(result), encoding="utf-8")
    print(
        json.dumps(
            {
                "examples": len(result["examples"]),
                "blocked": result["examples_blocked"],
                "applied_to_production": False,
            },
            ensure_ascii=False,
        )
    )
