"""Launch a leader or follower bridge.

    ros2 launch teleop_bridge teleop_bridge.launch.py side:=follower \\
        zenoh_endpoint:=tcp/router.example.com:7447 session_id:=default
"""
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description() -> LaunchDescription:
    side = LaunchConfiguration("side")
    endpoint = LaunchConfiguration("zenoh_endpoint")
    session = LaunchConfiguration("session_id")

    return LaunchDescription([
        DeclareLaunchArgument("side", default_value="follower",
                              description="leader | follower"),
        DeclareLaunchArgument("zenoh_endpoint", default_value=""),
        DeclareLaunchArgument("session_id", default_value="default"),
        Node(
            package="teleop_bridge",
            executable=[side, "_bridge"],
            name=[side, "_bridge"],
            output="screen",
            parameters=[{"zenoh_endpoint": endpoint, "session_id": session}],
        ),
    ])
