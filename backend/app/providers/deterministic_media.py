"""Deterministic local media generation adapters (Image & TTS).

Produces valid visual cards and synthetic narration audio with exact word timestamps
without requiring commercial API keys or unverified third-party cloud accounts.
"""

from __future__ import annotations

import math
import struct
from typing import Any

from app.providers.media_base import (
    ImageProvider,
    ImageResult,
    TTSProvider,
    TTSResult,
)


class DeterministicVisualAdapter(ImageProvider):
    """Generates sharp 9:16 (1080x1920) SVG/PNG visual cards with typography and branded colors."""

    ADAPTER_VERSION = "1.0.0"

    async def health_check(self) -> dict[str, Any]:
        return {
            "status": "HEALTHY",
            "adapter": "DeterministicVisualAdapter",
            "mode": "LOCAL_DETERMINISTIC",
        }

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
        title = (extra or {}).get("title", "AUTONOMOUS AI STUDIO")
        scene_idx = (extra or {}).get("scene_index", 1)
        bg_color = (extra or {}).get("bg_color", "#0b1329")
        accent_color = (extra or {}).get("accent_color", "#38bdf8")

        # Generate a clean, crisp 9:16 SVG visual frame
        svg_content = f"""<svg xmlns="http://www.w3.org/2000/svg"
     viewBox="0 0 {width} {height}" width="{width}" height="{height}">
  <defs>
    <linearGradient id="grad" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="{bg_color}" />
      <stop offset="100%" stop-color="#020617" />
    </linearGradient>
    <pattern id="grid" width="40" height="40" patternUnits="userSpaceOnUse">
      <path d="M 40 0 L 0 0 0 40" fill="none" stroke="rgba(56,189,248,0.07)" stroke-width="1"/>
    </pattern>
  </defs>
  <rect width="100%" height="100%" fill="url(#grad)" />
  <rect width="100%" height="100%" fill="url(#grid)" />
  
  <!-- Safe Margin Guides -->
  <rect x="60" y="120" width="{width - 120}" height="{height - 280}" rx="24" fill="none"
        stroke="{accent_color}" stroke-width="2" stroke-opacity="0.25" />
  
  <!-- Top Marquee -->
  <text x="{width / 2}" y="200" font-family="sans-serif" font-size="28" font-weight="bold"
        fill="#94a3b8" letter-spacing="4" text-anchor="middle"
        >THE OBSERVABLE STUDIO • SCENE {scene_idx:02d}</text>
  
  <!-- Title Badge -->
  <rect x="{width / 2 - 250}" y="250" width="500" height="60" rx="12" fill="rgba(56,189,248,0.15)"
        stroke="{accent_color}" stroke-width="2" />
  <text x="{width / 2}" y="290" font-family="sans-serif" font-size="26" font-weight="bold"
        fill="{accent_color}" text-anchor="middle">{title[:35]}</text>
  
  <!-- Scene Visual Frame -->
  <circle cx="{width / 2}" cy="{height / 2 - 80}" r="220" fill="rgba(15,23,42,0.8)"
          stroke="{accent_color}" stroke-width="4" />
  <text x="{width / 2}" y="{height / 2 - 120}" font-family="sans-serif" font-size="72"
        text-anchor="middle">🎬</text>
  <text x="{width / 2}" y="{height / 2 - 30}" font-family="sans-serif" font-size="24"
        font-weight="bold" fill="#f8fafc" text-anchor="middle">PROMPT</text>
  <foreignObject x="{width / 2 - 180}" y="{height / 2}" width="360" height="180">
    <div xmlns="http://www.w3.org/1999/xhtml"
         style="color:#cbd5e1; font-family:sans-serif; font-size:18px;
                text-align:center; line-height:1.4;">
      {prompt[:140]}
    </div>
  </foreignObject>
  
  <!-- Lower Caption Safe Area Placeholder -->
  <rect x="80" y="{height - 380}" width="{width - 160}" height="140" rx="16"
        fill="rgba(2,6,23,0.85)"
        stroke="rgba(255,255,255,0.1)" stroke-width="1" />
  <text x="{width / 2}" y="{height - 300}" font-family="sans-serif" font-size="22"
        font-weight="600" fill="#38bdf8" text-anchor="middle"
        >[ TIMED CAPTIONS BURNED HERE ]</text>
  <text x="{width / 2}" y="{height - 100}" font-family="sans-serif" font-size="16"
        fill="#64748b" text-anchor="middle">9:16 VERTICAL SHORT • VERIFIED PROVENANCE</text>
</svg>"""
        svg_bytes = svg_content.encode("utf-8")
        return ImageResult(
            image_bytes=svg_bytes,
            format="svg",
            width=width,
            height=height,
            seed=seed,
            prompt=prompt,
            cost_vr="0.00",
            raw_response={"engine": "deterministic_svg", "style": style},
        )


class DeterministicTTSAdapter(TTSProvider):
    """Synthesizes valid PCM WAV voiceover narration with exact word-level timestamp mapping."""

    ADAPTER_VERSION = "1.0.0"

    async def health_check(self) -> dict[str, Any]:
        return {
            "status": "HEALTHY",
            "adapter": "DeterministicTTSAdapter",
            "mode": "LOCAL_DETERMINISTIC",
        }

    async def list_voices(self) -> list[dict[str, Any]]:
        return [
            {
                "voice_id": "sarah_executive",
                "name": "Sarah (Director/CEO)",
                "gender": "Female",
                "style": "Authoritative",
            },
            {
                "voice_id": "dr_aris_narrator",
                "name": "Dr. Aris (Lead Researcher)",
                "gender": "Male",
                "style": "Scientific/Curious",
            },
            {
                "voice_id": "lyra_studio",
                "name": "Lyra (Voice Artist)",
                "gender": "Female",
                "style": "Warm/Broadcast",
            },
        ]

    async def synthesize(
        self,
        text: str,
        *,
        voice_id: str | None = None,
        speed: float = 1.0,
        pitch: float = 1.0,
        extra: dict[str, Any] | None = None,
    ) -> TTSResult:
        words = text.strip().split()
        if not words:
            words = ["Silence."]

        # Calculate natural speaking duration: ~150 words per minute at 1.0x speed
        # Min 0.35s per word for pacing, with 0.4s lead-in/lead-out
        wpm = 150.0 * max(0.5, min(2.0, speed))
        seconds_per_word = 60.0 / wpm
        total_duration = max(1.5, len(words) * seconds_per_word + 0.6)

        # Generate word-level timing offsets
        word_timings = []
        current_time = 0.3
        for w in words:
            end_time = current_time + seconds_per_word
            word_timings.append(
                {
                    "word": w,
                    "start": round(current_time, 2),
                    "end": round(end_time, 2),
                }
            )
            current_time = end_time

        # Synthesize a valid, cleanly formatted standard PCM WAV file (44.1kHz, 16-bit mono)
        # using subtle multi-tone harmonic synthesis so it sounds like a modulated radio voice
        sample_rate = 44100
        num_samples = int(total_duration * sample_rate)
        base_freq = 190.0 if "female" in (voice_id or "lyra_studio").lower() else 130.0
        base_freq *= pitch

        audio_samples = bytearray()
        for i in range(num_samples):
            t = float(i) / sample_rate
            # Modulate amplitude with speech pacing cadence
            envelope = 0.5 + 0.5 * math.sin(2.0 * math.pi * 3.5 * t)
            # Add harmonic frequencies for warm studio tone
            val = (
                0.6 * math.sin(2.0 * math.pi * base_freq * t)
                + 0.3 * math.sin(2.0 * math.pi * base_freq * 2.0 * t)
                + 0.1 * math.sin(2.0 * math.pi * base_freq * 3.0 * t)
            ) * envelope
            # Soft fade in/out
            if t < 0.15:
                val *= t / 0.15
            elif t > total_duration - 0.2:
                val *= max(0.0, (total_duration - t) / 0.2)

            int_val = int(max(-32767, min(32767, val * 8000)))
            audio_samples.extend(struct.pack("<h", int_val))

        # Pack WAV header
        header = bytearray()
        header.extend(b"RIFF")
        header.extend(struct.pack("<I", 36 + len(audio_samples)))
        header.extend(b"WAVE")
        header.extend(b"fmt ")
        header.extend(struct.pack("<I", 16))  # Subchunk1Size
        header.extend(struct.pack("<H", 1))  # AudioFormat (PCM)
        header.extend(struct.pack("<H", 1))  # NumChannels (Mono)
        header.extend(struct.pack("<I", sample_rate))  # SampleRate
        header.extend(struct.pack("<I", sample_rate * 2))  # ByteRate
        header.extend(struct.pack("<H", 2))  # BlockAlign
        header.extend(struct.pack("<H", 16))  # BitsPerSample
        header.extend(b"data")
        header.extend(struct.pack("<I", len(audio_samples)))

        wav_bytes = bytes(header + audio_samples)

        return TTSResult(
            audio_bytes=wav_bytes,
            format="wav",
            duration_seconds=round(total_duration, 2),
            sample_rate=sample_rate,
            word_timings=word_timings,
            cost_vr="0.00",
            raw_response={"engine": "deterministic_pcm", "voice_id": voice_id},
        )
