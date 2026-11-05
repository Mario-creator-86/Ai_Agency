# Instructions for the next coding AI — Mario Agent Town

Read `HANDOFF.md`, `README.md`, `PROJECT_STATE.json` and `art/README_CLAUDE.md` first. This directory is a NEW, independent local prototype explicitly requested by Mario on 2026-11-05. It lives on a feature branch of the existing Ai_Agency repository because the available GitHub integration cannot create a new repository. The current user request authorizes this sidecar project; it does not replace or migrate the existing AMN-AI studio.

Keep all application changes within `mario-agent-town/` unless a separately scoped bridge to the parent studio is requested. Parent documentation tracks this exception. Do not automatically merge this branch. The parent's production runtime, databases, credentials, media and character identities are unrelated to this prototype.

Requirements from the Owner: exactly ten named agents, ten houses, a central Town Hall, park/benches/fountain, a larger CEO house, walkable Mario avatar and agents who look toward him, inter-agent communication, direct/group chat, autonomous work and precise jobs. Maria owns the entire YouTube growth goal of 1M subscribers. Ana is the personal assistant; Radu researches AI/markets/news. The other seven have explicit charters in `src/agents.mjs`. Providers should use ChatGPT/Codex and Claude subscriptions where officially supported, or Ollama local/cloud. Do not silently introduce paid OpenAI/Anthropic API billing.

Mario is bald with a salt-and-pepper beard. Use only the confirmed sprite in `public/assets/mario-sprites.webp`. His sweater MUST have a short zipper at the neck. The earlier short-haired man's photo was explicitly rejected as a different person: do not retrieve or use it. Do not commit original photos, auth tokens, .env, databases or user activity.

Do not turn scenery into fake work evidence. Only backend records indicate real activity. Configured does not mean authenticated or verified. Demo replies must remain explicitly labeled. Never describe scripts or production plans as rendered/published films.

Run `npm test` and syntax checks after code changes. Use temporary data for tests. No real vendor calls in the test suite. Live acceptance is a distinct owner-machine step. Update HANDOFF, PROJECT_STATE and the parent tracking note with actual results, blockers and the next task. Maintain small, reversible commits.

## Owner graphic update, 2026-11-05

The Owner explicitly requested richly colored illustrated RPG village graphics instead of the first flat pastel isometric scene, then asked for drawn characters/city images so Claude can continue. The v2 art is in public/assets with its exact inventory and slicing contract in art/manifest.json. Preserve this delivered map, ten unique animated character sheets and the approved quarter-zip CEO. The display coordinates are authoritative in public/village-layout.js; the old x/y presentation fields in src/agents.mjs are legacy and not used by the new renderer. Do not paint static people into the background or duplicate atlas buildings over the already painted map. No new external integrations were added by the graphic revision.

## Owner update v3, 2026-11-05

Roles remapped by the Owner (see HANDOFF v3). Ten core agents remain; the Owner explicitly asked that Alex may propose new hires, created only after the Owner says yes, so `staff` rows can add agents. Hires reuse an existing sheet plus a code-painted vest. Higgsfield was not used. Movement rules and the Town Hall seating live in `public/town.js` and `public/village-layout.js`.
