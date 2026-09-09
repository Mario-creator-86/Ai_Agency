import sys
from pathlib import Path

import uvicorn

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.config import Settings  # noqa: E402

if __name__ == "__main__":
    settings = Settings()  # type: ignore[call-arg]
    if not (ROOT / "frontend/dist/index.html").is_file():
        raise SystemExit("Build frontend first: npm run build --prefix frontend")
    uvicorn.run(
        "app.main:create_app",
        factory=True,
        host=settings.host,
        port=settings.port,
        access_log=False,
    )
