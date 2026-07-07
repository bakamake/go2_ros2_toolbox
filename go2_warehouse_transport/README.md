# go2_warehouse_transport

Go2 自主运输与定点放置包（仓库仿真）。

基于已有的 `go2_navigation` 的 TCP/Nav2 桥接思路改造，新增了一个
`PICKUP → TRANSPORT → PLACE` 状态机，模拟一个小型仓库：

- 两侧货架线（`SHELF-A1/A2/A3`、`SHELF-B1/B2/B3`）作为取货点。
- 中央三个分拣台（`STAGE-1/2/3`）、装车口（`BAY-OUT`）、原点（`HOME`）
  作为放置点。
- 通过 TCP 接收外部调度器推送的运输任务，按 FIFO 服务，结果回写给
  客户端并发布到 `/warehouse_transport/status`。
- 每次任务成功后向 `/warehouse_transport/pickup_done` 与
  `/warehouse_transport/place_done` 各发一条 `String`
  消息（payload_id），可对接抓取/放置执行器或仿真可视化节点。

## 节点

| 可执行 | 作用 |
|---|---|
| `warehouse_transport_bridge` | 主节点：TCP 服务 + Nav2 客户端 + 状态机 |
| `warehouse_demo_dispatcher`  | 演示脚本：循环派送 5 条样例任务 |

## 协议（NDJSON over TCP，每行一条消息）

请求：

```json
{"type":"task","task_id":"T1","payload_id":"BOX-001",
 "pickup":"SHELF-A1","dropoff":"STAGE-1"}
```

请求也可直接传入 `position` / `orientation` 字典而不用 zone 名。

应答：

```json
{"type":"task_accepted","task_id":"T1","queue_position":2}
```

心跳：

```json
{"type":"ping"}
```

## 配置文件

- `config/tcp_config.yaml` — TCP 服务地址 / 最大重试次数
- `config/warehouse_zones.yaml` — 取货点 / 放置点预设坐标

## 启动

```bash
# 端 1（启动 Nav2，详见 go2_navigation）
ros2 launch go2_navigation go2_nav2.launch.py

# 端 2（运输桥 + 内置演示 dispatcher）
ros2 launch go2_warehouse_transport go2_warehouse_transport.launch.py
```
