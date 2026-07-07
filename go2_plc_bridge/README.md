# go2_plc_bridge

ROS2 胶水包，把 `/home/bakamake/Downloads/1.py` 的 PLC + SSH + UDP 三段链路包装成 ROS2 节点，并补上 1.py 里缺失的 UDP 半双工链路。

## 节点一览

| 节点 | 替代 1.py 的函数 | 作用 |
|------|----------------|------|
| `plc_dog_bridge` | `main_loop` + `dog_stand_then_sit` | 用 `snap7` 轮询 PLC I128.0；上升沿触发后用 `paramiko` SSH 到 `192.168.101.4` 执行 `standup.py` / `standown.py` |
| `udp_trigger` | `udp_send_trigger` | 把固定报文通过 UDP 发到 `192.168.101.10:8888`；可用 service `/udp/trigger` 手动触发 |
| `udp_feedback` | `udp_receiver` | 监听 `0.0.0.0:8888` 的 UDP 报文，转发成 `/dog/joint_feedback` (std_msgs/String) |

## 话题 / 服务

### Publishers（来自 `plc_dog_bridge`）
- `/plc/i128_state` — `Bool`，每 200 ms 发布一次当前 I128.0
- `/dog/action_status` — `String`：`stand_started` / `stand_hold_done` / `sit_done`
- `/plc/bridge_heartbeat` — `Int32`，1 Hz 心跳

### Services
- `/dog/stand_sit_cycle` — `std_srvs/srv/Trigger`。手动启动一次"站→等→坐"流程，等价于 PLC 上升沿
- `/udp/trigger` — `std_srvs/srv/Trigger`。手动发一次 UDP 触发报文

### Subscriber（来自 `udp_feedback`）
- `/dog/joint_feedback` — `std_msgs/String`，JSON 格式，原始字段直接转存

## Launch

```bash
# 默认：带 PLC、带 SSH、UDP 全开
ros2 launch go2_plc_bridge go2_plc_pipeline.launch.py

# 不接硬件的纯开发模式（用 trigger_once 跑一次假触发）
ros2 launch go2_plc_bridge go2_plc_pipeline.launch.py \
    use_plc:=false use_ssh:=false trigger_once:=true

# 关掉 UDP，只保留 PLC-SSH 主链路
ros2 launch go2_plc_bridge go2_plc_pipeline.launch.py enable_udp:=false
```

## 配置

`config/plc_dog_bridge.yaml` 里的字段直接镜像 1.py 顶部的常量区。可在 launch 时用
`config_file:=` 指向你自己的 yaml。

## 安装

```bash
# 系统依赖（与 1.py 一致）
pip3 install python-snap7 python-paramiko pyyaml

# 编译
cd /home/bakamake/go2_ros2_ws
colcon build --packages-select go2_plc_bridge
source install/setup.bash
```

## 干跑自检（无 PLC/无机器狗）

```bash
ros2 launch go2_plc_bridge go2_plc_pipeline.launch.py \
    use_plc:=false use_ssh:=false trigger_once:=true
# 期望日志：stand_started -> "holding stand for 10s" -> sit_done
```
