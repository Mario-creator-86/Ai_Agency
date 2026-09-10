# Brand — AMN-AI · Autonomous Machine Nexus — 2026-09-10

## The name

The agency is **AMN-AI**, short for **Autonomous Machine Nexus — Artificial Intelligence**.

| Where | Form used |
|---|---|
| Short mark, tight spaces, the H1, the top bar | `AMN-AI` |
| Standard, most user-facing surfaces | `AMN-AI · Autonomous Machine Nexus` |
| Full legal/identity form, footer, first mention in a document | `AMN-AI — Autonomous Machine Nexus — Artificial Intelligence` |

Write the short mark with a hyphen and no spaces. In the interface, the em dash separates the
expansion; the middot separates the mark from the expansion in the browser tab and the neon sign.

## Where the name is introduced

Interface (`frontend/`):

- Browser tab and share cards — `<title>`, `og:title`, `og:description`, `meta description`.
- Top bar — the mark next to `AMN-AI` / `Autonomous Machine Nexus`, with the full form on hover.
- Sign-in screen — the full lockup, the eyebrow `AUTONOMOUS MACHINE NEXUS · ARTIFICIAL INTELLIGENCE`
  and the invitation to "spațiul privat al agenției AMN-AI". This is the only screen a visitor sees
  before authenticating, so it carries the full identity.
- Workspace H1 — rendered from the studio row the backend serves, not from a literal in the page.
  The markup ships `AMN-AI` as the pre-snapshot placeholder so there is no flash of another name.
- Page footer — the full form.
- The 2D office — the building's neon sign reads `AMN-AI · AUTONOMOUS MACHINE NEXUS`, drawn by the
  renderer in the 5×7 pixel font (`office_engine.js`).

Backend and packaging:

- `STUDIO_NAME` in `.env.example` and the `Settings.name` default — `AMN-AI`.
- FastAPI application title, the simulated publishing adapter's channel title and the Channel B
  brand tagline.
- Distribution names: `amn-ai` (`pyproject.toml`, `uv.lock`) and `amn-ai-ui`
  (`frontend/package.json`, `frontend/package-lock.json`).

Repository: `README.md`, `AGENTS.md`, `start.cmd`, `scripts/start.py`.

## The stored studio name is domain state, not configuration

`bootstrap_studio` writes `STUDIO_NAME` **only** when it creates the studio row, and never again —
changing an environment default must not silently rewrite history that already exists. A studio
created before the rebrand therefore keeps its old name, and the interface keeps showing it,
because the H1 comes from the database.

Renaming is an explicit Owner act, recorded like any other change of state:

```shell
uv run python scripts/rename_studio.py --dry-run
uv run python scripts/rename_studio.py
```

It updates the row and appends a `studio.renamed` event (aggregate `studio`, next version,
carrying `previous_name`) in one transaction. It is idempotent, refuses an empty or over-long
name, and makes no provider calls. Covered by
`tests/test_foundation.py::test_renaming_the_studio_is_explicit_idempotent_and_audited`.

## The logo and its assets

The source artwork is an isometric cutaway office cube — the same idea the 2D scene renders — over
a cream ground, above the `AMN-AI` wordmark and the `Autonomous Machine Nexus` line. Two derived
forms are used, both generated from that source and committed under `frontend/public/`:

| Asset | Size | Used for |
|---|---|---|
| `amn-ai-mark.png` | 128×128 | Top-bar brand mark (rendered 38×38 on its cream card) |
| `amn-ai-lockup.png` | 480×509, transparent ground | Sign-in screen, rendered 200 px wide |
| `favicon.ico` | 16/32/48 | Browser tab, Windows |
| `favicon-32.png` | 32×32 | Browser tab (PNG) |
| `apple-touch-icon.png` | 180×180 | iOS home screen |
| `amn-ai-logo.png` | 512×512 | Canonical square master; `og:image` |

Rules:

- **The mark, never the lockup, at icon sizes.** The wordmark is illegible below ~120 px, so every
  icon is cropped to the cube alone, centred in a square with even breathing room.
- **The lockup has a transparent ground** so it sits on the light panel without a visible box; the
  mark keeps its cream ground because it sits on the dark top bar as a rounded card.
- **The mark is decorative in the top bar** (`alt=""`): the wordmark next to it already names the
  agency, so a screen reader would otherwise read the name twice.
- Assets are palette-quantised: the original 1.16 MB source became a 7.5 kB mark and a 31 kB
  lockup, so a page load costs about 8 kB of brand imagery instead of a megabyte.
- Regenerate derived assets from `amn-ai-logo.png`, not from a resized copy, and keep the intrinsic
  `width`/`height` attributes in `index.html` matching the rendered size so nothing shifts on load.

`frontend/public/favicon.svg`, the placeholder "A" mark of the previous name, was removed; nothing
referenced it and serving it would have kept an old identity alive in browser tabs.

## Deliberately left alone

- **The 78 documents in `docs/architecture/`.** Three of them still use the previous product name.
  That package is normative and hash-locked by `scripts/check_docs.py`; editing it requires a
  recorded specification change and an explicit index-hash update, which a rebrand does not justify.
- **Past entries in the decision log and changelog.** They record what was decided when, under the
  name in use at the time. History is appended to, not rewritten.
