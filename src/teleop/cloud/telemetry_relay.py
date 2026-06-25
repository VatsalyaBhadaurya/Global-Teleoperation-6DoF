"""Operator-feed publisher.

Pushes the *real* robot state, *real* measured network telemetry, and the
supervisor advisories derived from them to operator UIs over the signaling
WebSocket. This is the light status path (small JSON), kept separate from the
heavy WebRTC media path.

There is no synthetic/demo data here: the caller injects ``state_provider`` and
``telemetry_provider`` callables that read the live system (e.g. the leader's
last received follower state and the NetworkMonitor's measured RTT). If a
provider returns ``None`` that field is simply omitted.

Runs as an asyncio task and reconnects automatically.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Callable, Optional

from ..core import SystemConfig, NetworkTelemetry, RobotState
from ..agent import Supervisor

log = logging.getLogger(__name__)

StateProvider = Callable[[], Optional[RobotState]]
TelemetryProvider = Callable[[], Optional[NetworkTelemetry]]


class TelemetryRelay:
    def __init__(self, signaling_url: str, session_id: str,
                 state_provider: StateProvider,
                 telemetry_provider: TelemetryProvider,
                 config: Optional[SystemConfig] = None,
                 supervisor: Optional[Supervisor] = None,
                 peer_id: str = "operator-feed", role: str = "viewer",
                 rate_hz: float = 10.0) -> None:
        url = signaling_url.replace("https://", "wss://").replace("http://", "ws://")
        self.url = url.rstrip("/") + f"/ws/{session_id}/{peer_id}"
        self.role = role
        self.cfg = config or SystemConfig.load()
        self.supervisor = supervisor or Supervisor.from_config(self.cfg)
        self.state_provider = state_provider
        self.telemetry_provider = telemetry_provider
        self.period = 1.0 / rate_hz
        agent = getattr(self.cfg, "agent", None)
        self._guidance_enabled = bool(getattr(agent, "guidance_enabled", False))
        ghz = float(getattr(agent, "guidance_rate_hz", 0.5) or 0.5)
        self._guidance_period = 1.0 / max(ghz, 0.05)
        self._last_guidance = ""   # last LLM line sent (only re-sent on change)
        self._stop = False

    async def run(self) -> None:
        import websockets
        backoff = 1.0
        while not self._stop:
            try:
                async with websockets.connect(self.url) as ws:
                    await ws.send(json.dumps({"type": "join", "role": self.role}))
                    log.info("operator feed connected: %s", self.url)
                    backoff = 1.0
                    self._last_guidance = ""  # force a fresh guidance push
                    # The LLM guidance call can block (Ollama HTTP); run it on a
                    # slow background task off the event loop so the 10 Hz feed
                    # never stalls. Both tasks send on the same ws, but never
                    # concurrently (guidance awaits in run_in_executor, then a
                    # single send) — safe for the websockets client.
                    guidance_task = asyncio.ensure_future(self._guidance_loop(ws))
                    try:
                        while not self._stop:
                            await self._broadcast(ws)
                            await asyncio.sleep(self.period)
                    finally:
                        guidance_task.cancel()
            except Exception:
                if self._stop:
                    break
                log.warning("operator feed reconnecting in %.1fs", backoff)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 15.0)

    async def _broadcast(self, ws) -> None:
        state = self.state_provider()
        tele = self.telemetry_provider()
        advisories = self.supervisor.supervise(state, tele)
        if state is not None:
            await ws.send(json.dumps({"type": "state", "state": state.to_dict()}))
        if tele is not None:
            await ws.send(json.dumps({"type": "telemetry", "telemetry": tele.to_dict()}))
        await ws.send(json.dumps({
            "type": "advisory",
            "advisories": [
                {"severity": a.severity.name, "category": a.category, "message": a.message}
                for a in advisories
            ],
        }))

    async def _guidance_loop(self, ws) -> None:
        """Recompute the LLM operator guidance at a slow rate, off the event
        loop, and push it only when the text changes."""
        if not self._guidance_enabled:
            return
        loop = asyncio.get_running_loop()
        while not self._stop:
            try:
                state = self.state_provider()
                tele = self.telemetry_provider()
                # Blocking for the Ollama backend — keep it off the event loop.
                text = await loop.run_in_executor(
                    None, self.supervisor.guidance, state, tele)
                text = (text or "").strip()
                if text and text != self._last_guidance:
                    self._last_guidance = text
                    await ws.send(json.dumps({"type": "guidance", "text": text}))
            except asyncio.CancelledError:
                raise
            except Exception:
                log.debug("guidance update failed; will retry", exc_info=True)
            await asyncio.sleep(self._guidance_period)

    def stop(self) -> None:
        self._stop = True
