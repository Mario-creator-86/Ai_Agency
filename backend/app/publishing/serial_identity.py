"""The serial's identity at publish: which series, which episode, and what came before.

Measured in the rehearsal of 2026-09-18 and read again on the code of 2026-09-24: an episode
reached the Publisher as "Storyboard: <episode title>" with its scenes and nothing else, so it
went out as a film with no series, no number and no link to the episode before it. The
architecture asks for the opposite (07_STORY_ENGINE.md, "New viewer accessibility": recurring
identifiers and "episode metadata linking prior related episode").

What this module decides, and nothing more:

- `episode_identity` reads, from the script a film was shot from, the facts the Publisher is
  given: the series, the episode number, the episode's own title (never the storyboard's
  "Storyboard: " label), its logline and the previous episode. A film that is not an episode
  has no identity, and nothing here touches it.
- `series_title` writes a title in the series' one format, ``<hook> | Inside The Nexus Ep. N``;
  `hook_of` reads the hook back out of a title, so the metadata guard judges the words the
  Publisher chose and never the series name the studio adds to every episode.
- `fallback_metadata` is the studio's own title, description and tags for an episode, built
  from the episode alone, used when the Publisher's answer is refused by the guard. It is
  judged by the same guard before it may go.
"""

from __future__ import annotations

import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.factual.models import ScriptDraft
from app.media.models import VideoRenderJob
from app.publishing.models import PublicationRecord

#: The serial's public name, as the brief, the page and every episode title carry it.
SERIES_NAME = "Inside The Nexus"
#: The title limit the Publisher's schema and YouTube both hold.
TITLE_LIMIT = 100
#: A description may not grow past the Publisher's schema limit.
DESCRIPTION_LIMIT = 5000
#: The storyboard's own label on its title, which is not the film's title.
_STORYBOARD_PREFIX = re.compile(r"^\s*storyboard\s*:\s*", re.IGNORECASE)
#: The series marker wherever a model put it: "| Inside The Nexus Ep. 3" after the hook, or
#: "Inside The Nexus, Ep 3:" before it, with any separator and any spelling of "episode".
_MARKER = r"inside\s+the\s+nexus(?:\s*[,:\-–—]?\s*(?:ep(?:isode)?\.?\s*#?\s*\d+))?"
_TRAILING_MARKER = re.compile(rf"\s*[|\-–—:·•]*\s*{_MARKER}\s*[|\-–—:·•]*\s*$", re.IGNORECASE)
_LEADING_MARKER = re.compile(rf"^\s*{_MARKER}\s*[|\-–—:·•]+\s*", re.IGNORECASE)
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")


def _one_line(text: Any) -> str:
    return " ".join(str(text or "").split())


def series_suffix(episode_number: int | None) -> str:
    """`` | Inside The Nexus Ep. N``, or the series name alone when the number is unknown."""
    if episode_number:
        return f" | {SERIES_NAME} Ep. {int(episode_number)}"
    return f" | {SERIES_NAME}"


def hook_of(title: str) -> str:
    """The words a title chose, without the storyboard's label or the series marker."""
    text = _STORYBOARD_PREFIX.sub("", _one_line(title))
    for _ in range(2):  # a model may write the marker at both ends
        text = _TRAILING_MARKER.sub("", text)
        text = _LEADING_MARKER.sub("", text)
    return text.strip(" |-–—:·•")


def series_title(hook: str, episode_number: int | None) -> str:
    """``<hook> | Inside The Nexus Ep. N`` within the title limit; the hook is shortened at a
    word, never the series marker."""
    suffix = series_suffix(episode_number)
    words = hook_of(hook)
    room = TITLE_LIMIT - len(suffix)
    if len(words) > room:
        cut = words[: room - 1].rsplit(" ", 1)[0].rstrip(" ,;:-–—")
        words = f"{cut}…" if cut else words[:room]
    return f"{words}{suffix}" if words else suffix.lstrip(" |")


def _folded(text: str) -> str:
    return re.sub(r"[^\w]+", " ", str(text or "").casefold()).strip()


def series_description(description: str, identity: dict[str, Any]) -> str:
    """The description opening with the logline, and naming the previous episode at the end.

    Neither is added twice: a description that already opens with the logline, or already
    names the previous episode's title, keeps its own words.
    """
    text = str(description or "").strip()
    logline = _one_line(identity.get("logline"))
    if logline and not _folded(text).startswith(_folded(logline)):
        text = f"{logline}\n\n{text}" if text else logline
    previous = identity.get("previous_episode") or {}
    previous_title = _one_line(previous.get("title"))
    if previous_title and _folded(previous_title) not in _folded(text):
        line = (
            f"Previously on {SERIES_NAME}: Ep. {previous.get('episode_number')}, "
            f"“{previous_title}”."
        )
        if previous.get("url"):
            line += f" {previous['url']}"
        text = f"{text}\n\n{line}" if text else line
    return text[:DESCRIPTION_LIMIT]


def series_tags(tags: list[str]) -> list[str]:
    """The series name first, then the Publisher's tags, at most 15, none twice."""
    kept = [SERIES_NAME]
    for tag in tags:
        if tag.casefold() not in {k.casefold() for k in kept}:
            kept.append(tag)
    return kept[:15]


def logline_of(episode: Any) -> str:
    """The episode's logline: the writer's own (brief v4), else the first sentence of its
    summary (an episode written before v4), else its title."""
    continuity = episode.continuity_json if isinstance(episode.continuity_json, dict) else {}
    logline = _one_line(continuity.get("logline"))
    if logline:
        return logline[:300]
    summary = _one_line(continuity.get("summary"))
    if summary:
        return _SENTENCE_END.split(summary, maxsplit=1)[0][:300]
    return _one_line(episode.title)[:300]


def _public_url(session: Session, storyboard_id: str | None) -> str | None:
    """Where the audience can watch an episode: a publication anyone may open, or nothing.

    A private upload is not a link a stranger can follow, so it is never given.
    """
    if not storyboard_id:
        return None
    for job in session.scalars(
        select(VideoRenderJob).where(VideoRenderJob.storyboard_id == storyboard_id)
    ):
        if not job.output_asset_id:
            continue
        for record in session.scalars(
            select(PublicationRecord).where(PublicationRecord.media_asset_id == job.output_asset_id)
        ):
            if record.remote_url and str(record.privacy_status).lower() in ("public", "unlisted"):
                return record.remote_url
    return None


def episode_identity(session: Session, script: ScriptDraft | None) -> dict[str, Any] | None:
    """The series facts of the episode a script dramatises, or None for any other film."""
    from app.story.models import StoryEpisode  # noqa: PLC0415 - story imports publishing

    story = script.story_json if script is not None and isinstance(script.story_json, dict) else {}
    if story.get("kind") != "office_serial_episode":
        return None
    episode = (
        session.get(StoryEpisode, story.get("episode_id")) if story.get("episode_id") else None
    )
    continuity = (
        episode.continuity_json
        if episode is not None and isinstance(episode.continuity_json, dict)
        else {}
    )
    number = continuity.get("episode_number") or story.get("episode_number")
    title = hook_of(episode.title if episode is not None else (script.title if script else ""))
    previous: dict[str, Any] | None = None
    if isinstance(number, int) and number > 1:
        for row in session.scalars(select(StoryEpisode).where(StoryEpisode.status == "APPROVED")):
            data = row.continuity_json if isinstance(row.continuity_json, dict) else {}
            if data.get("episode_number") == number - 1:
                previous = {"episode_number": number - 1, "title": hook_of(row.title)}
                url = _public_url(session, row.storyboard_id)
                if url:
                    previous["url"] = url
                break
        if previous is None and continuity.get("previous_episode_title"):
            previous = {
                "episode_number": number - 1,
                "title": hook_of(str(continuity["previous_episode_title"])),
            }
    return {
        "series": SERIES_NAME,
        "episode_number": number if isinstance(number, int) else None,
        "episode_title": title,
        "logline": logline_of(episode) if episode is not None else title,
        "previous_episode": previous,
        "title_format": series_title("<hook>", number if isinstance(number, int) else None),
    }


def fallback_metadata(identity: dict[str, Any], characters: list[str]) -> dict[str, Any]:
    """The studio's own metadata for an episode, from the episode alone: its title in the
    series format, its logline and the previous episode, and tags naming the series and the
    people in it. Deterministic, so the same episode always gets the same words."""
    tags = [str(name).split("(")[0].strip() for name in characters if str(name).strip()]
    return {
        "title": series_title(identity.get("episode_title") or "", identity.get("episode_number")),
        "description": series_description("", identity),
        "tags": series_tags([*dict.fromkeys(t for t in tags if t), "office comedy"]),
    }
