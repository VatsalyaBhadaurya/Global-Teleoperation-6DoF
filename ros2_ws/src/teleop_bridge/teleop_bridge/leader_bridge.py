"""Leader-side ROS2 <-> Zenoh bridge.

Subscribes the ROS2 leader topics produced by the leader arm driver and
republishes them onto the Zenoh transport so the (remote) follower receives
them. Mirrors follower feedback from Zenoh back onto ROS2 leader-side topics for
local visualization (RViz, diagnostics).

ROS2 topics (per ctx.txt):
    sub:  /leader/joint_states   (sensor_msgs/JointState)
          /leader/gripper        (std_msgs/Float64)
    pub:  /follower/joint_states (sensor_msgs/JointState)
          /follower/status       (std_msgs/String)

Run (inside ROS2 Humble):
    ros2 run teleop_bridge leader_bridge --ros-args -p zenoh_endpoint:=tcp/router:7447
"""
from __future__ import annotations

import json

import rclpy
from rclpy.node import Node
from sensor_msgs.msg import JointState
from std_msgs.msg import Float64, String

from teleop.core import SystemConfig, JointCommand, RobotState, now
from teleop.transport import (
    make_transport, KEY_LEADER_COMMAND, KEY_FOLLOWER_STATE, KEY_FOLLOWER_STATUS,
)


class LeaderBridge(Node):
    def __init__(self) -> None:
        super().__init__("leader_bridge")
        self.declare_parameter("zenoh_endpoint", "")
        self.declare_parameter("session_id", "default")

        cfg = SystemConfig.load()
        cfg.transport = "zenoh"
        ep = self.get_parameter("zenoh_endpoint").value
        cfg.zenoh_endpoint = ep or None
        cfg.session_id = self.get_parameter("session_id").value
        self.cfg = cfg
        self.tx = make_transport(cfg)
        self._seq = 0
        self._gripper = 0.0

        self.create_subscription(JointState, "/leader/joint_states", self._on_joints, 10)
        self.create_subscription(Float64, "/leader/gripper", self._on_gripper, 10)
        self.pub_follower = self.create_publisher(JointState, "/follower/joint_states", 10)
        self.pub_status = self.create_publisher(String, "/follower/status", 10)
        self.tx.subscribe(KEY_FOLLOWER_STATE, self._on_follower_state)
        self.tx.subscribe(KEY_FOLLOWER_STATUS, self._on_follower_status)
        self.get_logger().info(f"leader_bridge up (zenoh endpoint={ep!r})")

    def _on_gripper(self, msg: Float64) -> None:
        self._gripper = float(msg.data)

    def _on_joints(self, msg: JointState) -> None:
        self._seq += 1
        cmd = JointCommand(
            seq=self._seq, stamp=now(),
            positions=list(msg.position), velocities=list(msg.velocity),
            gripper=self._gripper,
        )
        self.tx.publish(KEY_LEADER_COMMAND, cmd.to_dict())

    def _on_follower_state(self, payload: dict) -> None:
        st = RobotState.from_dict(payload)
        js = JointState()
        js.header.stamp = self.get_clock().now().to_msg()
        js.name = [f"joint{i}" for i in range(len(st.positions))]
        js.position = list(st.positions)
        js.velocity = list(st.velocities)
        self.pub_follower.publish(js)

    def _on_follower_status(self, payload: dict) -> None:
        self.pub_status.publish(String(data=json.dumps(payload)))

    def destroy_node(self) -> None:
        self.tx.close()
        super().destroy_node()


def main() -> None:
    rclpy.init()
    node = LeaderBridge()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
