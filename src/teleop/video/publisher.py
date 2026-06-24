"""Follower-side WebRTC video publisher.

Publishes the global + wrist camera tracks to viewers (leader UI / browser) via
the cloud signaling server. Implements the spec's video requirements:
* Multiple simultaneous streams (one RTCPeerConnection per viewer, N tracks).
* Automatic reconnection to the signaling server with exponential backoff.
* Graceful teardown on peer-left.

aiortc + PyAV are optional deps (``pip install -e '.[video]'``); this module
imports without them so the rest of the package is unaffected.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Dict, Optional

from .camera import CameraConfig, make_camera

log = logging.getLogger(__name__)

try:
    import av  # type: ignore
    from aiortc import (  # type: ignore
        RTCPeerConnection, RTCConfiguration, RTCIceServer,
        RTCSessionDescription, VideoStreamTrack,
    )
    import websockets  # type: ignore
    _HAVE_WEBRTC = True
except Exception:  # pragma: no cover - optional deps
    _HAVE_WEBRTC = False


if _HAVE_WEBRTC:

    class CameraTrack(VideoStreamTrack):
        """Wraps a camera source as a WebRTC video track at the configured FPS."""

        def __init__(self, cfg: CameraConfig) -> None:
            super().__init__()
            self.cfg = cfg
            self.cam = make_camera(cfg)

        async def recv(self):
            pts, time_base = await self.next_timestamp()
            frame_ndarray = self.cam.read()
            frame = av.VideoFrame.from_ndarray(frame_ndarray, format="bgr24")
            frame.pts = pts
            frame.time_base = time_base
            return frame

        def stop(self) -> None:  # type: ignore[override]
            super().stop()
            self.cam.close()


def _quiet_ice_teardown(loop, context: dict) -> None:
    """Swallow the harmless 'NoneType has no attribute sendto/call_exception_handler'
    raised by aioice STUN retransmit timers after a peer connection closes; pass
    everything else to the default handler."""
    exc = context.get("exception")
    text = f"{context.get('message', '')} {exc}"
    if isinstance(exc, AttributeError) and (
        "sendto" in text or "call_exception_handler" in text
    ):
        return
    loop.default_exception_handler(context)


class VideoPublisher:
    """Connects to the signaling server as a 'follower' and answers viewer
    offers with the camera tracks. One instance serves all viewers."""

    def __init__(self, signaling_url: str, session_id: str,
                 peer_id: str = "follower-video",
                 global_cfg: Optional[CameraConfig] = None,
                 wrist_cfg: Optional[CameraConfig] = None) -> None:
        if not _HAVE_WEBRTC:
            raise RuntimeError(
                "WebRTC deps missing. Install with: pip install -e '.[video]' "
                "(aiortc, av, websockets)."
            )
        self.url = signaling_url.rstrip("/") + f"/ws/{session_id}/{peer_id}"
        self.peer_id = peer_id
        self.global_cfg = global_cfg or CameraConfig("global", 1280, 720, 30)
        self.wrist_cfg = wrist_cfg or CameraConfig("wrist", 640, 480, 30)
        self._pcs: Dict[str, "RTCPeerConnection"] = {}
        self._ice_servers: list = []
        self._stop = False
        # Each camera is opened exactly once and fanned out to every viewer via
        # a MediaRelay — avoids reopening a busy /dev/videoN per connection.
        self._relay = None
        self._global_src = None
        self._wrist_src = None

    def _ensure_sources(self) -> None:
        if self._relay is None:
            from aiortc.contrib.media import MediaRelay  # type: ignore
            self._relay = MediaRelay()
            self._global_src = CameraTrack(self.global_cfg)
            self._wrist_src = CameraTrack(self.wrist_cfg)
            log.info("camera sources opened (global=%s, wrist=%s)",
                     self.global_cfg.device, self.wrist_cfg.device)

    async def run(self) -> None:
        # aioice schedules STUN retransmits that can fire after a peer's
        # transport is torn down, raising a harmless 'NoneType has no attribute
        # sendto' from a timer callback. Swallow exactly that noise.
        try:
            asyncio.get_running_loop().set_exception_handler(_quiet_ice_teardown)
        except RuntimeError:
            pass
        backoff = 1.0
        while not self._stop:
            try:
                await self._session()
                backoff = 1.0  # reset after a clean session
            except Exception:
                log.exception("publisher session error; reconnecting in %.1fs", backoff)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30.0)  # exp. backoff per spec

    async def _session(self) -> None:
        async with websockets.connect(self.url) as ws:
            await ws.send(json.dumps({"type": "join", "role": "follower"}))
            log.info("video publisher joined session at %s", self.url)
            async for raw in ws:
                msg = json.loads(raw)
                await self._handle(ws, msg)

    async def _handle(self, ws, msg: dict) -> None:
        mtype = msg.get("type")
        if mtype == "joined":
            self._ice_servers = msg.get("iceServers", [])
        elif mtype == "offer":
            await self._on_offer(ws, msg)
        elif mtype == "candidate":
            pc = self._pcs.get(msg.get("from"))
            if pc and msg.get("candidate"):
                from aiortc.sdp import candidate_from_sdp  # type: ignore
                cand = candidate_from_sdp(msg["candidate"]["candidate"])
                cand.sdpMid = msg["candidate"].get("sdpMid")
                cand.sdpMLineIndex = msg["candidate"].get("sdpMLineIndex")
                await pc.addIceCandidate(cand)
        elif mtype == "peer-left":
            pc = self._pcs.pop(msg.get("peer_id"), None)
            if pc:
                await pc.close()

    async def _on_offer(self, ws, msg: dict) -> None:
        viewer = msg["from"]
        config = RTCConfiguration([
            RTCIceServer(**s) for s in (self._ice_servers or
                                        [{"urls": "stun:stun.l.google.com:19302"}])
        ])
        pc = RTCPeerConnection(config)
        self._pcs[viewer] = pc
        self._ensure_sources()
        # Subscribe each viewer to the shared camera sources (one open device,
        # many viewers) instead of opening the camera per connection.
        pc.addTrack(self._relay.subscribe(self._global_src))
        pc.addTrack(self._relay.subscribe(self._wrist_src))

        @pc.on("connectionstatechange")
        async def _on_state() -> None:
            log.info("viewer %s connection: %s", viewer, pc.connectionState)
            if pc.connectionState in ("failed", "closed"):
                self._pcs.pop(viewer, None)

        await pc.setRemoteDescription(
            RTCSessionDescription(sdp=msg["sdp"], type="offer"))
        answer = await pc.createAnswer()
        await pc.setLocalDescription(answer)
        await ws.send(json.dumps({
            "type": "answer", "to": viewer,
            "sdp": pc.localDescription.sdp,
        }))

    async def close(self) -> None:
        self._stop = True
        for pc in list(self._pcs.values()):
            await pc.close()
        self._pcs.clear()
