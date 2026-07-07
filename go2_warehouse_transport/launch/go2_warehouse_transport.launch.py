"""Launch the warehouse transport TCP bridge.

It does *not* start Nav2 itself; bring up ``go2_navigation`` (which in turn
uses ``nav2_bringup``) in the same launch tree if you want a complete demo.
"""

from launch import LaunchDescription
from launch_ros.actions import Node


def generate_launch_description() -> LaunchDescription:
    ld = LaunchDescription()

    bridge_node = Node(
        package="go2_warehouse_transport",
        executable="warehouse_transport_bridge",
        name="warehouse_transport_bridge",
        output="screen",
        parameters=[{"use_sim_time": False}],
    )
    ld.add_action(bridge_node)

    # The demo dispatcher is opt-in: by default the bridge just listens.
    # Set ``run_demo_dispatcher:=true`` to also send a scripted task loop.
    dispatcher_node = Node(
        package="go2_warehouse_transport",
        executable="warehouse_demo_dispatcher",
        name="warehouse_demo_dispatcher",
        output="screen",
        condition=None,  # left for the user to wire up via ROS 2 launch conditions
    )
    ld.add_action(dispatcher_node)

    return ld
