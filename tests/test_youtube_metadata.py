"""What the studio sends YouTube fits YouTube's own limits (audit PUB-06, 2026-10-02).

YouTube (developers.google.com/youtube/v3/docs/videos): the title has at most 100 characters
and no '<' or '>'; the description at most 5000 bytes; the tags at most 500 characters,
commas between items counting, and a tag holding a space counting its quotation marks. Any
of them over is HTTP 400, which after a paid film is a FAILED_FINAL publication. Before this
work the adapter cut the description at 4800 *characters* (a Romanian description of 4800
characters is far more than 5000 bytes), the title at 100 characters with '<' left in, and
the tags at 50 items whatever their length.
"""

from __future__ import annotations

import pytest
from app.providers.youtube import (
    DESCRIPTION_LIMIT_BYTES,
    TAGS_LIMIT,
    TITLE_LIMIT,
    footer_start,
    tag_budget,
    youtube_safe_metadata,
)

FOOTER = "Disclosure: this video was produced with generative AI.\nCreated by Test Channel"


def test_angle_brackets_never_reach_youtube():
    title, description, tags = youtube_safe_metadata(
        "Why <b>stars</b> burn > forever", "A <script> inside > text.", ["a<b", "c>d"]
    )
    for text in (title, description, *tags):
        assert "<" not in text and ">" not in text
    assert title == "Why ‹b›stars‹/b› burn › forever"
    assert tags == ["a‹b", "c›d"]


def test_the_title_is_cut_at_a_word_to_one_hundred_characters():
    words = "Ștefan cel Mare și bătălia de la Vaslui " * 6
    title, _, _ = youtube_safe_metadata(words, "", [])
    assert len(title) <= TITLE_LIMIT == 100
    # Cut between words, never inside one, and marked as cut.
    assert title.endswith("…")
    assert words.startswith(title[:-1].rstrip())
    assert not title[:-1].endswith(" ")
    kept = title[:-1].split()
    assert all(word in words.split() for word in kept)


def test_an_empty_title_falls_back_to_the_script_title():
    title, _, _ = youtube_safe_metadata("   ", "", [], fallback_title="The <Script> Title")
    assert title == "The ‹Script› Title"
    # Nothing at all to name the film with still sends a title, never an empty one.
    title, _, _ = youtube_safe_metadata("", "", [])
    assert title


def test_a_title_has_no_line_breaks():
    title, _, _ = youtube_safe_metadata("One\nTwo\tThree", "", [])
    assert title == "One Two Three"


def test_the_description_is_cut_to_five_thousand_bytes_and_keeps_the_footer():
    # ă, ș and ț are two bytes each in UTF-8: 3000 characters of them are 6000 bytes, which
    # a character cut at 4800 sent whole.
    body = "Știință și țară, ăă " * 200
    assert len(body) < 4800 and len(body.encode("utf-8")) > 5000
    _, description, _ = youtube_safe_metadata("t", f"{body}\n\n{FOOTER}", [])
    assert len(description.encode("utf-8")) <= DESCRIPTION_LIMIT_BYTES == 5000
    assert description.endswith(FOOTER)
    assert description.count("Disclosure:") == 1
    # The body is cut at a word, marked, and decodes cleanly.
    head = description[: footer_start(description)].rstrip()
    assert head.endswith("…")
    description.encode("utf-8").decode("utf-8")


def test_a_short_description_is_left_as_it_is():
    text = f"What the film shows.\n\n{FOOTER}"
    assert youtube_safe_metadata("t", text, [])[1] == text


def test_making_metadata_safe_twice_changes_nothing():
    body = "Ă" * 4000 + " <tail>"
    tags = [f"tag number {n}" for n in range(60)]
    once = youtube_safe_metadata("Title <x> " * 20, f"{body}\n\n{FOOTER}", tags)
    assert youtube_safe_metadata(*once) == once


@pytest.mark.parametrize(
    ("tags", "expected_cost"),
    [
        (["space"], 5),
        (["deep space"], 12),  # quoted: "deep space"
        (["a", "b"], 3),  # a,b
        (["deep space", "jwst"], 12 + 1 + 4),
    ],
)
def test_the_tag_budget_counts_commas_and_quoted_spaces(tags, expected_cost):
    assert tag_budget(tags) == expected_cost


def test_tags_are_kept_within_five_hundred_characters():
    long_tags = [f"james webb space telescope fact {n:02d}" for n in range(30)]
    _, _, tags = youtube_safe_metadata("t", "", long_tags)
    assert tag_budget(tags) <= TAGS_LIMIT == 500
    # Kept in the order given, dropped from the end.
    assert tags == long_tags[: len(tags)]
    assert 0 < len(tags) < 30


def test_tags_are_cleaned_and_deduplicated():
    _, _, tags = youtube_safe_metadata("t", "", ["Space", " space ", "", "a,b", "  two  words "])
    assert tags == ["Space", "a b", "two words"]
