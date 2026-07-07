#!/usr/bin/env python3
"""ROS2 glue node: PLC I128.0 rising edge -> SSH to Go2 host -> standup / standown.

Mirrors the legacy /home/bakamake/Downloads/1.py flow but keeps a long-lived
paramiko SSH connection and exposes ROS2 topics for observability.
"""

import os
import socket
import threading
import time

import rclpy
from rclpy.node import Node
from std_msgs.msg import Bool, Int32, String
from std_srvs.srv import Trigger

import snap7  # type: ignore
import paramiko  # type: ignore
import yaml


class SshPool:
    """Maintain a single paramiko.SSHClient with keepalive and lazy reconnect."""

    def __init__(self, host, port, user, password, keepalive=10, lock=None):
        self._host = host
        self._port = port
        self._user = user
        self._password = password
        self._keepalive = keepalive
        self._lock = lock or threading.Lock()
        self._client = None
        self._transport = None
        self._shell = None

    def _open_locked(self):
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        client.connect(
            hostname=self._host,
            port=self._port,
            username=self._user,
            password=self._password,
            timeout=8,
            allow_agent=False,
            look_for_keys=False,
        )
        transport = client.get_transport()
        if transport is None:
            client.close()
            raise RuntimeError("paramiko: no transport after connect")
        transport.set_keepalive(self._keepalive)
        shell = transport.open_session(timeout=8)
        shell.settimeout(8)
        self._client = client
        self._transport = transport
        self._shell = shell

    def close(self):
        with self._lock:
            for attr in ("_shell", "_transport", "_client"):
                obj = getattr(self, attr)
                if obj is not None:
                    try:
                        obj.close()
                    except Exception:
                        pass
                    setattr(self, attr, None)

    def is_alive(self):
        if self._transport is None:
            return False
        return self._transport.is_alive()

    def ensure(self):
        with self._lock:
            if self._transport is not None and self._transport.is_alive():
                return
            # tear down stale state before reconnect
            self.close()
            self._open_locked()

    def run(self, cmd):
        """Run cmd in a fresh exec channel; return (rc, stdout, stderr)."""
        with self._lock:
            self.ensure()
            assert self._client is not None
            try:
                stdin, stdout, stderr = self._client.exec_command(cmd, timeout=8)
                rc = stdout.channel.recv_exit_status()
                out = stdout.read().decode("utf-8", errors="replace")
                err = stderr.read().decode("utf-8", errors="replace")
                return rc, out, err
            except (paramiko.SSHException, socket.error, OSError):
                # drop the connection so the next call reconnects
                self.close()
                raise


class PlcDogBridge(Node):
    def __init__(self):
        super().__init__("plc_dog_bridge")

        # ---- parameters ----
        self.declare_parameter("config_file", "")
        cfg_file = self.get_parameter("config_file").get_parameter_value().string_value
        cfg = self._load_config(cfg_file)

        plc = cfg["plc"]
        dog = cfg["dog"]
        bridge = cfg["bridge"]

        self._plc_ip = plc["ip"]
        self._plc_rack = int(plc["rack"])
        self._plc_slot = int(plc["slot"])
        self._trig_byte = int(plc["trig_i_byte"])
        self._trig_bit = int(plc["trig_i_bit"])
        self._poll_period = float(plc["poll_period"])

        self._dog_ip = dog["ip"]
        self._dog_user = dog["user"]
        self._dog_password = dog["password"]
        self._dog_ssh_port = int(dog["ssh_port"])
        self._stand_cmd = dog["stand_cmd"]
        self._sit_cmd = dog["sit_cmd"]
        self._stand_duration = float(dog["stand_duration"])

        self._reconnect_period = float(bridge["reconnect_period"])
        self._ssh_keepalive = int(bridge["ssh_keepalive_interval"])

        # ---- dry-run flags for hardware-less dev ----
        self.declare_parameter("use_plc", True)
        self.declare_parameter("use_ssh", True)
        self.declare_parameter("trigger_once", False)
        self._use_plc = bool(self.get_parameter("use_plc").get_parameter_value().bool_value)
        self._use_ssh = bool(self.get_parameter("use_ssh").get_parameter_value().bool_value)
        self._trigger_once = bool(
            self.get_parameter("trigger_once").get_parameter_value().bool_value
        )
        self._trigger_once_fired = False

        # ---- publishers ----
        self._state_pub = self.create_publisher(Bool, "/plc/i128_state", 10)
        self._action_pub = self.create_publisher(String, "/dog/action_status", 10)
        self._heartbeat_pub = self.create_publisher(Int32, "/plc/bridge_heartbeat", 10)

        # ---- service: trigger a stand->hold->sit cycle on demand ----
        self._stand_sit_srv = self.create_service(
            Trigger, "/dog/stand_sit_cycle", self._on_stand_sit_service)

        # ---- internal state ----
        self._action_lock = threading.Lock()
        self._action_running = False
        self._last_state = False
        self._heartbeat_counter = 0
        self._plc = None
        self._ssh = SshPool(
            host=self._dog_ip,
            port=self._dog_ssh_port,
            user=self._dog_user,
            password=self._dog_password,
            keepalive=self._ssh_keepalive,
            lock=threading.Lock(),
        )

        # 1Hz heartbeat for liveness checks
        self.create_timer(1.0, self._tick_heartbeat)

        # main poll loop
        self.create_timer(self._poll_period, self._poll_once)

        self.get_logger().info(
            f"plc_dog_bridge up: plc={self._plc_ip}:{self._plc_rack}/{self._plc_slot} "
            f"i{self._trig_byte}.{self._trig_bit} dog={self._dog_ip} "
            f"use_plc={self._use_plc} use_ssh={self._use_ssh} "
            f"trigger_once={self._trigger_once}"
        )

    # ---------- config loading ----------
    def _load_config(self, cfg_file):
        defaults = {
            "plc": {
                "ip": "192.168.101.15",
                "rack": 0,
                "slot": 1,
                "trig_i_byte": 128,
                "trig_i_bit": 0,
                "poll_period": 0.2,
            },
            "dog": {
                "ip": "192.168.101.4",
                "user": "unitree",
                "password": "123",
                "ssh_port": 22,
                "stand_cmd": "cd ~/unitree_sdk2_python/unitree_sdk2py && PYTHONPATH=../ python3 standup.py",
                "sit_cmd": "cd ~/unitree_sdk2_python/unitree_sdk2py && PYTHONPATH=../ python3 standown.py",
                "stand_duration": 10,
            },
            "bridge": {
                "reconnect_period": 5.0,
                "ssh_keepalive_interval": 10,
            },
        }
        if not cfg_file:
            return defaults
        if not os.path.isabs(cfg_file):
            # try share/ first (ament index), then CWD-relative
            try:
                from ament_index_python.packages import get_package_share_directory
                share = get_package_share_directory("go2_plc_bridge")
                candidate = os.path.join(share, cfg_file)
                if os.path.exists(candidate):
                    cfg_file = candidate
            except Exception:
                pass
        if not os.path.exists(cfg_file):
            self.get_logger().warn(f"config_file not found: {cfg_file}, using defaults")
            return defaults
        with open(cfg_file, "r") as f:
            loaded = yaml.safe_load(f) or {}
        # shallow merge
        for k, v in loaded.items():
            if isinstance(v, dict) and k in defaults:
                defaults[k].update(v)
            else:
                defaults[k] = v
        return defaults

    # ---------- heartbeat ----------
    def _tick_heartbeat(self):
        self._heartbeat_counter += 1
        msg = Int32()
        msg.data = self._heartbeat_counter
        self._heartbeat_pub.publish(msg)

    # ---------- PLC ----------
    def _ensure_plc(self):
        if not self._use_plc:
            return None
        if self._plc is not None and self._plc.get_connected():
            return self._plc
        self._plc = snap7.client.Client()
        try:
            self._plc.connect(self._plc_ip, self._plc_rack, self._plc_slot)
        except Exception as e:
            self.get_logger().error(f"PLC connect failed: {e}")
            self._plc = None
            return None
        if not self._plc.get_connected():
            self._plc = None
            return None
        self.get_logger().info(
            f"PLC connected {self._plc_ip} rack={self._plc_rack} slot={self._plc_slot}"
        )
        return self._plc

    def _read_i_bit(self):
        if not self._use_plc:
            return False
        plc = self._ensure_plc()
        if plc is None:
            return False
        try:
            i_data = plc.read_area(0x81, 0, self._trig_byte, 1)
        except Exception as e:
            self.get_logger().warn(f"I area read failed: {e}")
            try:
                plc.disconnect()
            except Exception:
                pass
            self._plc = None
            return False
        if len(i_data) < 1:
            return False
        byte_val = snap7.util.get_byte(i_data, 0)
        return bool((byte_val >> self._trig_bit) & 1)

    # ---------- action ----------
    def _publish_action(self, text):
        msg = String()
        msg.data = text
        self._action_pub.publish(msg)
        self.get_logger().info(text)

    def _start_action(self):
        if not self._action_lock.acquire(blocking=False):
            return
        try:
            if self._action_running:
                return
            self._action_running = True
        finally:
            self._action_lock.release()

        t = threading.Thread(target=self._run_stand_then_sit, daemon=True)
        t.start()

    def _run_stand_then_sit(self):
        try:
            self._publish_action("stand_started")
            self._ssh_run(self._stand_cmd)
            self.get_logger().info(f"holding stand for {self._stand_duration}s")
            time.sleep(self._stand_duration)
            self._publish_action("stand_hold_done")
            self._ssh_run(self._sit_cmd)
            self._publish_action("sit_done")
        finally:
            with self._action_lock:
                self._action_running = False

    def _ssh_run(self, cmd):
        if not self._use_ssh:
            self.get_logger().info(f"[dry-run] would run: {cmd}")
            return
        try:
            rc, out, err = self._ssh.run(cmd)
            self.get_logger().info(f"ssh rc={rc} cmd={cmd}")
            if out.strip():
                self.get_logger().info(f"ssh stdout: {out.strip()}")
            if err.strip():
                self.get_logger().warn(f"ssh stderr: {err.strip()}")
        except Exception as e:
            self.get_logger().error(f"SSH exec failed: {e}")

    # ---------- service callback ----------
    def _on_stand_sit_service(self, _req, response):
        """Trigger service: mirrors what the PLC rising-edge path does."""
        # Reuse the same gate as the PLC path so we never run two cycles
        # simultaneously.
        if self._action_running:
            response.success = False
            response.message = "stand->sit cycle already in progress"
            self.get_logger().warn(response.message)
            return response
        self.get_logger().info(
            "/dog/stand_sit_cycle service called, starting cycle")
        self._start_action()
        response.success = True
        response.message = "cycle started"
        return response

    # ---------- main loop ----------
    def _poll_once(self):
        current = self._read_i_bit()
        state_msg = Bool()
        state_msg.data = current
        self._state_pub.publish(state_msg)

        rising = current and not self._last_state
        self._last_state = current

        if self._trigger_once and not self._trigger_once_fired:
            self._trigger_once_fired = True
            self.get_logger().info("trigger_once: firing stand->sit cycle")
            self._start_action()
            return

        if rising and not self._action_running:
            self.get_logger().info(
                f"rising edge on I{self._trig_byte}.{self._trig_bit}, starting cycle"
            )
            self._start_action()

    def destroy_node(self):
        try:
            self._ssh.close()
        except Exception:
            pass
        try:
            if self._plc is not None and self._plc.get_connected():
                self._plc.disconnect()
        except Exception:
            pass
        super().destroy_node()


def main(args=None):
    rclpy.init(args=args)
    node = PlcDogBridge()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
