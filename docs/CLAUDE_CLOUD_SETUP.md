# Start an offline Claude Code cloud audit

1. Open https://claude.ai/code and sign in to the existing Claude account.
2. Connect GitHub through the browser. For this private repository, install/configure the
   Claude GitHub App with access to `Mario-creator-86/Ai_Agency` only as needed.
3. Select `Mario-creator-86/Ai_Agency`, branch `main`, and a cloud environment. Keep vendor
   API keys and the production Owner token out of the environment.
4. Install the locked development dependencies in the cloud checkout:

```shell
uv sync --locked
npm ci --prefix frontend
```

Use the project Python pin when available; the declared supported range is Python
3.12–3.14. If necessary, use `uv sync --locked --python 3.12` for a supported cloud runtime
without changing `.python-version` or the lock. Read README.md's SQLite runtime requirement.
Package-install network access is needed; production vendor access is not.

Run the documentation/secret gates, Python lint/type checks, non-slow tests, frontend checks
and build listed in CLAUDE.md. All provider transports are faked by the test suite. The
inherited GitHub Actions workflow is manual-only, so uploading code starts no Actions jobs.

## Optional local-only model restoration

`backend/app/media/models/yunet_2023mar.onnx` is excluded from Git. The original installation
retains its model. A fresh checkout needs this model for actual face measurement and certain
film tests. This is a 232,589-byte CPU QC model, not a generation model or GPU workload.

The approved model source is `app.media.faces.YUNET_SOURCE` and its required SHA-256 is
`8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4`.
Download only that file when deliberately setting up a disposable full-QC environment,
verify that checksum before putting it at the ignored path, and retain `LICENSE-YuNet`.
Do not run the RunPod worker model resolver or download generation weights for a cloud audit.

Without YuNet, face checks must say NOT_RUN and production must refuse unmeasured media.
Full film tests need FFmpeg/FFprobe; browser tests also need a Playwright Chromium install.
Windows service/DPAPI, Blender/Unreal and local GPU integrations require the Owner's machine.
Cloud checks cannot prove those production integrations work.

## First task

Read CLAUDE.md and AGENTS.md. Audit the existing architecture, startup and offline tests.
Prioritize the media repair loop, refusal/re-purchase guards, prompt rewrites, fresh seeds,
Director second-look decisions and dependency vulnerabilities. Preserve local Windows 11,
Ollama/local AI, Owner STOP, budgets and encrypted credentials. Use a feature branch and
return a Pull Request with tests. Do not connect production accounts, run paid/GPU jobs,
weaken quality gates, rewrite the architecture or merge automatically.

Official setup reference (checked 2026-10-13):
https://code.claude.com/docs/en/web-quickstart
