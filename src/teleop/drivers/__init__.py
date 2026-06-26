"""Pluggable arm drivers — the plug-and-play arm layer.

``make_arm(config)`` returns a ready driver for the selected ``ArmProfile``;
``ArmDriver`` is the contract every driver satisfies. The ROS2 driver is loaded
lazily by the registry so importing this package never requires rclpy.
"""
from .base import ArmDriver
from .registry import ARM_DRIVERS, make_arm, register_driver

__all__ = ["ArmDriver", "ARM_DRIVERS", "make_arm", "register_driver"]
