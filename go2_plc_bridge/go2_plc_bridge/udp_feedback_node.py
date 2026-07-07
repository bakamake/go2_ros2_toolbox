#!/usr/bin/env python3
"""ROS2 node: forward incoming UDP joint-state packets into a ROS topic.

Mirrors 1.py's `udp_receiver()`. JSON-looking packets are decoded and republished
as parsed key/value pairs in a String message; plain-text packets pass through
verbatim.
"""

import json
import socket
import threading

import rclpy
from rclpy.node import Node
from std_msgs.msg import String


class UdpFeedbackNode(Node):
    def __init__(self):
        super().__init__("udp_feedback")

        self.declare_parameter("listen_ip", "0.0.0.0")
        self.declare_parameter("listen_port", 8888)
        self.declare_parameter("recv_buffer_bytes", 2048)
        self.declare_parameter("topic", "/dog/joint_feedback")

        self._listen_ip = (
            self.get_parameter("listen_ip").get_parameter_value().string_value
        )
        self._listen_port = int(
            self.get_parameter("listen_port").get_parameter_value().integer_value
        )
        self._buf = int(
            self.get_parameter("recv_buffer_bytes").get_parameter_value().integer_value
        )
        topic = self.get_parameter("topic").get_parameter_value().string_value

        self._pub = self.create_publisher(String, topic, 10)
        self._stop_evt = threading.Event()

        try:
            self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self._sock.bind((self._listen_ip, self._listen_port))
        except Exception as e:
            self.get_logger().fatal(f"bind {self._listen_ip}:{self._listen_port} failed: {e}")
            raise

        self._thread = threading.Thread(target=self._recv_loop, daemon=True)
        self._thread.start()

        self.get_logger().info(
            f"udp_feedback listening on {self._listen_ip}:{self._listen_port} "
            f"-> {topic}"
        )

    def _recv_loop(self):
        while rclpy.ok() and not self._stop_evt.is_set():
            try:
                data, addr = self._sock.recvfrom(self._buf)
            except OSError:
                break
            text = data.decode("utf-8", errors="replace").strip()
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError:
                # plain text payload; just forward and log
                self.get_logger().info(f"udp txt from {addr}: {text}")
                msg = String()
                msg.data = text
                self._pub.publish(msg)
                continue

            status = parsed.get("status")
            action = parsed.get("action", "")
            if status == "finish":
                joints = parsed.get("joint_rad", {})
                self.get_logger().info(
                    f"dog action done status=finish action={action} "
                    f"joints={len(joints)} src={addr[0]}"
                )
            payload = json.dumps(parsed, ensure_ascii=False)
            msg = String()
            msg.data = payload
            self._pub.publish(msg)

    def destroy_node(self):
        self._stop_evt.set()
        try:
            self._sock.close()
        except Exception:
            pass
        super().destroy_node()


def main(args=None):
    rclpy.init(args=args)
    node = UdpFeedbackNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
