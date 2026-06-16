"""Follower-side ROS2 <-> Zenoh bridge.

Receives leader commands from Zenoh, runs them through the independent
``FollowerController`` (safety + watchdog + arm driver), and republishes the
resulting commands/state onto ROS2 follower topics so a real ros2_control /
MoveIt stack (or a sim) can execute them. Follower state is also fed back over
Zenoh to the remote leader by the controller itself.

ROS2 topics (per ctx.txt):
    sub (via Zenoh): leader commands
    pub: /follower/joint_states (sensor_msgs/JointState)
         /follower/status       (std_msgs/String)
         /follower/diagnostics  (std_msgs/String)

Run (inside ROS2 Humble):
    ros2 run teleop_bridge follower_bridge --ros-args -p zenoh_endpoint:=tcp/router:7447
"""
from __future__ import annotations

import json

import rclpy
from rclpy.node import Node
from sensor_msgs.msg import JointState
from std_msgs.msg import String

from teleop.core import SystemConfig
from teleop.transport import make_transport, KEY_FOLLOWER_STATE, KEY_FOLLOWER_STATUS, KEY_FOLLOWER_DIAG
from teleop.follower import FollowerController


class FollowerBridge(Node):
    def __init__(self) -> None:
        super().__init__("follower_bridge")
        self.declare_parameter("zenoh_endpoint", "")
        self.declare_parameter("session_id", "default")

        cfg = SystemConfig.load()
        cfg.transport = "zenoh"
        ep = self.get_parameter("zenoh_endpoint").value
        cfg.zenoh_endpoint = ep or None
        cfg.session_id = self.get_parameter("session_id").value
        self.cfg = cfg
        self.tx = make_transport(cfg)

        # Run the safety-checked controller against the (sim) arm. Swap MockArm
        # for a ros2_control hardware interface to drive a real follower.
        self.controller = FollowerController(cfg, self.tx)
        self.controller.start()

        self.pub_js = self.create_publisher(JointState, "/follower/joint_states", 10)
        self.pub_status = self.create_publisher(String, "/follower/status", 10)
        self.pub_diag = self.create_publisher(String, "/follower/diagnostics", 10)
        # Re-publish controller feedback onto ROS2 at the control rate.
        self.tx.subscribe(KEY_FOLLOWER_STATE, self._on_state)
        self.tx.subscribe(KEY_FOLLOWER_STATUS, self._on_status)
        self.tx.subscribe(KEY_FOLLOWER_DIAG, self._on_diag)
        self.get_logger().info(f"follower_bridge up (zenoh endpoint={ep!r})")

    def _on_state(self, payload: dict) -> None:
        js = JointState()
        js.header.stamp = self.get_clock().now().to_msg()
        js.name = [f"joint{i}" for i in range(len(payload.get("positions", [])))]
        js.position = list(payload.get("positions", []))
        js.velocity = list(payload.get("velocities", []))
        self.pub_js.publish(js)

    def _on_status(self, payload: dict) -> None:
        self.pub_status.publish(String(data=json.dumps(payload)))

    def _on_diag(self, payload: dict) -> None:
        self.pub_diag.publish(String(data=json.dumps(payload)))

    def destroy_node(self) -> None:
        self.controller.stop()
        self.tx.close()
        super().destroy_node()


def main() -> None:
    rclpy.init()
    node = FollowerBridge()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
