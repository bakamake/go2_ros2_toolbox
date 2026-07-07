#!/usr/bin/env python3
"""Demo dispatcher: a small TCP client that pushes a scripted transport queue
into ``warehouse_transport_bridge``.

The default queue is three transport tasks that loop through the simulated
warehouse map (see ``config/warehouse_zones.yaml``)::

    T1  SHELF-A1 -> STAGE-1
    T2  SHELF-B2 -> BAY-OUT
    T3  SHELF-A3 -> STAGE-3

Each transport request is sent as a single NDJSON line; replies are read
until the connection is closed. This script is intentionally synchronous —
it is meant as a smoke test, not a production dispatcher.

Usage::

    ros2 run go2_warehouse_transport warehouse_demo_dispatcher
"""

from __future__ import annotations

import json
import os
import socket
import sys
import time

import yaml
from ament_index_python.packages import get_package_share_directory


DEFAULT_TASKS = [
    {"task_id": "T1", "payload_id": "BOX-001",
     "pickup": "SHELF-A1", "dropoff": "STAGE-1"},
    {"task_id": "T2", "payload_id": "BOX-002",
     "pickup": "SHELF-B2", "dropoff": "BAY-OUT"},
    {"task_id": "T3", "payload_id": "BOX-003",
     "pickup": "SHELF-A3", "dropoff": "STAGE-3"},
    {"task_id": "T4", "payload_id": "BOX-004",
     "pickup": "SHELF-B1", "dropoff": "STAGE-2"},
    {"task_id": "T5", "payload_id": "BOX-005",
     "pickup": "SHELF-A2", "dropoff": "STAGE-3"},
]


def _load_tcp_config() -> tuple[str, int]:
    cfg_path = os.path.join(
        get_package_share_directory("go2_warehouse_transport"),
        "config",
        "tcp_config.yaml",
    )
    with open(cfg_path, "r") as f:
        cfg = yaml.safe_load(f)
    return cfg["nav_server"]["host"], int(cfg["nav_server"]["port"])


def run(tasks=None, host: str | None = None, port: int | None = None,
        interval: float = 2.0) -> int:
    tasks = tasks or DEFAULT_TASKS
    config_host, config_port = _load_tcp_config()
    host = host or config_host
    port = port or config_port

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(10.0)
    print(f"[dispatcher] connecting to {host}:{port}")
    sock.connect((host, port))

    def _recv_reply() -> dict | None:
        buf = b""
        try:
            while b"\n" not in buf:
                chunk = sock.recv(4096)
                if not chunk:
                    return None
                buf += chunk
        except socket.timeout:
            return None
        line, _, _ = buf.partition(b"\n")
        try:
            return json.loads(line.decode("utf-8"))
        except json.JSONDecodeError:
            return None

    try:
        # First sanity ping so the operator can verify the bridge is up.
        sock.sendall((json.dumps({"type": "ping"}) + "\n").encode("utf-8"))
        print("[dispatcher] ping ->", _recv_reply())

        for task in tasks:
            print(f"[dispatcher] dispatching {task['task_id']}: "
                  f"{task['pickup']} -> {task['dropoff']}")
            msg = json.dumps({"type": "task", **task}).encode("utf-8")
            sock.sendall(msg + b"\n")
            print("[dispatcher] ack ->", _recv_reply())
            time.sleep(interval)

        # Wait briefly for the bridge to drain the queue, then close.
        time.sleep(1.0)
        return 0
    except (OSError, ConnectionError) as exc:
        print(f"[dispatcher] error: {exc}", file=sys.stderr)
        return 1
    finally:
        sock.close()


def main() -> None:
    rc = run()
    sys.exit(rc)


if __name__ == "__main__":
    main()
