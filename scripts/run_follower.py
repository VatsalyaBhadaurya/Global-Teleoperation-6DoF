"""Standalone follower node for multi-machine deployment.

Runs the safety-checked follower controller against the (sim) arm and connects
to the leader over Zenoh through a cloud router. No ROS2 required.

    python scripts/run_follower.py --endpoint tcp/ROUTER_HOST:7447 --session demo

Swap MockArm in FollowerController for a real hardware driver to drive a
physical follower arm.
"""
from __future__ import annotations

import argparse
import logging
import time
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from teleop.core import SystemConfig
from teleop.transport import make_transport
from teleop.follower import FollowerController


def main() -> int:
    ap = argparse.ArgumentParser(description="Teleop follower node (Zenoh)")
    ap.add_argument("--endpoint", default=os.environ.get("ZENOH_ENDPOINT", ""),
                    help="Zenoh router endpoint, e.g. tcp/1.2.3.4:7447")
    ap.add_argument("--url", default=os.environ.get("SIGNALING_URL", ""),
                    help="WebSocket server URL for --transport ws, "
                         "e.g. wss://teleop-signaling.onrender.com")
    ap.add_argument("--session", default=os.environ.get("SESSION_ID", "default"))
    ap.add_argument("--transport", default="zenoh", choices=["zenoh", "inproc", "ws"])
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    cfg = SystemConfig.load()
    cfg.transport = args.transport
    cfg.zenoh_endpoint = args.endpoint or None
    cfg.ws_url = args.url or None
    cfg.session_id = args.session

    tx = make_transport(cfg, role="follower", peer_id="follower-control")
    follower = FollowerController(cfg, tx)
    follower.start()
    log = logging.getLogger("follower")
    log.info("Follower running (session=%s, endpoint=%s). Ctrl-C to stop.",
             args.session, args.endpoint or "(peer discovery)")
    try:
        while True:
            time.sleep(2.0)
            log.info("stats: %s", follower.stats)
    except KeyboardInterrupt:
        pass
    finally:
        follower.stop()
        tx.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
