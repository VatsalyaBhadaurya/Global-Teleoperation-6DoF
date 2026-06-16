"""Telemetry relay: pushes robot state, network telemetry, and supervisor
advisories from the follower side to operator UIs over the signaling WebSocket.

This keeps the heavy media path (WebRTC) separate from the light control/status
path: the same signaling server that brokers video also broadcasts small JSON
status frames to every viewer in the session. Runs as an asyncio task and
reconnects automatically.

    python -m teleop.cloud.telemetry_relay --signaling ws://localhost:8080
"""
from __future__ import annotations

import asyncio
import json
import logging
import math
from typing import Optional

from ..core import SystemConfig, NetworkTelemetry, RobotState, now
from ..agent import Supervisor

log = logging.getLogger(__name__)


class TelemetryRelay:
    def __init__(self, signaling_url: str, session_id: str,
                 config: Optional[SystemConfig] = None,
                 peer_id: str = "follower-telemetry", rate_hz: float = 10.0) -> None:
        self.url = signaling_url.rstrip("/") + f"/ws/{session_id}/{peer_id}"
        self.cfg = config or SystemConfig.load()
        self.supervisor = Supervisor(self.cfg)
        self.period = 1.0 / rate_hz
        self._stop = False
        # Pluggable providers; defaults produce a self-contained demo signal.
        self.state_provider = self._demo_state
        self.telemetry_provider = self._demo_telemetry
        self._t0 = now()

    # ---- demo providers (replace with real follower hooks) ----------------
    def _demo_state(self) -> RobotState:
        t = now() - self._t0
        return RobotState(
            seq=int(t * 10), stamp=now(),
            positions=[0.6 * math.sin(0.8 * t), 0.4 * math.sin(0.5 * t), 0, 0, 0, 0],
            gripper_position=0.5 + 0.5 * math.sin(0.3 * t),
        )

    def _demo_telemetry(self) -> NetworkTelemetry:
        t = now() - self._t0
        return NetworkTelemetry(
            stamp=now(),
            command_latency_ms=80 + 60 * (1 + math.sin(0.2 * t)),
            packet_loss=0.01,
            connected=True,
        )

    async def run(self) -> None:
        import websockets  # local import: optional dep
        backoff = 1.0
        while not self._stop:
            try:
                async with websockets.connect(self.url) as ws:
                    await ws.send(json.dumps({"type": "join", "role": "follower"}))
                    backoff = 1.0
                    while not self._stop:
                        await self._broadcast(ws)
                        await asyncio.sleep(self.period)
            except Exception:
                log.exception("telemetry relay error; reconnecting in %.1fs", backoff)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 15.0)

    async def _broadcast(self, ws) -> None:
        state = self.state_provider()
        tele = self.telemetry_provider()
        advisories = self.supervisor.supervise(state, tele)
        await ws.send(json.dumps({"type": "state", "state": state.to_dict()}))
        await ws.send(json.dumps({"type": "telemetry", "telemetry": tele.to_dict()}))
        await ws.send(json.dumps({
            "type": "advisory",
            "advisories": [
                {"severity": a.severity.name, "category": a.category, "message": a.message}
                for a in advisories
            ],
        }))

    def stop(self) -> None:
        self._stop = True


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser(description="Follower telemetry relay")
    ap.add_argument("--signaling", default="ws://localhost:8080")
    ap.add_argument("--session", default="default")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    relay = TelemetryRelay(args.signaling, args.session)
    try:
        asyncio.run(relay.run())
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
