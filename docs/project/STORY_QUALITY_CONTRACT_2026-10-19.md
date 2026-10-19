# Story quality contract for Marcus and Sarah — 2026-10-19

Eight questions live in `backend/app/story/quality_contract.py`. Marcus receives them in his existing write call and may return `self_review` in the same JSON object. His answers are saved to the episode continuity for audit, but are never passed to Sarah as evidence. Sarah receives the same eight questions in her existing episode-review call, and independently returns `quality` in her verdict. Explicit negative answers, unsupported YES answers, or missing keys in a supplied review turn a nominal PASS into FAIL with concise rewrite notes. Historical/legacy answers lacking the new field remain readable, with `quality_missing` stored so omission is visible.

The serial's editorial rewrite loop defaults to at most two versions (one targeted rewrite); a lower explicitly supplied limit is respected. Factual films, existing grounding, privacy, spending and publication permissions remain unchanged. No new LLM call is added for a successful script. Production film renders are not triggered by this patch.

Run offline: `python -m pytest tests/test_story_quality_contract.py tests/test_serial_pipeline.py tests/test_editorial_judgement.py -q`.
