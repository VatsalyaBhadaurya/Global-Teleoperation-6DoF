"""The arm-driver contract.

Everything below the follower controller talks to the arm through this small
surface. ``MockArm`` already implements it; a real arm is just another class
that satisfies the same five methods and is registered in the driver registry.
Keeping it a ``Protocol`` means existing drivers (like ``MockArm``) conform
structurally without having to import or subclass anything.
"""
from __future__ import annotations

from typing import List, Protocol, runtime_checkable

from ..core.types import RobotState


@runtime_checkable
class ArmDriver(Protocol):
    """Minimal interface the follower controller drives.

    The controller calls ``apply_command`` with a fresh setpoint, ``step`` once
    per control tick to advance the arm, and ``read_state`` to feed telemetry
    back. ``hold`` and ``estop`` are the two safe-states (comms loss / E-stop).
    """

    def apply_command(self, positions: List[float], gripper: float) -> None: ...

    def step(self, dt: float) -> None: ...

    def read_state(self) -> RobotState: ...

    def hold(self) -> None: ...

    def estop(self) -> None: ...
