"""System configuration with safe defaults.

Loaded from ``config/system.yaml`` if present, else from these defaults. No
hardcoded IPs or network-specific assumptions live in code — everything that
varies by deployment is here, per the spec's "avoid hardcoded IPs" rule.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

from .types import DOF

try:
    import yaml  # type: ignore
except Exception:  # pragma: no cover - yaml optional for the pure-python slice
    yaml = None


@dataclass
class JointLimits:
    """Per-joint soft/hard position and velocity limits (radians, rad/s)."""
    # Soft limits trigger warnings/clamping; hard limits trigger E-stop.
    soft_lower: List[float] = field(default_factory=lambda: [-2.9] * DOF)
    soft_upper: List[float] = field(default_factory=lambda: [2.9] * DOF)
    hard_lower: List[float] = field(default_factory=lambda: [-math.pi] * DOF)
    hard_upper: List[float] = field(default_factory=lambda: [math.pi] * DOF)
    max_velocity: List[float] = field(default_factory=lambda: [3.0] * DOF)


@dataclass
class WorkspaceLimits:
    """Configurable Cartesian operating volume for the end-effector (meters)."""
    x_min: float = -0.6
    x_max: float = 0.6
    y_min: float = -0.6
    y_max: float = 0.6
    z_min: float = 0.02   # keep the EE above the table surface
    z_max: float = 0.9


@dataclass
class NetworkThresholds:
    """Matches the RO-SLM network-awareness rules in ctx.txt."""
    warn_latency_ms: float = 300.0
    slow_latency_ms: float = 500.0
    max_packet_loss: float = 0.05
    command_timeout_s: float = 0.5   # watchdog: comms considered lost after this


@dataclass
class AgentConfig:
    """TeleOp-RO supervision agent settings.

    The deterministic rule engine is always on. The optional LLM layer turns the
    rule advisories into one plain-English operator instruction. ``backend`` is
    "mock" (offline, deterministic) or "ollama" (Llama 3.2 1B via a local Ollama
    server). Because an Ollama call is a blocking network request, guidance is
    recomputed off the event loop at ``guidance_rate_hz`` (slow on purpose) and
    only re-sent when the text changes — it must never stall the 10 Hz feed.
    """
    backend: str = "mock"            # "mock" | "ollama"
    model: str = "llama3.2:1b"
    host: str = "http://localhost:11434"
    guidance_enabled: bool = True
    guidance_rate_hz: float = 0.5    # how often the LLM line is recomputed


@dataclass
class SystemConfig:
    control_hz: float = 100.0
    dof: int = DOF
    joint_limits: JointLimits = field(default_factory=JointLimits)
    workspace: WorkspaceLimits = field(default_factory=WorkspaceLimits)
    network: NetworkThresholds = field(default_factory=NetworkThresholds)
    agent: AgentConfig = field(default_factory=AgentConfig)
    transport: str = "inproc"        # "inproc" | "zenoh" | "ws"
    zenoh_endpoint: Optional[str] = None  # e.g. "tcp/router.example.com:7447"
    ws_url: Optional[str] = None     # e.g. "wss://teleop-signaling.onrender.com"
    session_id: str = "default"
    recording_dir: str = "recordings"

    @classmethod
    def load(cls, path: Optional[str] = None) -> "SystemConfig":
        cfg = cls()
        path = path or str(Path(__file__).resolve().parents[3] / "config" / "system.yaml")
        if yaml is None or not Path(path).exists():
            return cfg
        data = yaml.safe_load(Path(path).read_text()) or {}
        # Shallow-merge top-level scalars; nested limit blocks override fields.
        for key in ("control_hz", "dof", "transport", "zenoh_endpoint", "ws_url",
                    "session_id", "recording_dir"):
            if key in data:
                setattr(cfg, key, data[key])
        if "network" in data:
            for k, v in data["network"].items():
                setattr(cfg.network, k, v)
        if "workspace" in data:
            for k, v in data["workspace"].items():
                setattr(cfg.workspace, k, v)
        if "joint_limits" in data:
            for k, v in data["joint_limits"].items():
                setattr(cfg.joint_limits, k, v)
        if "agent" in data:
            for k, v in data["agent"].items():
                setattr(cfg.agent, k, v)
        return cfg
