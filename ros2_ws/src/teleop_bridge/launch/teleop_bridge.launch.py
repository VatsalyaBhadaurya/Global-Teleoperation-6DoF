"""Launch leader bridge, follower bridge, camera bridge, or all.

    # leader only:
    ros2 launch teleop_bridge teleop_bridge.launch.py side:=leader \
        ws_url:=wss://gt6dof-signaling.onrender.com session_id:=demo

    # follower only:
    ros2 launch teleop_bridge teleop_bridge.launch.py side:=follower \
        ws_url:=wss://gt6dof-signaling.onrender.com session_id:=demo

    # follower + camera (robot side):
    ros2 launch teleop_bridge teleop_bridge.launch.py side:=follower \
        ws_url:=wss://gt6dof-signaling.onrender.com session_id:=demo \
        with_camera:=true \
        global_topic:=/camera/global/image_raw \
        wrist_topic:=/camera/wrist/image_raw

    # everything on one machine (testing):
    ros2 launch teleop_bridge teleop_bridge.launch.py side:=both \
        ws_url:=wss://gt6dof-signaling.onrender.com session_id:=demo \
        with_camera:=true
"""
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.conditions import IfCondition
from launch.substitutions import LaunchConfiguration, PythonExpression
from launch_ros.actions import Node


def generate_launch_description() -> LaunchDescription:
    side         = LaunchConfiguration("side")
    ws_url       = LaunchConfiguration("ws_url")
    session      = LaunchConfiguration("session_id")
    with_camera  = LaunchConfiguration("with_camera")
    global_topic = LaunchConfiguration("global_topic")
    wrist_topic  = LaunchConfiguration("wrist_topic")

    shared_params = [{"ws_url": ws_url, "session_id": session}]

    return LaunchDescription([
        DeclareLaunchArgument("side", default_value="both",
                              description="leader | follower | both"),
        DeclareLaunchArgument("ws_url",
                              default_value="wss://gt6dof-signaling.onrender.com"),
        DeclareLaunchArgument("session_id", default_value="demo"),
        DeclareLaunchArgument("with_camera", default_value="false",
                              description="true to also launch camera_bridge"),
        DeclareLaunchArgument("global_topic",
                              default_value="/camera/color/image_raw"),
        DeclareLaunchArgument("wrist_topic",
                              default_value="/gripper_camera/color/image_raw"),

        Node(
            package="teleop_bridge",
            executable="leader_bridge",
            name="leader_bridge",
            output="screen",
            parameters=shared_params,
            condition=IfCondition(
                PythonExpression(["'", side, "' in ('leader', 'both')"])
            ),
        ),
        Node(
            package="teleop_bridge",
            executable="follower_bridge",
            name="follower_bridge",
            output="screen",
            parameters=shared_params,
            condition=IfCondition(
                PythonExpression(["'", side, "' in ('follower', 'both')"])
            ),
        ),
        Node(
            package="teleop_bridge",
            executable="camera_bridge",
            name="camera_bridge",
            output="screen",
            parameters=[{
                "ws_url": ws_url,
                "session_id": session,
                "global_topic": global_topic,
                "wrist_topic": wrist_topic,
            }],
            condition=IfCondition(with_camera),
        ),
    ])
