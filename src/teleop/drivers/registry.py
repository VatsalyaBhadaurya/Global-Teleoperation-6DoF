"""Arm-driver registry — the plug-and-play seam.

``make_arm(config)`` reads the selected :class:`ArmProfile` and returns a ready
driver. Adding a new arm is: write one driver class, register it here, and ship
a ``config/arms/<name>.yaml`` that points ``driver:`` at it. Nothing in the
control/safety/transport stack changes.

Each entry is a factory ``callable(SystemConfig) -> ArmDriver`` so different
drivers can pull whatever they need (velocity limits, link lengths, ROS topics)
out of the config without a shared constructor signature.
"""
from __future__ import annotations

import logging
from typing import Callable, Dict

from ..core.config import SystemConfig
from ..sim.mock_arm import MockArm
from .base import ArmDriver

log = logging.getLogger(__name__)


def _make_mock(config: SystemConfig) -> ArmDriver:
    return MockArm(
        config.dof,
        config.joint_limits.max_velocity,
        link_lengths=config.arm.link_lengths,
    )


def _make_ros2(config: SystemConfig) -> ArmDriver:
    # Imported lazily so the package works on machines without ROS2/rclpy
    # installed (dev laptops, CI, the pure-python demo).
    from .ros2_driver import ROS2ArmDriver
    return ROS2ArmDriver(config)


# name -> factory. ``piper_ros`` is an alias for the generic ROS2 driver; a
# Piper just needs its own profile (topics/limits/gripper stroke), not its own
# Python class.
ARM_DRIVERS: Dict[str, Callable[[SystemConfig], ArmDriver]] = {
    "mock": _make_mock,
    "ros2": _make_ros2,
    "piper_ros": _make_ros2,
}


def register_driver(name: str, factory: Callable[[SystemConfig], ArmDriver]) -> None:
    """Register (or override) a driver factory by name (for plugins/tests)."""
    ARM_DRIVERS[name] = factory


def make_arm(config: SystemConfig) -> ArmDriver:
    """Build the arm driver named by ``config.arm.driver``.

    Unknown drivers fall back to the mock so a typo in a profile can't take the
    whole follower down — it logs loudly and keeps running in sim.
    """
    name = (getattr(config.arm, "driver", "mock") or "mock").lower()
    factory = ARM_DRIVERS.get(name)
    if factory is None:
        log.warning("unknown arm driver %r; falling back to mock. Known: %s",
                    name, ", ".join(sorted(ARM_DRIVERS)))
        factory = _make_mock
    return factory(config)
