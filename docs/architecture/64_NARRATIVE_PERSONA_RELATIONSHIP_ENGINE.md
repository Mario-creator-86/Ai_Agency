# Narrative Persona & Relationship Engine

## Purpose

Make AI employees feel consistent, recognizable and human-like in the fictional office universe without confusing narrative personality with technical capability.

## Core principle

Operational correctness wins over personality.

A sarcastic Fact Checker still has to fact-check correctly.
A nervous Research Agent still receives the same factual standards.
A confident CEO cannot override hard gates.

## Persona definition

Each AgentCharacter may have:
- persona_id;
- persona_version;
- in-universe birthday;
- traits;
- humor;
- speech cadence;
- values;
- likes/dislikes;
- quirks;
- preferred props;
- social energy;
- conflict style;
- strengths/weaknesses for narrative use;
- recurring jokes;
- voice;
- visual references.

## Relationship edges

Between characters:
- affinity;
- trust;
- rivalry;
- respect;
- tension;
- mentorship;
- familiarity.

Use bounded scores/tags.

Update only from committed events, not arbitrary LLM whim.

## Event-driven relationship update

Examples:
- successful collaboration increases rapport;
- repeated verified disagreement may increase rivalry/tension;
- team building can alter relationship state;
- onboarding can create mentorship;
- firing ends active workplace relationship but preserves history.

## Narrative consistency

Showrunner should query:
- current persona versions;
- active roster;
- relationship graph;
- recent story threads.

Do not let the model freely invent a new personality every episode.

## Transparency

Public product should make clear that these are AI/fictitious characters/personas rather than real human employees.

## Safety

Do not generate hateful, sexualized, humiliating or targeted harassment as a default "personality feature."

Workplace comedy may use mild conflict, but should remain brand-safe and controllable.
