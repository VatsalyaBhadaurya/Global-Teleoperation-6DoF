"""Standalone leader node for multi-machine deployment.

Publishes teleoperation commands to the remote follower over Zenoh through a
cloud router, and prints follower feedback. No ROS2 required.

    # Procedural demo motion (no hardware):
    python scripts/run_leader.py --endpoint tcp/ROUTER_HOST:7447 --session demo

    # Keyboard jog (interactive):
    python scripts/run_leader.py --endpoint tcp/ROUTER_HOST:7447 --source keyboard

Replace the target source with a real leader-arm driver / SpaceMouse / VR
controller for production teleoperation.
"""
from __future__ import annotations

import argparse
import logging
import math
import time
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from teleop.core import SystemConfig
from teleop.transport import make_transport
from teleop.leader import LeaderNode


def procedural_source():
    """Smooth sinusoidal sweep on joints 0 and 1; gripper cycles."""
    def src(t: float):
        return ([0.6 * math.sin(0.8 * t), 0.4 * math.sin(0.5 * t), 0, 0, 0, 0],
                0.5 + 0.5 * math.sin(0.3 * t))
    return src


def keyboard_source(dof: int = 6):
    """Arrow-free WASDQE jog of joints 0/1/2; space toggles gripper. Requires a
    TTY. Falls back to hold if no key pressed."""
    state = {"q": [0.0] * dof, "g": 0.0}
    try:
        import threading
        last = {"key": ""}

        def reader():
            while True:
                last["key"] = sys.stdin.read(1)
        threading.Thread(target=reader, daemon=True).start()
    except Exception:
        last = {"key": ""}

    step = 0.05
    keymap = {"a": (0, +step), "d": (0, -step), "w": (1, +step),
              "s": (1, -step), "q": (2, +step), "e": (2, -step)}

    def src(_t: float):
        k = last.get("key", "")
        last["key"] = ""
        if k in keymap:
            j, dv = keymap[k]
            state["q"][j] += dv
        elif k == " ":
            state["g"] = 0.0 if state["g"] > 0.5 else 1.0
        return list(state["q"]), state["g"]
    return src


def main() -> int:
    ap = argparse.ArgumentParser(description="Teleop leader node (Zenoh)")
    ap.add_argument("--endpoint", default=os.environ.get("ZENOH_ENDPOINT", ""),
                    help="Zenoh router endpoint, e.g. tcp/1.2.3.4:7447")
    ap.add_argument("--session", default=os.environ.get("SESSION_ID", "default"))
    ap.add_argument("--transport", default="zenoh", choices=["zenoh", "inproc"])
    ap.add_argument("--source", default="procedural", choices=["procedural", "keyboard"])
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    cfg = SystemConfig.load()
    cfg.transport = args.transport
    cfg.zenoh_endpoint = args.endpoint or None
    cfg.session_id = args.session

    tx = make_transport(cfg)
    source = keyboard_source(cfg.dof) if args.source == "keyboard" else procedural_source()
    leader = LeaderNode(cfg, tx, source)
    leader.start()
    log = logging.getLogger("leader")
    log.info("Leader running (session=%s, endpoint=%s, source=%s). Ctrl-C to stop.",
             args.session, args.endpoint or "(peer discovery)", args.source)
    try:
        while True:
            time.sleep(1.0)
            st = leader.last_follower_state
            if st:
                log.info("follower q0=%+.3f q1=%+.3f status=%s",
                         st.positions[0], st.positions[1], st.status.value)
    except KeyboardInterrupt:
        pass
    finally:
        leader.stop()
        tx.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
