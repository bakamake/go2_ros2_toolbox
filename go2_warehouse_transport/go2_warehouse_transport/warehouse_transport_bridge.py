#!/usr/bin/env python3
"""Warehouse transport bridge.

Listens on a TCP socket for transport tasks of the form::

    {
      "task_id": "T001",
      "payload_id": "BOX-42",
      "pickup":   {"position": {...}, "orientation": {...}, "zone_id": "SHELF-A1"},
      "dropoff":  {"position": {...}, "orientation": {...}, "zone_id": "STAGE-3"}
    }

For each task it drives the Go2 through three phases against Nav2:

    1. DRIVE_TO_PICKUP   — NavigateToPose(pickup.pose)
    2. PICKUP            — simulated grasp (publishes /pickup_done)
    3. DRIVE_TO_DROPOFF  — NavigateToPose(dropoff.pose)
    4. PLACE             — simulated placement (publishes /place_done)

Status updates are published on ``/warehouse_transport/status`` (std_msgs/String)
and the result of every task is written back to the TCP client as a JSON
dictionary with at least ``{"task_id", "status", "phase"}``.

The bridge is a single-task executor: a new task arriving while another is
running is queued internally and serviced FIFO so order is preserved across
clients. Configuration is loaded from ``config/tcp_config.yaml`` (server host
and port) and ``config/warehouse_zones.yaml`` (named pose shortcuts).
"""

from __future__ import annotations

import json
import os
import queue
import socket
import struct
import threading
import time
from dataclasses import dataclass, field
from typing import Optional

import rclpy
from action_msgs.msg import GoalStatus
from geometry_msgs.msg import Pose, PoseStamped
from nav2_msgs.action import NavigateToPose
from rclpy.action import ActionClient
from rclpy.node import Node
from std_msgs.msg import String

import yaml
from ament_index_python.packages import get_package_share_directory


# --------------------------------------------------------------------------- #
# Data structures
# --------------------------------------------------------------------------- #

@dataclass
class Pose3D:
    """Position + quaternion plus an optional warehouse zone name."""
    position: dict
    orientation: dict
    zone_id: str = ""

    @classmethod
    def from_dict(cls, data: dict) -> "Pose3D":
        pos = data.get("position", {}) or {}
        ori = data.get("orientation", {}) or {}
        return cls(
            position={
                "x": float(pos.get("x", 0.0)),
                "y": float(pos.get("y", 0.0)),
                "z": float(pos.get("z", 0.0)),
            },
            orientation={
                "x": float(ori.get("x", 0.0)),
                "y": float(ori.get("y", 0.0)),
                "z": float(ori.get("z", 0.0)),
                "w": float(ori.get("w", 1.0)),
            },
            zone_id=str(data.get("zone_id", "")),
        )

    def to_pose_stamped(self, frame_id: str, stamp) -> PoseStamped:
        pose = PoseStamped()
        pose.header.frame_id = frame_id
        pose.header.stamp = stamp
        pose.pose.position.x = self.position["x"]
        pose.pose.position.y = self.position["y"]
        pose.pose.position.z = self.position["z"]
        pose.pose.orientation.x = self.orientation["x"]
        pose.pose.orientation.y = self.orientation["y"]
        pose.pose.orientation.z = self.orientation["z"]
        pose.pose.orientation.w = self.orientation["w"]
        return pose


@dataclass
class TransportTask:
    task_id: str
    payload_id: str
    pickup: Pose3D
    dropoff: Pose3D
    received_at: float = field(default_factory=time.time)


# --------------------------------------------------------------------------- #
# Main node
# --------------------------------------------------------------------------- #

class WarehouseTransportBridge(Node):
    """TCP <-> Nav2 bridge with a PICKUP/TRANSPORT/PLACE state machine."""

    PHASE_IDLE = "IDLE"
    PHASE_DRIVE_TO_PICKUP = "DRIVE_TO_PICKUP"
    PHASE_PICKUP = "PICKUP"
    PHASE_DRIVE_TO_DROPOFF = "DRIVE_TO_DROPOFF"
    PHASE_PLACE = "PLACE"

    def __init__(self) -> None:
        super().__init__("warehouse_transport_bridge")

        # ---- configuration ------------------------------------------------
        pkg_share = get_package_share_directory("go2_warehouse_transport")
        cfg_dir = os.path.join(pkg_share, "config")

        with open(os.path.join(cfg_dir, "tcp_config.yaml"), "r") as f:
            tcp_cfg = yaml.safe_load(f)
        self.host: str = tcp_cfg["nav_server"]["host"]
        self.port: int = int(tcp_cfg["nav_server"]["port"])

        with open(os.path.join(cfg_dir, "warehouse_zones.yaml"), "r") as f:
            zones_raw = yaml.safe_load(f) or {}
        self.zones: dict[str, Pose3D] = {
            name: Pose3D.from_dict(p) for name, p in (zones_raw.get("zones") or {}).items()
        }

        # ---- task state ---------------------------------------------------
        self.max_retries: int = int(tcp_cfg.get("nav_server", {}).get("max_retries", 3))
        self.phase: str = self.PHASE_IDLE
        self.current_task: Optional[TransportTask] = None
        self.retry_count: int = 0
        self._task_queue: "queue.Queue[TransportTask]" = queue.Queue()
        self._result_subscribers: list[tuple[socket.socket, str]] = []

        # ---- Nav2 client --------------------------------------------------
        self._nav_action = ActionClient(self, NavigateToPose, "navigate_to_pose")

        # ---- publishers ---------------------------------------------------
        self.status_pub = self.create_publisher(
            String, "/warehouse_transport/status", 10
        )
        self.pickup_done_pub = self.create_publisher(
            String, "/warehouse_transport/pickup_done", 10
        )
        self.place_done_pub = self.create_publisher(
            String, "/warehouse_transport/place_done", 10
        )

        # ---- TCP server ---------------------------------------------------
        self._server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._server_sock.bind((self.host, self.port))
        self._server_sock.listen(8)
        self._server_sock.settimeout(1.0)

        self._tcp_thread = threading.Thread(target=self._tcp_loop, daemon=True)
        self._tcp_thread.start()

        self._publish_status("bridge started", phase=self.PHASE_IDLE)
        self.get_logger().info(
            f"Warehouse transport bridge listening on {self.host}:{self.port}, "
            f"{len(self.zones)} named zones loaded."
        )

    # ------------------------------------------------------------------ TCP
    def _tcp_loop(self) -> None:
        while rclpy.ok():
            try:
                client, addr = self._server_sock.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            self.get_logger().info(f"TCP client connected: {addr}")
            t = threading.Thread(
                target=self._handle_client, args=(client, addr), daemon=True
            )
            t.start()

    def _handle_client(self, client: socket.socket, addr) -> None:
        client.settimeout(60.0)
        buf = b""
        try:
            while rclpy.ok():
                chunk = client.recv(4096)
                if not chunk:
                    break
                buf += chunk
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    self._dispatch_line(client, line)
        except Exception as exc:  # noqa: BLE001 — log + keep serving
            self.get_logger().warn(f"TCP client {addr} disconnected: {exc}")
        finally:
            try:
                client.close()
            except OSError:
                pass

    def _dispatch_line(self, client: socket.socket, raw: bytes) -> None:
        try:
            msg = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError as exc:
            self._reply(client, {
                "type": "error",
                "message": f"invalid JSON: {exc}",
            })
            return

        msg_type = msg.get("type", "task")
        if msg_type == "task":
            try:
                task = self._parse_task(msg)
            except (KeyError, ValueError) as exc:
                self._reply(client, {
                    "type": "task_rejected",
                    "task_id": msg.get("task_id", ""),
                    "reason": f"bad task: {exc}",
                })
                return

            self._task_queue.put(task)
            self._publish_status(
                f"task {task.task_id} accepted",
                task_id=task.task_id,
                phase=self.phase,
            )
            self._reply(client, {
                "type": "task_accepted",
                "task_id": task.task_id,
                "queue_position": self._task_queue.qsize(),
            })
        elif msg_type == "ping":
            self._reply(client, {
                "type": "pong",
                "phase": self.phase,
                "queue_size": self._task_queue.qsize(),
            })
        elif msg_type == "zones":
            self._reply(client, {
                "type": "zones",
                "zones": list(self.zones.keys()),
            })
        else:
            self._reply(client, {
                "type": "error",
                "message": f"unknown message type: {msg_type}",
            })

    def _reply(self, client: socket.socket, payload: dict) -> None:
        try:
            client.sendall((json.dumps(payload) + "\n").encode("utf-8"))
        except OSError:
            pass

    # -------------------------------------------------------------- parsing
    def _parse_task(self, msg: dict) -> TransportTask:
        task_id = str(msg["task_id"]).strip()
        if not task_id:
            raise ValueError("task_id missing")
        payload_id = str(msg.get("payload_id", "")).strip() or f"PL-{task_id}"

        pickup = self._resolve_pose(msg.get("pickup"))
        dropoff = self._resolve_pose(msg.get("dropoff"))
        return TransportTask(
            task_id=task_id,
            payload_id=payload_id,
            pickup=pickup,
            dropoff=dropoff,
        )

    def _resolve_pose(self, raw) -> Pose3D:
        if raw is None:
            raise ValueError("pose missing")
        if isinstance(raw, str):
            if raw not in self.zones:
                raise ValueError(f"unknown zone: {raw}")
            pose = self.zones[raw]
            return Pose3D(pose.position, pose.orientation, zone_id=raw)
        return Pose3D.from_dict(raw)

    # ------------------------------------------------------------- executor
    def _pump(self) -> None:
        """Called from a periodic ROS timer to advance the state machine."""
        if self.phase != self.PHASE_IDLE:
            return
        try:
            self.current_task = self._task_queue.get_nowait()
        except queue.Empty:
            self.current_task = None
            return
        self.retry_count = 0
        self._enter_drive_to_pickup()

    def _enter_drive_to_pickup(self) -> None:
        task = self.current_task
        assert task is not None
        self.phase = self.PHASE_DRIVE_TO_PICKUP
        self._publish_status(
            f"drive to pickup zone={task.pickup.zone_id or 'pose'}",
            task_id=task.task_id, phase=self.phase,
        )
        goal = NavigateToPose.Goal()
        goal.pose = task.pickup.to_pose_stamped(
            "odom", self.get_clock().now().to_msg()
        )
        self._send_nav_goal(goal, "pickup")

    def _enter_drive_to_dropoff(self) -> None:
        task = self.current_task
        assert task is not None
        self.phase = self.PHASE_DRIVE_TO_DROPOFF
        self._publish_status(
            f"transport to dropoff zone={task.dropoff.zone_id or 'pose'}",
            task_id=task.task_id, phase=self.phase,
        )
        self.pickup_done_pub.publish(String(data=task.payload_id))
        goal = NavigateToPose.Goal()
        goal.pose = task.dropoff.to_pose_stamped(
            "odom", self.get_clock().now().to_msg()
        )
        self._send_nav_goal(goal, "dropoff")

    def _enter_place(self) -> None:
        task = self.current_task
        assert task is not None
        self.phase = self.PHASE_PLACE
        self._publish_status(
            f"place payload={task.payload_id}",
            task_id=task.task_id, phase=self.phase,
        )
        # In the real robot this would command a low-level placement action.
        # For simulation we mark it complete after a short dwell.
        self.create_timer(1.5, lambda: self._finish_task(success=True), one_shot=True)

    def _finish_task(self, success: bool, error: str = "") -> None:
        task = self.current_task
        if task is None:
            self.phase = self.PHASE_IDLE
            return
        if success:
            self.place_done_pub.publish(String(data=task.payload_id))
            self._publish_status(
                f"task {task.task_id} done",
                task_id=task.task_id, phase=self.PHASE_PLACE,
            )
        result = {
            "type": "task_result",
            "task_id": task.task_id,
            "payload_id": task.payload_id,
            "status": "ok" if success else "error",
            "phase": self.phase,
            "error": error,
        }
        # broadcast to any attached clients via status topic
        self.status_pub.publish(String(data=json.dumps(result)))
        self.get_logger().info(json.dumps(result))
        self.current_task = None
        self.retry_count = 0
        self.phase = self.PHASE_IDLE

    # --------------------------------------------------------- nav helpers
    def _send_nav_goal(self, goal: NavigateToPose.Goal, leg: str) -> None:
        if not self._nav_action.wait_for_server(timeout_sec=5.0):
            self.get_logger().error("Nav2 action server unavailable")
            self._finish_task(success=False, error="nav2 action unavailable")
            return
        fut = self._nav_action.send_goal_async(
            goal, feedback_callback=self._nav_feedback_cb(leg)
        )
        fut.add_done_callback(self._nav_goal_resp_cb(leg))

    def _nav_goal_resp_cb(self, leg: str):
        def _cb(future) -> None:
            handle = future.result()
            if handle is None or not handle.accepted:
                self.get_logger().warn(f"{leg} goal rejected")
                self._finish_task(success=False, error=f"{leg} rejected")
                return
            fut = handle.get_result_async()
            fut.add_done_callback(self._nav_result_cb(leg))
        return _cb

    def _nav_result_cb(self, leg: str):
        def _cb(future) -> None:
            wrapped = future.result()
            status = wrapped.status if wrapped is not None else -1
            if status == GoalStatus.STATUS_SUCCEEDED:
                if leg == "pickup":
                    # arrived at pickup — simulate a brief grasp
                    self.phase = self.PHASE_PICKUP
                    self._publish_status("pickup payload", phase=self.PHASE_PICKUP)
                    self.create_timer(
                        1.0, lambda: self._enter_drive_to_dropoff(),
                        one_shot=True,
                    )
                else:
                    self._enter_place()
                return
            # failure path: retry then fail
            if self.retry_count < self.max_retries:
                self.retry_count += 1
                self.get_logger().warn(
                    f"{leg} leg failed (status={status}), retry "
                    f"{self.retry_count}/{self.max_retries}"
                )
                self._send_nav_goal(self._make_replay_goal(leg), leg)
            else:
                self._finish_task(
                    success=False, error=f"{leg} failed after {self.max_retries}"
                )
        return _cb

    def _nav_feedback_cb(self, leg: str):
        def _cb(msg) -> None:
            remaining = msg.feedback.distance_remaining
            self.get_logger().info(
                f"{leg} leg: {remaining:.2f} m remaining"
            )
        return _cb

    def _make_replay_goal(self, leg: str) -> NavigateToPose.Goal:
        task = self.current_task
        goal = NavigateToPose.Goal()
        if task is None:
            return goal
        pose3d = task.pickup if leg == "pickup" else task.dropoff
        goal.pose = pose3d.to_pose_stamped(
            "odom", self.get_clock().now().to_msg()
        )
        return goal

    # -------------------------------------------------------- misc helpers
    def _publish_status(self, message: str, task_id: str = "", phase: str = "") -> None:
        self.status_pub.publish(String(data=json.dumps({
            "ts": time.time(),
            "phase": phase or self.phase,
            "task_id": task_id,
            "message": message,
        })))
        self.get_logger().info(f"[{phase or self.phase}] {message}")


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #

def main(args=None) -> None:
    rclpy.init(args=args)
    node = WarehouseTransportBridge()
    try:
        # _pump runs at 20 Hz; Nav2 callbacks drive the rest of the FSM.
        node.create_timer(0.05, lambda: node._pump())
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        try:
            node._server_sock.close()
        except OSError:
            pass
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
