# Public source retrieval — Codex handoff

## Implemented scope

Owner-directed retrieval of a known public HTTPS URL lives in
`backend/app/research/retrieval.py`. The local entry point is
`scripts/research_source.py`. No frontend, media, provider registry, worker,
database migration or application router was changed.

The adapter validates every redirect against an exact hostname allowlist,
rejects non-public DNS answers (including mixed public/private answers), and
connects to the validated IP while retaining the original hostname for TLS
verification. It sends no cookies, credentials or environment proxy settings to
external sources. Non-200 responses, unsupported encodings/content types,
truncated responses and excessive body/text sizes fail explicitly. A rate limit
returns a typed error with the source's Retry-After value; it never retries on its own.

HTML extraction excludes script/style/template content. The existing ingestion
service applies its injection filter and persists the raw extracted text, sanitized
text, content hash and source event. Retrieved text remains untrusted evidence.
No claim is created or marked supported. Credibility is initialized to zero
(unassessed), not inferred from HTTPS or a successful download. Publisher denotes
the URL hostname, not an authenticated editorial identity.

## Run from the project root

Preview a source without writing studio state:

```shell
uv run python scripts/research_source.py https://www.iana.org/help/example-domains --allow-host www.iana.org
```

To ingest, add `--ingest`. This uses the existing authenticated local Owner API
on the configured studio port and loads the token from existing settings without
printing it. The studio must already be running. Add `--topic-id` to associate an
existing topic. Add `--receipt output/source-receipt.json` to save retrieval
provenance to a **new** file; an existing receipt is never overwritten. Create the
receipt's parent directory first. A receipt records retrieval, not successful
ingestion; stdout includes the source ID only after the API confirms ingestion.

The receipt includes requested/final URL, retrieval timestamp, response-body hash
and extracted-content hash. The database currently stores the final URL and
extracted-content hash; retain the receipt separately when original response
provenance is needed. Receipt files do not contain the fetched body.

## Limits and exact next work

- This implements known-URL fetching, not keyword search, source ranking or the
  complete search-provider contract in `../architecture/22_PROVIDER_INTEGRATION_CONTRACTS.md`.
- No independent fact checker, UI action or automatic worker integration is added.
  Phase 4 remains partial. Implement role-separated verification before claiming acceptance.
- The bounded cache is per adapter instance, in memory, with a default five-minute
  TTL. Separate CLI invocations refetch. Use one instance per worker; concurrent
  request coalescing and persistent caching are not implemented.
- TLS and socket operations have timeouts; body reads check an overall deadline.
  OS DNS resolution and HTTP header parsing are not hard wall-clock cancellable.
- HTML is parsed without JavaScript rendering. PDFs, compressed responses, login,
  CAPTCHA and paywall handling are unsupported. There is no restriction bypass.
- Ingestion uses the existing endpoint, whose command ID is not an idempotency
  guard. Do not automatically retry a POST after an uncertain response: inspect
  source/event history first. This adapter does not enable autonomous execution.

## Verification

Dedicated tests exercise URL policy, private/mixed DNS, pinned TLS hostname,
redirect revalidation, rate limits, download/text limits, unsupported responses,
truncation, network failure, cache expiry/eviction, and authenticated source
ingestion with no automatic factual verification.

Real HTTPS verification fetched IANA's Example Domains page and ingested its
extracted content through the authenticated API into an isolated temporary
database. Returned and calculated hashes matched. The running studio database
was not modified. Evidence is in `output/research_verified_ingestion.json`.

Tests intentionally use controlled responses for failure scenarios; those tests
are not evidence of a search-provider integration or factual correctness.
