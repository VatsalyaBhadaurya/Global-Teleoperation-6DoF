"""System configuration with safe defaults.

Loaded from ``config/system.yaml`` if present, else from these defaults. No
hardcoded IPs or network-specific assumptions live in code — everything that
varies by deployment is here, per the spec's "avoid hardcoded IPs" rule.
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from .types import DOF

log = logging.getLogger(__name__)

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
class GripperSpec:
    """How this arm's gripper maps to/from our normalized 0..1 command.

    ``normalized`` arms take the command as-is (0 = open, 1 = closed). ``stroke``
    arms expect a physical opening, so the driver linearly maps 0..1 onto
    ``range`` (e.g. metres of jaw travel) before sending it to the hardware.
    """
    type: str = "normalized"                 # "normalized" | "stroke"
    range: List[float] = field(default_factory=lambda: [0.0, 1.0])

    def to_hardware(self, normalized: float) -> float:
        lo, hi = (self.range + [0.0, 1.0])[:2]
        n = max(0.0, min(1.0, normalized))
        return lo + n * (hi - lo)


@dataclass
class ArmProfile:
    """A self-contained description of one physical (or simulated) arm.

    This is the unit of plug-and-play: a non-developer selects an arm by name
    (``--arm piper``) or drops in their own ``config/arms/<name>.yaml`` and the
    whole stack — limits, joint names, gripper mapping, kinematics, and which
    driver to load — is configured from it without touching code.
    """
    name: str = "mock"
    dof: int = DOF
    driver: str = "mock"                     # key into the ArmDriver registry
    joint_names: List[str] = field(
        default_factory=lambda: [f"joint{i}" for i in range(DOF)])
    # Planar-FK link lengths (m) used for workspace checks in the sim driver.
    link_lengths: List[float] = field(
        default_factory=lambda: [0.0, 0.20, 0.20, 0.10, 0.05, 0.05])
    gripper: GripperSpec = field(default_factory=GripperSpec)
    # Free-form per-driver options (ROS topics, CAN bus, etc.).
    options: Dict[str, Any] = field(default_factory=dict)
    # Raw limit/workspace blocks merged into SystemConfig when the profile is
    # applied — kept as dicts so a profile YAML can override any subset.
    joint_limits: Dict[str, Any] = field(default_factory=dict)
    workspace: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def load(cls, name_or_path: str, search_dir: Optional[str] = None) -> "ArmProfile":
        """Load a profile by bare name (``piper``) or explicit path.

        Bare names resolve to ``config/arms/<name>.yaml``. An unknown name (or
        missing yaml) falls back to the built-in mock profile so the system
        always starts.
        """
        prof = cls()
        if not name_or_path:
            return prof
        path = Path(name_or_path)
        if path.suffix.lower() not in (".yaml", ".yml") or not path.exists():
            base = Path(search_dir) if search_dir else (
                Path(__file__).resolve().parents[3] / "config" / "arms")
            path = base / f"{name_or_path}.yaml"
        if yaml is None or not path.exists():
            log.warning("arm profile %r not found (%s); using built-in mock profile",
                        name_or_path, path)
            return prof
        data = yaml.safe_load(path.read_text()) or {}
        for key in ("name", "dof", "driver", "joint_names", "link_lengths",
                    "options", "joint_limits", "workspace"):
            if key in data:
                setattr(prof, key, data[key])
        if "gripper" in data and isinstance(data["gripper"], dict):
            for k, v in data["gripper"].items():
                setattr(prof.gripper, k, v)
        log.info("Loaded arm profile %r (driver=%s, dof=%d) from %s",
                 prof.name, prof.driver, prof.dof, path)
        return prof


@dataclass
class SystemConfig:
    control_hz: float = 100.0
    dof: int = DOF
    joint_limits: JointLimits = field(default_factory=JointLimits)
    workspace: WorkspaceLimits = field(default_factory=WorkspaceLimits)
    network: NetworkThresholds = field(default_factory=NetworkThresholds)
    agent: AgentConfig = field(default_factory=AgentConfig)
    arm: ArmProfile = field(default_factory=ArmProfile)
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
        # An arm may be selected straight from system.yaml (``arm: piper``) so a
        # deployment can be fully described by one file with no CLI flags.
        if data.get("arm"):
            cfg.apply_arm_profile(ArmProfile.load(str(data["arm"])))
        return cfg

    def apply_arm_profile(self, profile: "ArmProfile") -> None:
        """Fold an :class:`ArmProfile` into this config.

        Pulls dof/joint-limit/workspace numbers out of the profile and overlays
        them on the live config, then stores the profile so the driver factory,
        the follower bridge (joint names), and the FK (link lengths) can read it.
        Only fields the profile actually specifies are overridden.
        """
        self.arm = profile
        self.dof = profile.dof
        for k, v in (profile.joint_limits or {}).items():
            if hasattr(self.joint_limits, k):
                setattr(self.joint_limits, k, v)
        for k, v in (profile.workspace or {}).items():
            if hasattr(self.workspace, k):
                setattr(self.workspace, k, v)
