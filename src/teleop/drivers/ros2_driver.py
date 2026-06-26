"""ROS2 arm driver — Stage-2 scaffold for real hardware.

This is the bridge between the safety-checked follower controller and a real
arm exposed over ROS2 (AgileX Piper, an SO-100 ros2_control stack, a MoveIt
servo node, a Gazebo/Isaac sim, …). It does two things:

  * **reads** the arm's true ``/joint_states`` back, so the UI/telemetry/workspace
    checks reflect the *physical* arm instead of an open-loop guess, and
  * **writes** setpoints to the arm's command topic, with the gripper scaled
    from our normalized 0..1 into the arm's real units (e.g. Piper jaw metres).

It owns its own rclpy node + background spin thread, so it works both inside the
``follower_bridge`` ROS node and standalone from ``run_follower.py``.

PER-ARM WIRING lives entirely in the arm profile's ``options`` block — no code
edits to switch arms:

    options:
      state_topic:   /joint_states          # where the arm reports back
      command_topic: /joint_ctrl_single     # where the arm takes setpoints
      command_type:  joint_state            # joint_state | <add yours here>

What remains arm-specific and must be confirmed against the vendor driver: the
exact command **message type** and field layout. The default publishes a
``sensor_msgs/JointState`` (the common ros2_control / Piper convention); add a
branch in ``_publish`` for arms that expect a custom message.
"""
from __future__ import annotations

import logging
import threading
from typing import List, Optional

from ..core.config import SystemConfig
from ..core.types import (
    GripperState,
    RobotState,
    RobotStatus,
    now,
)
from ..sim.mock_arm import forward_kinematics

log = logging.getLogger(__name__)


class ROS2ArmDriver:
    """Drives a real arm over ROS2 and feeds its true state back.

    Falls back to holding the last commanded pose if the arm has not published
    ``/joint_states`` yet, so the follower has a valid state from tick one.
    """

    def __init__(self, config: SystemConfig) -> None:
        self.cfg = config
        arm = config.arm
        self.dof = config.dof
        self._link = arm.link_lengths
        self._gripper_spec = arm.gripper
        self._joint_names: List[str] = list(arm.joint_names)

        opts = arm.options or {}
        self._state_topic = opts.get("state_topic", "/joint_states")
        self._command_topic = opts.get("command_topic", "/joint_commands")
        self._command_type = str(opts.get("command_type", "joint_state")).lower()

        # Open-loop fallback state until the real arm reports back.
        self._cmd_pos: List[float] = [0.0] * self.dof
        self._cmd_gripper = 0.0          # normalized 0..1 (UI/telemetry units)
        self._state_pos: Optional[List[float]] = None
        self._state_vel: Optional[List[float]] = None
        self._status = RobotStatus.READY
        self._seq = 0
        self._lock = threading.Lock()

        self._node = None
        self._pub = None
        self._spin_thread: Optional[threading.Thread] = None
        self._init_ros()

    # ---- ROS plumbing -----------------------------------------------------
    def _init_ros(self) -> None:
        try:
            import rclpy
            from rclpy.node import Node
            from sensor_msgs.msg import JointState
        except Exception as exc:  # pragma: no cover - needs a ROS2 install
            raise RuntimeError(
                "ROS2ArmDriver requires a ROS2 (rclpy) environment. Source your "
                "ROS2 setup, or use the 'mock' arm for hardware-free runs."
            ) from exc

        if not rclpy.ok():
            rclpy.init()
        self._JointState = JointState
        self._node = Node("teleop_arm_driver")
        self._pub = self._node.create_publisher(JointState, self._command_topic, 10)
        self._node.create_subscription(
            JointState, self._state_topic, self._on_joint_states, 10)
        self._spin_thread = threading.Thread(
            target=self._spin, name="ros2-arm-driver", daemon=True)
        self._spin_thread.start()
        log.info("ROS2ArmDriver up: cmd->%s state<-%s (type=%s, joints=%s)",
                 self._command_topic, self._state_topic, self._command_type,
                 self._joint_names)

    def _spin(self) -> None:  # pragma: no cover - needs a ROS2 install
        import rclpy
        try:
            rclpy.spin(self._node)
        except Exception:
            log.debug("ros2 spin stopped", exc_info=True)

    def _on_joint_states(self, msg) -> None:  # pragma: no cover - needs ROS2
        # Map the incoming message by joint name when names are provided, else
        # assume the first ``dof`` entries are our joints in order.
        names = list(getattr(msg, "name", []) or [])
        pos = list(getattr(msg, "position", []) or [])
        vel = list(getattr(msg, "velocity", []) or [])
        with self._lock:
            if names and self._joint_names and all(n in names for n in self._joint_names):
                idx = [names.index(n) for n in self._joint_names]
                self._state_pos = [pos[i] if i < len(pos) else 0.0 for i in idx]
                self._state_vel = [vel[i] if i < len(vel) else 0.0 for i in idx]
            else:
                self._state_pos = pos[: self.dof] or None
                self._state_vel = (vel[: self.dof] or [0.0] * self.dof)

    def _publish(self, positions: List[float], gripper_norm: float) -> None:
        if self._pub is None:  # pragma: no cover
            return
        gripper_hw = self._gripper_spec.to_hardware(gripper_norm)
        if self._command_type == "joint_state":
            msg = self._JointState()
            msg.header.stamp = self._node.get_clock().now().to_msg()
            # Gripper rides as a trailing joint if the profile names one.
            names = list(self._joint_names[: len(positions)])
            pos = list(positions)
            if len(self._joint_names) > len(positions):
                names = list(self._joint_names)
                pos = list(positions) + [gripper_hw]
            msg.name = names
            msg.position = pos
            self._pub.publish(msg)
        else:  # pragma: no cover - add custom command types here
            raise NotImplementedError(
                f"command_type={self._command_type!r} not implemented; add a "
                "branch in ROS2ArmDriver._publish for this arm's message.")

    # ---- ArmDriver interface ---------------------------------------------
    def apply_command(self, positions: List[float], gripper: float) -> None:
        with self._lock:
            self._cmd_pos = list(positions[: self.dof])
            self._cmd_gripper = max(0.0, min(1.0, gripper))
            self._status = RobotStatus.MOVING
        self._publish(self._cmd_pos, self._cmd_gripper)

    def step(self, dt: float) -> None:
        # The real arm advances itself; nothing to integrate here. State comes
        # from the ``/joint_states`` callback. Kept for interface symmetry.
        return

    def hold(self) -> None:
        with self._lock:
            hold_pos = list(self._state_pos or self._cmd_pos)
            self._status = RobotStatus.HOLDING
        self._publish(hold_pos, self._cmd_gripper)

    def estop(self) -> None:
        self.hold()
        with self._lock:
            self._status = RobotStatus.ESTOP

    def read_state(self) -> RobotState:
        with self._lock:
            self._seq += 1
            pos = list(self._state_pos or self._cmd_pos)
            vel = list(self._state_vel or [0.0] * self.dof)
            g = self._cmd_gripper
            status = self._status
        if g < 0.1:
            gs = GripperState.OPEN
        elif g > 0.9:
            gs = GripperState.CLOSED
        else:
            gs = GripperState.MOVING
        return RobotState(
            seq=self._seq,
            stamp=now(),
            positions=pos,
            velocities=vel,
            pose=forward_kinematics(pos, self._link),
            gripper_state=gs,
            gripper_position=g,
            status=status,
        )

    def close(self) -> None:  # pragma: no cover - needs a ROS2 install
        try:
            if self._node is not None:
                self._node.destroy_node()
        except Exception:
            pass
