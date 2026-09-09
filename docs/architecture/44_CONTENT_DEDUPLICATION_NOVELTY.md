# Content Deduplication and Novelty

## Purpose

Autonomous channels can drift into repetitive, spam-like content even when every individual video is valid.

## Compare against history

For each candidate:
- semantic topic similarity;
- same core fact;
- same hook structure;
- same title pattern;
- same storyboard pattern;
- same visual template;
- recent category frequency.

## Thresholds

Use:
- hard duplicate threshold;
- soft similarity penalty;
- cooldown by topic/fact.

## Exceptions

A sequel/series is allowed if:
- intentional;
- adds new information/story;
- tagged as series;
- Director logs reason.

## Serial channel

Recurring characters are expected, but daily episode conflict/story should not be copy-paste.

## Main channel

Avoid rephrasing the same fact with a new background.

## Detection

Use a combination of:
- normalized text hashes;
- embeddings;
- entity/topic tags;
- manual/Director review for borderline cases.

## Analytics

Track novelty alongside performance to avoid learning that repetitive clickbait is the only objective.
