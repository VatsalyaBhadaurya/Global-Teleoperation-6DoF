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

## Running the full distributed stack

The cloud layer (Zenoh router + signaling) and follower run via Docker Compose;
the operator UI runs in the browser. Leader/follower may be on different networks.

```bash
# 1. Cloud layer (signaling + Zenoh router) — deploy on a public host
docker compose up zenoh signaling

# 2. Follower (ROS2 bridge + safety controller + WebRTC video) — at the robot
docker compose up follower

# 3. Operator UI
docker compose up ui          # then open http://localhost:3000
```

Run pieces directly without Docker:

```bash
# Signaling server
uvicorn teleop.cloud.signaling_server:app --host 0.0.0.0 --port 8080
# Follower WebRTC video publisher (synthetic cameras if none attached)
python -m teleop.video.run_publisher --signaling ws://localhost:8080 --session default
# Follower telemetry/state/advisory relay (feeds the UI panels)
python -m teleop.cloud.telemetry_relay --signaling ws://localhost:8080 --session default
# Operator UI
cd ui && npm install && npm run dev
```

ICE/TURN and Zenoh endpoints are configured via env (`STUN_URL`, `TURN_URL`,
`ZENOH_ENDPOINT`, `SIGNALING_URL`) — no hardcoded infrastructure.

## Status

- [x] Shared core types & config
- [x] Pluggable transport (in-process) + Zenoh backend
- [x] Mock 6DOF arm sim
- [x] Follower controller + safety controller (joint/workspace/watchdog/E-stop)
- [x] Leader teleop node
- [x] Network monitor
- [x] Data recorder (Parquet)
- [x] RO-SLM supervisor (deterministic safety rule engine + pluggable LLM)
- [x] ROS2 Humble bridge package (`ros2_ws/src/teleop_bridge`)
- [x] WebRTC video pipeline + FastAPI signaling server + session registry
- [x] React/Next.js operator UI (`ui/`)
- [x] Docker + Docker Compose for the full stack

See `ctx.txt` for the full specification.

## Repository layout

```
src/teleop/        Python packages (core, transport, sim, follower, leader,
                   network, recording, agent, cloud, video)
ros2_ws/           ROS2 Humble workspace (teleop_bridge package)
ui/                Next.js operator console
docker/            Dockerfiles + follower entrypoint
docker-compose.yml Full-stack orchestration
config/system.yaml Deployment configuration (limits, thresholds, endpoints)
scripts/run_demo.py Hardware-free end-to-end demo
tests/             Unit tests (safety, supervisor, session registry)
```
