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
import secrets
from typing import Any

from app.providers.media_base import ImageProvider, ImageResult
from app.providers.media_http import (
    MediaProviderError,
    MediaProviderNotConfigured,
    png_dimensions,
    request,
    retrying,
)

HOST = "api.openai.com"
DEFAULT_MODEL = "gpt-image-1"

#: The vertical sizes the Images API accepts. A short is 9:16, and the nearest supported shape
#: is 1024x1536; the assembler scales to 1080x1920 rather than the adapter claiming a size the
#: API never produced.
PORTRAIT_SIZE = "1024x1536"
SQUARE_SIZE = "1024x1024"

#: The Images API draws from words at `/v1/images/generations` and from a picture it is given
#: at `/v1/images/edits`, which is multipart and takes the reference as a file part. A
#: character's reference sheet goes to the second, so the face in the shot is the face the
#: Owner approved instead of a fresh invention every scene.
EDITS_PATH = "/v1/images/edits"
GENERATIONS_PATH = "/v1/images/generations"


def _multipart(
    fields: dict[str, str], files: list[tuple[str, str, str, bytes]]
) -> tuple[bytes, str]:
    """A multipart/form-data body and its content type, built without a dependency.

    `files` is (field name, filename, content type, bytes). The boundary is random so it
    cannot occur inside a picture by accident, which is the one way a body like this breaks.
    """
    boundary = f"----studio{secrets.token_hex(16)}"
    marker = f"--{boundary}".encode()
    parts: list[bytes] = []
    for name, value in fields.items():
        parts.append(
            marker
            + b"\r\n"
            + f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode()
            + str(value).encode("utf-8")
            + b"\r\n"
        )
    for name, filename, content_type, payload in files:
        parts.append(
            marker
            + b"\r\n"
            + f'Content-Disposition: form-data; name="{name}"; filename="{filename}"\r\n'.encode()
            + f"Content-Type: {content_type}\r\n\r\n".encode()
            + payload
            + b"\r\n"
        )
    parts.append(marker + b"--\r\n")
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


def _reference_bytes(extra: dict[str, Any] | None) -> tuple[bytes, str] | None:
    """The reference picture the caller handed over, as bytes and a media type.

    A path, an asset id or a description is refused here rather than posted as a form field:
    the vendor would answer 400 for a whole film, and the studio would have told the Owner it
    was drawing from the character's reference while it was drawing from nothing.
    """
    reference = (extra or {}).get("reference_image")
    if not reference:
        return None
    if not isinstance(reference, dict):
        raise MediaProviderError("The reference image must be given as bytes, not as a name")
    payload = reference.get("bytes")
    if not isinstance(payload, bytes | bytearray) or not payload:
        raise MediaProviderError("The reference image must be given as bytes, not as a name")
    mime = reference.get("mime_type")
    return bytes(payload), mime if isinstance(mime, str) and mime.startswith(
        "image/"
    ) else "image/png"


class OpenAIImageAdapter(ImageProvider):
    PROVIDER_NAME = "OPENAI_IMAGES"
    ADAPTER_VERSION = "1.1.0"

    #: This adapter implements the documented edits endpoint, so the studio may hand it a
    #: character's reference sheet. It is a statement about the code, not about the account:
    #: `REFERENCE_IMAGE_VERIFIED` stays False until an Owner-approved run has actually drawn
    #: a scene this way, because no test may spend a credit to find out.
    ACCEPTS_REFERENCE_IMAGE = True
    REFERENCE_IMAGE_VERIFIED = False

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
                retrying, request, HOST, "GET", f"/v1/models/{self.model}", self._headers()
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

        reference = _reference_bytes(extra)
        size = PORTRAIT_SIZE if height > width else SQUARE_SIZE
        if reference is None:
            path = GENERATIONS_PATH
            headers = self._headers()
            payload = json.dumps(
                {"model": self.model, "prompt": described[:4000], "size": size, "n": 1}
            ).encode("utf-8")
        else:
            # The picture the character already is, handed back as the thing to work from.
            reference_bytes, mime = reference
            path = EDITS_PATH
            payload, content_type = _multipart(
                {"model": self.model, "prompt": described[:4000], "size": size, "n": "1"},
                [("image[]", f"reference.{mime.split('/')[-1]}", mime, reference_bytes)],
            )
            headers = {**self._headers(), "Content-Type": content_type}

        data, _, _ = await asyncio.to_thread(
            retrying, request, HOST, "POST", path, headers, payload
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
                "requested_size": size,
                "endpoint": path,
                # How many references this still was actually drawn from, so a render's record
                # says whether the character's face came from its sheet or from the words.
                "reference_images": 0 if reference is None else 1,
                "bytes": len(image_bytes),
            },
        )
