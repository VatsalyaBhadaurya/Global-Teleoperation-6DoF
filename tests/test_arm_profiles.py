"""Arm-profile + driver-registry tests — the plug-and-play arm layer."""
from teleop.core import SystemConfig, ArmProfile, GripperSpec
from teleop.drivers import ARM_DRIVERS, make_arm, register_driver
from teleop.follower import FollowerController
from teleop.transport import make_transport


def test_builtin_profiles_load():
    for name in ("mock", "so100", "piper"):
        p = ArmProfile.load(name)
        assert p.name == name
        assert p.dof == 6
        assert p.driver in ARM_DRIVERS


def test_unknown_profile_falls_back_to_mock():
    p = ArmProfile.load("does-not-exist")
    assert p.name == "mock"
    assert p.driver == "mock"


def test_apply_profile_overrides_limits_and_dof():
    cfg = SystemConfig()
    cfg.apply_arm_profile(ArmProfile.load("piper"))
    assert cfg.arm.name == "piper"
    assert cfg.dof == 6
    # Profile limits overlay the live config.
    assert cfg.joint_limits.soft_lower == cfg.arm.joint_limits["soft_lower"]
    assert "joint1" in cfg.arm.joint_names


def test_gripper_stroke_mapping():
    g = GripperSpec(type="stroke", range=[0.0, 0.07])
    assert g.to_hardware(0.0) == 0.0
    assert abs(g.to_hardware(0.5) - 0.035) < 1e-9
    assert abs(g.to_hardware(1.0) - 0.07) < 1e-9
    # Clamps out-of-range commands.
    assert g.to_hardware(2.0) == 0.07
    assert g.to_hardware(-1.0) == 0.0


def test_make_arm_defaults_to_mockarm():
    cfg = SystemConfig()
    arm = make_arm(cfg)
    assert type(arm).__name__ == "MockArm"


def test_unknown_driver_falls_back_to_mock():
    cfg = SystemConfig()
    cfg.arm.driver = "nonsense"
    arm = make_arm(cfg)
    assert type(arm).__name__ == "MockArm"


def test_register_custom_driver():
    cfg = SystemConfig()
    sentinel = object()

    class FakeArm:
        def __init__(self, c):
            self.c = c

    register_driver("fake", lambda c: FakeArm(c))
    cfg.arm.driver = "fake"
    arm = make_arm(cfg)
    assert isinstance(arm, FakeArm)
    ARM_DRIVERS.pop("fake", None)


def test_controller_builds_arm_from_profile():
    cfg = SystemConfig()
    cfg.apply_arm_profile(ArmProfile.load("piper"))
    tx = make_transport(cfg, peer_id="test-follower")
    ctl = FollowerController(cfg, tx)
    # piper profile uses the mock driver -> still a kinematic sim arm.
    assert type(ctl.arm).__name__ == "MockArm"
    ctl.stop()
    tx.close()
