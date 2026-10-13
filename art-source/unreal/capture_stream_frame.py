"""Experimental local Pixel Streaming receiver, without browser UI.

Not yet validated with this project's UE 5.8 Pixel Streaming 2 runtime: the
connection succeeds but no decoded video frames have arrived. Do not use this
utility as evidence that the browser stream is broken or visually validated.

uv run --no-project --with aiortc --with websockets --with pillow python
    art-source/unreal/capture_stream_frame.py --out output/visual-audit/live.png

Connects as a spectator; sends no application or keyboard commands. Dependencies
stay in uv's isolated cache, outside the application's environment.
"""

import argparse
import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path
from urllib.parse import urlparse

from aiortc import RTCConfiguration, RTCPeerConnection, RTCSessionDescription, RTCRtpReceiver
from aiortc.sdp import candidate_from_sdp
import websockets


async def capture(args):
    peer = RTCPeerConnection(RTCConfiguration(iceServers=[]))
    complete = asyncio.get_running_loop().create_future()
    consumers = []
    metadata = {"signalling": args.url, "frames_received": 0, "source": "local Unreal Pixel Streaming WebRTC"}

    async def consume(track):
        try:
            while not complete.done():
                frame = await track.recv()
                if track.kind != "video":
                    continue
                metadata["frames_received"] += 1
                if metadata["frames_received"] >= args.frames:
                    args.out.parent.mkdir(parents=True, exist_ok=True)
                    frame.to_image().save(args.out)
                    metadata.update(width=frame.width, height=frame.height, timestamp_utc=datetime.now(timezone.utc).isoformat())
                    complete.set_result(metadata)
        except Exception as exc:
            if not complete.done():
                complete.set_exception(exc)

    @peer.on("track")
    def on_track(track):
        print(f"track: {track.kind}", flush=True)
        consumers.append(asyncio.create_task(consume(track)))

    @peer.on("connectionstatechange")
    def on_connection():
        print(f"connection: {peer.connectionState}", flush=True)

    @peer.on("datachannel")
    def on_datachannel(channel):
        def start_video():
            # Epic's stream protocol: IFrameRequest=0.
            # No input events, quality ownership or application commands are sent.
            channel.send(bytes([0]))
        if channel.readyState == "open":
            start_video()
        else:
            channel.on("open", start_video)

    async def receive(ws):
        await ws.send(json.dumps({"type": "listStreamers"}))
        async for raw in ws:
            message = json.loads(raw)
            kind = message.get("type")
            print(f"signalling: {kind}", flush=True)
            if kind == "streamerList":
                ids = message.get("ids", [])
                if not ids:
                    raise RuntimeError("No Unreal streamer registered")
                selected = args.streamer or ids[0]
                if selected not in ids:
                    raise RuntimeError(f"Requested streamer unavailable: {selected}")
                metadata["streamer"] = selected
                await ws.send(json.dumps({"type": "subscribe", "streamerId": selected}))
            elif kind == "offer":
                await peer.setRemoteDescription(RTCSessionDescription(sdp=message["sdp"], type="offer"))
                for transceiver in peer.getTransceivers():
                    if transceiver.kind == "video":
                        codecs = RTCRtpReceiver.getCapabilities("video").codecs
                        transceiver.setCodecPreferences([c for c in codecs if c.mimeType.lower() in {"video/h264", "video/rtx"}])
                await peer.setLocalDescription(await peer.createAnswer())
                await ws.send(json.dumps({"type": "answer", "sdp": peer.localDescription.sdp}))
            elif kind == "iceCandidate":
                item = message.get("candidate", {})
                if item.get("candidate"):
                    candidate = candidate_from_sdp(item["candidate"].removeprefix("candidate:"))
                    candidate.sdpMid = item.get("sdpMid")
                    candidate.sdpMLineIndex = item.get("sdpMLineIndex")
                    await peer.addIceCandidate(candidate)
            elif kind == "ping":
                await ws.send(json.dumps({"type": "pong", "time": message.get("time")}))
            elif kind in {"disconnectPlayer", "subscribeFailed"}:
                raise RuntimeError(f"Stream refused: {message}")

    receiver = None
    try:
        async with websockets.connect(args.url, max_size=4 * 1024 * 1024) as ws:
            receiver = asyncio.create_task(receive(ws))
            done, _ = await asyncio.wait([complete, receiver], timeout=args.timeout, return_when=asyncio.FIRST_COMPLETED)
            if not done:
                raise TimeoutError(f"No completed frame capture after {args.timeout}s; received {metadata['frames_received']} frames")
            if complete not in done:
                await receiver
                raise RuntimeError("Signalling closed before the capture completed")
            result = complete.result()
            args.out.with_suffix('.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
            print(json.dumps(result), flush=True)
    finally:
        tasks = [*consumers, *([receiver] if receiver else [])]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await peer.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', default='ws://127.0.0.1:8890')
    parser.add_argument('--streamer')
    parser.add_argument('--out', required=True, type=Path)
    parser.add_argument('--frames', default=120, type=int)
    parser.add_argument('--timeout', default=60, type=float)
    args = parser.parse_args()
    address = urlparse(args.url)
    if address.scheme != 'ws' or address.hostname not in {'localhost', '127.0.0.1', '::1'}:
        parser.error('Only local ws:// signalling is allowed by this audit utility')
    if args.frames < 1 or not 0 < args.timeout <= 300:
        parser.error('frames must be positive and timeout must be in (0, 300]')
    asyncio.run(capture(args))


if __name__ == '__main__':
    main()
