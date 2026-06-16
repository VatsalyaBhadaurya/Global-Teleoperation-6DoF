# Global Teleoperation — 6DoF Leader/Follower

A real-time leader–follower teleoperation platform for a 6DOF robotic arm where the
leader and follower may be anywhere in the world, on different networks, communicating
over the public internet.

This repo follows the specification in [`ctx.txt`](ctx.txt). It is built as a monorepo
with a **runnable, hardware-free vertical slice** at its core (so you can develop and
test the full control/safety/recording pipeline on any machine, including Windows,
without ROS2 or a physical arm), plus the production transport/video/UI layers that the
spec requires layered on top.

## Architecture

```
 Leader Station                Cloud Layer                 Follower Station
 ┌────────────────┐            ┌──────────────┐            ┌────────────────────┐
 │ Leader arm     │            │ Signaling    │            │ Follower controller│
 │ Teleop node    │  commands  │  server      │  commands  │ Safety controller  │
 │ Video viewer   │──ROS2/────▶│ Zenoh router │──Zenoh────▶│ Robot / MuJoCo sim │
 │ Session mgr    │  Zenoh     │ Session reg. │            │ Camera manager     │
 │                │◀──feedback─│              │◀──feedback─│ WebRTC publisher   │
 │ Video viewer   │◀═WebRTC════╪══════════════╪══video═════│ Data recorder      │
 └────────────────┘            └──────────────┘            └────────────────────┘
```

### Packages (`src/teleop`)

| Package      | Responsibility                                                        |
|--------------|-----------------------------------------------------------------------|
| `core`       | Shared dataclasses: joint state, EE pose, gripper, commands, telemetry |
| `transport`  | Pluggable transport: in-process (testing), Zenoh (production)          |
| `sim`        | Kinematic 6DOF mock arm (drop-in for MuJoCo/Isaac/real hardware)       |
| `follower`   | Robot controller + independent safety controller + watchdogs          |
| `leader`     | Teleop node: reads leader joints, publishes commands, holds session    |
| `network`    | Latency / packet-loss / stream telemetry monitor                      |
| `recording`  | Synchronized demonstration recorder (Parquet / HDF5 / LeRobot)         |
| `agent`      | RO-SLM teleoperation supervisor (deterministic safety rules + LLM)     |

## Quick start (hardware-free demo)

```bash
python -m pip install -e .
python scripts/run_demo.py        # runs leader→transport→follower→safety→sim loop
pytest -q                          # unit tests for safety + supervisor
```

## Status

- [x] Shared core types & config
- [x] Pluggable transport (in-process) + Zenoh backend
- [x] Mock 6DOF arm sim
- [x] Follower controller + safety controller (joint/workspace/watchdog/E-stop)
- [x] Leader teleop node
- [x] Network monitor
- [x] Data recorder (Parquet)
- [x] RO-SLM supervisor (deterministic safety rule engine + pluggable LLM)
- [ ] ROS2 Humble packages (`docker/ros2`)
- [ ] WebRTC video pipeline + signaling server (FastAPI)
- [ ] React/Next.js operator UI

See `ctx.txt` for the full specification.
