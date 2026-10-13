# Third-party notices

AMN-AI ships with, or builds into its page, the third-party components below. Each keeps its
own licence; this file gives the notice each licence asks for and says where the full text is.
A copy of this file is served with the page (`frontend/public/THIRD_PARTY_NOTICES.txt`).
Versions are the ones locked in `uv.lock` and `frontend/package-lock.json` on 2026-10-02.

## Shipped in the repository

| Component | Where | Licence | Notice |
|---|---|---|---|
| Inter (Regular, Bold) | `backend/app/media/fonts/` | SIL Open Font License 1.1 | Copyright (c) 2016 The Inter Project Authors (https://github.com/rsms/inter). Full text: `backend/app/media/fonts/OFL.txt`. |
| Oxanium | `frontend/public/fonts/oxanium/` | SIL Open Font License 1.1 | Copyright 2019 The Oxanium Project Authors (https://github.com/sevmeyer/oxanium). Full text: `frontend/public/fonts/oxanium/OFL.txt`. |
| YuNet face detector (`yunet_2023mar.onnx`) | `backend/app/media/models/` | MIT | Copyright (c) 2020 Shiqi Yu. Full text, source and SHA-256: `backend/app/media/models/LICENSE-YuNet`. (Earlier notes called it Apache-2.0, the OpenCV Zoo's own licence; the model's folder in the zoo says MIT.) |

## Built into the page (`frontend/dist`)

| Package | Version | Licence | Notice |
|---|---|---|---|
| @epicgames-ps/lib-pixelstreamingfrontend-ue5.8 | 0.1.2 | MIT | Copyright Epic Games, Inc. Loaded only when the live Unreal stream is switched on. |
| @epicgames-ps/lib-pixelstreamingcommon-ue5.8 | 0.1.0 | MIT | Copyright Epic Games, Inc. |
| @protobuf-ts/runtime | 2.11.1 | Apache-2.0 AND BSD-3-Clause | Copyright Timo Stamm. |
| sdp | 3.2.2 | MIT | Copyright (c) 2017 Philipp Hancke. |
| Tailwind CSS (generated stylesheet) | 4.x | MIT | Copyright (c) Tailwind Labs, Inc. |
| Vite (module preload helper) | 7.x | MIT | Copyright (c) 2019-present, VoidZero Inc. and Vite contributors. |

The MIT licence, for every MIT entry in this file:

> Permission is hereby granted, free of charge, to any person obtaining a copy of this software
> and associated documentation files (the "Software"), to deal in the Software without
> restriction, including without limitation the rights to use, copy, modify, merge, publish,
> distribute, sublicense, and/or sell copies of the Software, and to permit persons to whom the
> Software is furnished to do so, subject to the following conditions: The above copyright
> notice and this permission notice shall be included in all copies or substantial portions of
> the Software. THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
> IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A
> PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE
> LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR
> OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER
> DEALINGS IN THE SOFTWARE.

The Apache License 2.0 and the BSD 3-Clause licence are at
https://www.apache.org/licenses/LICENSE-2.0 and https://opensource.org/license/bsd-3-clause;
each installed package also carries its own copy under `frontend/node_modules/<package>/` or in
its Python distribution's metadata.

## Installed by `uv sync` (Python, runtime)

Not bundled in the repository; installed from PyPI by the buyer's `uv sync --locked`.

| Package | Licence | Package | Licence |
|---|---|---|---|
| alembic | MIT | pydantic, pydantic-core, pydantic-settings | MIT |
| annotated-doc, annotated-types | MIT | pycparser | BSD-3-Clause |
| anyio | MIT | python-dotenv | BSD-3-Clause |
| cffi | MIT-0 | sqlalchemy | MIT |
| click | BSD-3-Clause | starlette | BSD-3-Clause |
| colorama (Windows) | BSD-3-Clause | typing-extensions | PSF-2.0 |
| cryptography | Apache-2.0 OR BSD-3-Clause | typing-inspection | MIT |
| fastapi | MIT | tzdata | Apache-2.0 |
| greenlet | MIT AND PSF-2.0 | uvicorn | BSD-3-Clause |
| h11 | MIT | websockets | BSD-3-Clause |
| idna | BSD-3-Clause | numpy | BSD-3-Clause (and bundled 0BSD, MIT, Zlib, CC0-1.0) |
| mako, markupsafe | MIT, BSD-3-Clause | opencv-python-headless | Apache-2.0 (its wheels bundle FFmpeg libraries under the LGPL; this matters only to someone who redistributes the installed environment itself) |

Development-only tools (pytest, ruff, mypy, pillow, pytest-cov, TypeScript, Playwright) are not
part of a running studio; their licences are MIT, Apache-2.0 or HPND as published.

## Not shipped — the buyer brings them

- **FFmpeg and FFprobe** are required for films and are installed by the buyer
  (`winget install Gyan.FFmpeg`, `apt install ffmpeg`, `brew install ffmpeg`). Their licence
  (LGPL or GPL) depends on the build installed; the studio calls them as separate programs.
- **Unreal Engine, Epic's Pixel Streaming infrastructure and any Fab assets** used by the
  optional live headquarters are not part of this repository (`art-source/unreal/AMNReference/
  Content/` and `art-source/unreal/pixelstreaming/` are ignored by Git) and are governed by the
  buyer's own Epic/Fab agreements. The Unreal scripts in `art-source/` are the studio's own.
- **Music.** No track ships. `config/music_library.json` is empty; the studio mixes only tracks
  the buyer adds there with a licence that allows commercial use (`commercial_ok: true`).
- **Generated media.** Pictures, motion and voices bought from Runway, ElevenLabs or any other
  vendor are governed by the buyer's own plan with that vendor. The studio records the buyer's
  statement of commercial use on each connection (Setări) and refuses a public upload of a film
  whose components it cannot vouch for (quality control `rights_qc`, publishing `RIGHTS_GATE`).

## The studio's own marks

The AMN-AI name, logo images (`frontend/public/amn-ai-*.png`, favicons) and the employee
portraits under `Agents ID and Bible/` belong to the studio's owner and are not licensed by this
file; the release archive (`scripts/make_release.py`) leaves the portraits out.
