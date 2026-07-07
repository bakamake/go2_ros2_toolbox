#!/usr/bin/env python3
"""ROS2 node: bridge an outgoing UDP trigger message to ROS services/topic.

Mirrors 1.py's `udp_send_trigger()` so a separate PLC trigger (or a manual
service call) can broadcast the same fixed payload over UDP.
"""

import socket

import rclpy
from rclpy.node import Node
from std_msgs.msg import String
from std_srvs.srv import Trigger


class UdpTriggerNode(Node):
    def __init__(self):
        super().__init__("udp_trigger")

        self.declare_parameter("target_ip", "192.168.101.10")
        self.declare_parameter("target_port", 8888)
        self.declare_parameter("message", "Q0.0_ON_TRIGGER")

        self._target_ip = self.get_parameter("target_ip").get_parameter_value().string_value
        self._target_port = int(self.get_parameter("target_port").get_parameter_value().integer_value)
        self._message = (
            self.get_parameter("message").get_parameter_value().string_value.encode("utf-8")
        )

        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

        self._srv = self.create_service(
            Trigger, "/udp/trigger", self._on_trigger_service)
        self._pub = self.create_publisher(String, "/udp/trigger_log", 10)
        # Allow periodic fire without an external caller (defaults to off).
        self.declare_parameter("periodic_period_sec", 0.0)
        period = self.get_parameter("periodic_period_sec").get_parameter_value().double_value
        if period > 0.0:
            self.create_timer(period, self._send_once)

        self.get_logger().info(
            f"udp_trigger up -> {self._target_ip}:{self._target_port} "
            f"msg={self._message!r} periodic={period}s"
        )

    def _send_once(self):
        try:
            self._sock.sendto(self._message, (self._target_ip, self._target_port))
            self.get_logger().info(
                f"sent {self._message!r} -> {self._target_ip}:{self._target_port}")
            msg = String()
            msg.data = "sent"
            self._pub.publish(msg)
        except Exception as e:
            self.get_logger().error(f"udp send failed: {e}")

    def _on_trigger_service(self, _req, response):
        try:
            self._sock.sendto(self._message, (self._target_ip, self._target_port))
        except Exception as e:
            response.success = False
            response.message = f"sendto failed: {e}"
            self.get_logger().error(response.message)
            return response
        response.success = True
        response.message = (
            f"sent {len(self._message)} bytes to "
            f"{self._target_ip}:{self._target_port}")
        self.get_logger().info(response.message)
        msg = String()
        msg.data = response.message
        self._pub.publish(msg)
        return response

    def destroy_node(self):
        try:
            self._sock.close()
        except Exception:
            pass
        super().destroy_node()


def main(args=None):
    rclpy.init(args=args)
    node = UdpTriggerNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
