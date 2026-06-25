# Global Teleoperation — 6DoF Leader/Follower

Real-time leader–follower teleoperation for a 6DOF robotic arm. The **leader**
(human operator) and the **follower** (robot) can be anywhere in the world, on
different networks, communicating over the public internet.

- **Leader** = the human side. You jog the arm from your keyboard; commands are
  sent to the follower, and you watch the robot's real state, latency, and safety
  advisories come back.
- **Follower** = the robot side. It receives commands, runs them through an
  independent safety controller, drives the arm, and streams state + (optional)
  camera video back.
- **Cloud** = a small signaling/relay server (free to host on Render) that passes
  messages between the two so neither side needs a public IP.

Everything in the pipeline is **real** — real network, real measured latency, real
safety checks, real keyboard input. The only simulated piece is the arm itself
(`MockArm`), because there's no physical 6DOF arm attached. Swap `MockArm` in
`FollowerController` for a hardware driver and the same safety stack drives a real
robot.

---

## 1. Install (on both machines)

```bash
git clone https://github.com/<you>/Global-Teleoperation-6DoF.git
cd Global-Teleoperation-6DoF
python -m pip install -e .
```

> Always run `git pull origin main` on **both** machines before a session so the
> leader and follower are on the same code.

---

## 2. Quick local test (one machine, no internet, no cloud)

Proves the whole control → transport → safety → sim loop on a single computer:

```bash
python scripts/run_demo.py     # runs the full leader→follower→safety→sim loop
pytest -q                      # unit tests (safety, supervisor, session registry)
```

---

## 3. Run across two machines over the internet

Replace `HOST` with your signaling server host. If you deployed the included
`render.yaml`, it is your Render service, e.g. `gt6dof-signaling.onrender.com`.
Pick any shared `--session` name (here: `demo`) — the leader and follower must use
the **same** session.

### A. Follower machine (the robot side) — start this first

```bash
# Control only (simulated arm, full safety stack):
python scripts/run_follower.py --transport ws --url wss://HOST --session demo

# Control + real cameras (OpenCV device indices, e.g. 0 and 1):
python scripts/run_follower.py --transport ws --url wss://HOST --session demo \
    --video --global-cam 0 --wrist-cam 1
```

| Flag | Meaning |
|------|---------|
| `--transport ws` | use the WebSocket relay (works on free HTTP-only hosts like Render) |
| `--url wss://HOST` | the signaling server URL |
| `--session demo` | shared session name (must match the leader) |
| `--video` | also publish camera streams over WebRTC |
| `--global-cam N` | OpenCV device index of the overhead/global camera |
| `--wrist-cam N` | OpenCV device index of the wrist camera |

### B. Leader machine (the human side)

```bash
# Real keyboard teleoperation (default):
python scripts/run_leader.py --transport ws --url wss://HOST --session demo

# Hands-free scripted sweep (unattended testing, no human needed):
python scripts/run_leader.py --transport ws --url wss://HOST --session demo --source auto
```

**Keyboard controls** (the leader terminal must be focused):

| Keys | Action |
|------|--------|
| `A` / `D` | joint 0 − / + |
| `W` / `S` | joint 1 − / + |
| `Q` / `E` | joint 2 − / + |
| `R` / `F` | joint 3 − / + |
| `T` / `G` | joint 4 − / + |
| `Y` / `H` | joint 5 − / + |
| `SPACE` | toggle gripper open/closed |
| `X` | soft-stop (hold current pose) |
| `Ctrl-C` | quit |

| Flag | Meaning |
|------|---------|
| `--source keyboard` | real-time keyboard jog (default) |
| `--source auto` | scripted sweep inside the safe workspace, no human input |
| `--no-feed` | don't publish the operator feed to the UI (prints stats locally instead) |
| `--llm mock` | supervision backend: deterministic offline (default) |
| `--llm ollama` | supervision backend: Llama 3.2 1B via local Ollama (see §D) |
| `--llm-model NAME` | Ollama model name (default `llama3.2:1b`) |
| `--ollama-host URL` | Ollama server URL (default `http://localhost:11434`) |
| `--no-guidance` | turn off the natural-language guidance feed |

The leader automatically publishes the **operator feed** to the UI: the real
follower state, the **measured** round-trip latency, real packet loss, live
supervisor advisories, and a plain-English **AI guidance** line (see §D). On
`Ctrl-C` it also prints a short end-of-session summary.

### C. Operator UI (browser, optional)

```bash
cd ui
npm install
# point the UI at your signaling server:
#   PowerShell:  $env:NEXT_PUBLIC_SIGNALING_URL = "wss://HOST"
#   bash:        export NEXT_PUBLIC_SIGNALING_URL=wss://HOST
npm run dev        # open http://localhost:3000
```

The panels show your actual robot state, your real measured latency, live
advisories, and the **AI Guidance** panel (the LLM's one-line "what to do now").
If you deployed `gt6dof-ui` on Render, just open that URL instead of running it
locally. To watch a specific session, append `?session=demo` to the URL.

### D. AI supervision agent (optional LLM guidance)

The agent has **two layers**:

1. A **deterministic rule engine** (always on, no AI) that emits safety/network
   advisories: high latency → "slower movements", comms lost → "hold position",
   end-effector near the table → "lower slowly", joint near its limit, etc.
2. An **optional LLM** that turns those advisories into a single plain-English
   operator instruction, shown in the UI's **AI Guidance** panel.

The deterministic advisories work out of the box with **no model**. To enable
the natural-language layer with a real model, run [Ollama](https://ollama.com)
**on the leader machine** and pull the model once:

```bash
ollama pull llama3.2:1b           # one-time download
ollama serve                      # if not already running (http://localhost:11434)

# then start the leader with the ollama backend:
python scripts/run_leader.py --transport ws --url wss://HOST --session demo --llm ollama
```

- The LLM call is **grounded in** the deterministic rules — it can never
  contradict the safety advisories.
- It runs **off the control loop** at ~0.5 Hz, so it never slows the 10 Hz
  feed; if Ollama is unreachable it falls back to the offline backend.
- Ollama is **host-side** (your leader machine). Free cloud hosts have no GPU,
  so the default backend is `mock`. Disable the line entirely with
  `--no-guidance`.

You can also set these in `config/system.yaml` instead of CLI flags:

```yaml
agent:
  backend: ollama          # mock | ollama
  model: llama3.2:1b
  host: http://localhost:11434
  guidance_enabled: true
  guidance_rate_hz: 0.5
```

---

## 4. Run the full stack with Docker (alternative)

```bash
docker compose up zenoh signaling   # cloud layer (Zenoh router + signaling)
docker compose up follower          # follower (safety + WebRTC video)
docker compose up ui                # operator UI → http://localhost:3000
```

---

## Tips & gotchas

- **Start the follower before the leader** so it's ready to receive commands.
- **Keyboard control needs the leader terminal focused** — it reads live keypresses.
  Use `--source auto` if you want motion without a human at the keyboard.
- **Free Render hosts sleep when idle** — the first connection may take ~30s to wake.
- **Control + telemetry need no STUN/TURN.** Only the WebRTC *video* may need a TURN
  server on restrictive networks — set `TURN_URL` on the signaling service.
- All endpoints are configured via env (`STUN_URL`, `TURN_URL`, `ZENOH_ENDPOINT`,
  `SIGNALING_URL`) — nothing is hardcoded.

---

## Architecture

```
 Leader Station                Cloud Layer                 Follower Station
 ┌────────────────┐            ┌──────────────┐            ┌────────────────────┐
 │ Keyboard /     │            │ Signaling /  │            │ Follower controller│
 │ leader arm     │  commands  │  WS relay    │  commands  │ Safety controller  │
 │ Teleop node    │──ws/zenoh─▶│ Session reg. │──ws/zenoh─▶│ Robot / sim arm    │
 │ Operator feed  │◀─feedback──│              │◀─feedback──│ Camera manager     │
 │ Video viewer   │◀═WebRTC════╪══════════════╪══video═════│ WebRTC publisher   │
 └────────────────┘            └──────────────┘            └────────────────────┘
```

### Packages (`src/teleop`)

| Package      | Responsibility                                                        |
|--------------|-----------------------------------------------------------------------|
| `core`       | Shared dataclasses: joint state, EE pose, gripper, commands, telemetry |
| `transport`  | Pluggable transport: in-process (test), Zenoh (P2P), WebSocket (relay)  |
| `sim`        | Kinematic 6DOF mock arm (drop-in for MuJoCo/Isaac/real hardware)       |
| `follower`   | Robot controller + independent safety controller + watchdogs          |
| `leader`     | Teleop node: reads leader input, publishes commands, holds session     |
| `network`    | Latency / packet-loss / stream telemetry monitor (measured RTT)        |
| `recording`  | Synchronized demonstration recorder (Parquet / HDF5 / LeRobot)         |
| `agent`      | TeleOp-RO supervisor: deterministic safety rules + optional Ollama LLM, relayed to the UI as AI guidance |
| `cloud`      | FastAPI signaling server, session registry, operator-feed relay        |
| `video`      | WebRTC camera publisher (global + wrist)                               |

### How latency is measured (real, no faked numbers)

The leader stamps every outgoing command. The follower echoes the latest stamp in
its status frames. The leader's `NetworkMonitor` computes round-trip time from that
echo — so latency is a real end-to-end measurement with **no clock synchronization
required** between the two machines.

---

## Status

- [x] Shared core types & config
- [x] Pluggable transport: in-process + Zenoh (P2P) + WebSocket (free relay)
- [x] Mock 6DOF arm sim
- [x] Follower controller + safety controller (joint/workspace/watchdog/E-stop)
- [x] Leader teleop node (real keyboard input)
- [x] Network monitor (measured round-trip latency)
- [x] Data recorder (Parquet)
- [x] Supervisor (deterministic rule engine + Ollama LLM guidance, live in the UI)
- [x] ROS2 Humble bridge package (`ros2_ws/src/teleop_bridge`)
- [x] WebRTC video pipeline + FastAPI signaling server + session registry
- [x] React/Next.js operator UI (`ui/`)
- [x] Docker + Docker Compose for the full stack

See [`ctx.txt`](ctx.txt) for the full specification.

## Repository layout

```
src/teleop/         Python packages (core, transport, sim, follower, leader,
                    network, recording, agent, cloud, video)
ros2_ws/            ROS2 Humble workspace (teleop_bridge package)
ui/                 Next.js operator console
docker/             Dockerfiles + follower entrypoint
docker-compose.yml  Full-stack orchestration
render.yaml         Render Blueprint (signaling + UI, free tier)
config/system.yaml  Deployment config (limits, thresholds, endpoints)
scripts/run_demo.py     Hardware-free end-to-end demo (single machine)
scripts/run_leader.py   Leader node (keyboard teleop + operator feed)
scripts/run_follower.py Follower node (safety control + optional cameras)
tests/              Unit tests (safety, supervisor, session registry)
```
