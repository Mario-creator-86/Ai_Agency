"""OpenAI image generation adapter.

Uses the documented Images API at https://api.openai.com/v1/images/generations. The adapter
returns the bytes the API produced and the dimensions read out of those bytes; it does not
report the size that was requested, because a provider may return something else and the render
would then carry a measurement nobody took.
"""

from __future__ import annotations

import asyncio
import base64
import json
from typing import Any

from app.providers.media_base import ImageProvider, ImageResult
from app.providers.media_http import (
    MediaProviderError,
    MediaProviderNotConfigured,
    png_dimensions,
    request,
)

HOST = "api.openai.com"
DEFAULT_MODEL = "gpt-image-1"

#: The vertical sizes the Images API accepts. A short is 9:16, and the nearest supported shape
#: is 1024x1536; the assembler scales to 1080x1920 rather than the adapter claiming a size the
#: API never produced.
PORTRAIT_SIZE = "1024x1536"
SQUARE_SIZE = "1024x1024"


class OpenAIImageAdapter(ImageProvider):
    PROVIDER_NAME = "OPENAI_IMAGES"
    ADAPTER_VERSION = "1.0.0"

    def __init__(self, api_key: str, model: str | None = None) -> None:
        if not api_key:
            raise MediaProviderNotConfigured("OpenAI needs an API key")
        self.api_key = api_key
        self.model = model or DEFAULT_MODEL

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}

    async def health_check(self) -> dict[str, Any]:
        try:
            data, _, _ = await asyncio.to_thread(
                request, HOST, "GET", f"/v1/models/{self.model}", self._headers()
            )
        except MediaProviderError as exc:
            return {"status": "OFFLINE", "detail": str(exc)}
        if (data or {}).get("id") != self.model:
            return {"status": "OFFLINE", "detail": "The configured model is not available"}
        return {"status": "HEALTHY", "detail": ""}

    async def generate_image(
        self,
        prompt: str,
        *,
        width: int = 1080,
        height: int = 1920,
        style: str | None = None,
        seed: int | None = None,
        extra: dict[str, Any] | None = None,
    ) -> ImageResult:
        described = " ".join(str(prompt).split())
        if not described:
            raise MediaProviderError("There is no prompt to render")
        if style:
            described = f"{described}. Style: {style}"

        payload = json.dumps(
            {
                "model": self.model,
                "prompt": described[:4000],
                "size": PORTRAIT_SIZE if height > width else SQUARE_SIZE,
                "n": 1,
            }
        ).encode("utf-8")

        data, _, _ = await asyncio.to_thread(
            request, HOST, "POST", "/v1/images/generations", self._headers(), payload
        )
        items = (data or {}).get("data")
        if not isinstance(items, list) or not items:
            raise MediaProviderError("OpenAI returned no image")
        encoded = items[0].get("b64_json") if isinstance(items[0], dict) else None
        if not isinstance(encoded, str) or not encoded:
            # The adapter does not follow a URL to fetch the image: that would be a second,
            # unvalidated request to whatever host the response named.
            raise MediaProviderError("OpenAI returned no inline image data")
        try:
            image_bytes = base64.b64decode(encoded, validate=True)
        except (ValueError, TypeError) as exc:
            raise MediaProviderError("OpenAI returned image data that is not valid base64") from exc

        actual_width, actual_height = png_dimensions(image_bytes)
        return ImageResult(
            image_bytes=image_bytes,
            format="png",
            width=actual_width,
            height=actual_height,
            # The Images API accepts no seed, so none is reported rather than echoing the
            # caller's, which would suggest the render is reproducible when it is not.
            seed=None,
            prompt=described,
            raw_response={
                "provider": self.PROVIDER_NAME,
                "model": self.model,
                "requested_size": PORTRAIT_SIZE if height > width else SQUARE_SIZE,
                "bytes": len(image_bytes),
            },
        )
