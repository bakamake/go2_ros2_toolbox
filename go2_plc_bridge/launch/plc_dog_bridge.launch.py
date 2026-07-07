from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from ament_index_python.packages import get_package_share_directory
import os


def generate_launch_description():
    pkg = get_package_share_directory('go2_plc_bridge')
    default_cfg = os.path.join(pkg, 'config', 'plc_dog_bridge.yaml')

    cfg_arg = DeclareLaunchArgument(
        'config_file', default_value=default_cfg,
        description='Path to plc_dog_bridge.yaml')
    use_plc_arg = DeclareLaunchArgument(
        'use_plc', default_value='true',
        description='Read PLC I128.0 via snap7; if false, no hardware required')
    use_ssh_arg = DeclareLaunchArgument(
        'use_ssh', default_value='true',
        description='Actually run SSH commands; if false, dry-run mode')
    trigger_once_arg = DeclareLaunchArgument(
        'trigger_once', default_value='false',
        description='Fire stand->sit cycle once at startup (for dev)')

    node = Node(
        package='go2_plc_bridge',
        executable='plc_dog_bridge',
        name='plc_dog_bridge',
        output='screen',
        parameters=[{
            'config_file': LaunchConfiguration('config_file'),
            'use_plc': LaunchConfiguration('use_plc'),
            'use_ssh': LaunchConfiguration('use_ssh'),
            'trigger_once': LaunchConfiguration('trigger_once'),
        }],
    )

    return LaunchDescription([cfg_arg, use_plc_arg, use_ssh_arg, trigger_once_arg, node])
