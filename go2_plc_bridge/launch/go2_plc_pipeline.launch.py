from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch.conditions import IfCondition
from launch_ros.actions import Node
from ament_index_python.packages import get_package_share_directory
import os


def generate_launch_description():
    pkg = get_package_share_directory("go2_plc_bridge")
    default_cfg = os.path.join(pkg, "config", "plc_dog_bridge.yaml")

    cfg_arg = DeclareLaunchArgument(
        "config_file", default_value=default_cfg,
        description="plc_dog_bridge.yaml path")

    plc_args = DeclareLaunchArgument(
        "use_plc", default_value="true",
        description="Read PLC via snap7; false = dry-run dev mode")
    ssh_args = DeclareLaunchArgument(
        "use_ssh", default_value="true",
        description="Run SSH commands; false = dry-run dev mode")
    trigger_once_args = DeclareLaunchArgument(
        "trigger_once", default_value="false",
        description="Fire one stand->sit cycle at startup")

    enable_udp_arg = DeclareLaunchArgument(
        "enable_udp", default_value="true",
        description="Start UDP trigger + feedback forwarders")
    udp_target_ip = DeclareLaunchArgument(
        "udp_target_ip", default_value="192.168.101.10")
    udp_target_port = DeclareLaunchArgument(
        "udp_target_port", default_value="8888")
    udp_msg = DeclareLaunchArgument(
        "udp_message", default_value="Q0.0_ON_TRIGGER")

    bridge_node = Node(
        package="go2_plc_bridge",
        executable="plc_dog_bridge",
        name="plc_dog_bridge",
        output="screen",
        parameters=[{
            "config_file": LaunchConfiguration("config_file"),
            "use_plc": LaunchConfiguration("use_plc"),
            "use_ssh": LaunchConfiguration("use_ssh"),
            "trigger_once": LaunchConfiguration("trigger_once"),
        }],
    )

    udp_trigger_node = Node(
        package="go2_plc_bridge",
        executable="udp_trigger",
        name="udp_trigger",
        output="screen",
        condition=IfCondition(LaunchConfiguration("enable_udp")),
        parameters=[{
            "target_ip": LaunchConfiguration("udp_target_ip"),
            "target_port": LaunchConfiguration("udp_target_port"),
            "message": LaunchConfiguration("udp_message"),
        }],
    )

    udp_feedback_node = Node(
        package="go2_plc_bridge",
        executable="udp_feedback",
        name="udp_feedback",
        output="screen",
        condition=IfCondition(LaunchConfiguration("enable_udp")),
        parameters=[{}],
    )

    return LaunchDescription([
        cfg_arg, plc_args, ssh_args, trigger_once_args,
        enable_udp_arg, udp_target_ip, udp_target_port, udp_msg,
        bridge_node, udp_trigger_node, udp_feedback_node,
    ])
