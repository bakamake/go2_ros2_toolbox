# Go2 ROS2 Toolbox（中文说明）


> 本文件为[英文原版 README](./README.md)的中文翻译，若有疑问请参考原文。

[![ROS2](https://img.shields.io/badge/ROS2-Foxy-green.svg)](https://docs.ros.org/en/foxy/)
[![License](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Platform](https://img.shields.io/badge/Platform-Ubuntu%2020.04-orange.svg)](https://ubuntu.com/)

本项目是为 Unitree Go2 EDU 机器人开发的 ROS2 工具箱，提供 SLAM 与导航能力，实现自主运行。

如果觉得本项目有用，请点个 Star ⭐️ 支持一下！

<div align="center">
  <img src="asset/demo.gif" alt="Go2 ROS2 Toolbox Demo" width="100%" style="background-color: #1a1a1a;">
</div>

## 🚀 功能特性

- **激光雷达集成**：实时点云处理与累积
- **相机支持**：基于 GStreamer 的相机采集与推流
- **SLAM 能力**：集成 SLAM Toolbox 进行建图
- **导航系统**：完整集成 Navigation2 实现自主导航
- **原生 ROS2**：专为 ROS2 Foxy 生态构建

## 📋 前置条件

> **⚠️ 注意：本仓库功能仅在 Go2 EDU 扩展坞自带计算机上测试通过，其他环境（如 PC 直连扩展坞）未验证。**

开发与测试环境：

- **操作系统**：Ubuntu 20.04
- **ROS2**：Foxy
- **固件**：v1.1.7（已测试）

## 🛠️ 安装步骤

### 1. 安装官方 Unitree ROS2 包

请先安装官方 Unitree ROS2 包：

```bash
# 参考官方安装指南
# https://github.com/unitreerobotics/unitree_ros2
```

### 2. 安装依赖

#### ROS2 依赖包

```bash
sudo apt-get install ros-foxy-navigation2 \
                     ros-foxy-nav2-bringup \
                     ros-foxy-pcl-ros \
                     ros-foxy-tf-transformations \
                     ros-foxy-slam-toolbox
```

#### Python 依赖包

```bash
pip3 install transforms3d
```

### 3. 编译工作空间

```bash
# 创建工作空间
mkdir -p go2_ros2_ws/src
cd go2_ros2_ws/src

# 克隆本仓库
git clone https://github.com/andy-zhuo-02/go2_ros2_toolbox.git

# 编译
cd ..
colcon build
```

## 🎯 使用方法

### 快速启动

```bash
# Source 环境
source install/setup.bash

# 启动机器人
ros2 launch go2_core go2_startup.launch.py
```

### SLAM 操作

- **地图保存**：将生成的地图序列化保存
- **地图加载**：加载之前保存的地图

### 导航

1. 打开 RViz2
2. 选择"Navigation2 Goal"按钮
3. 在地图上点击设置导航目标
4. 拖动调整目标朝向

## 🔧 开发说明

### 坐标系参考

| 坐标系         | 说明           | 来源                   |
| -------------- | -------------- | ---------------------- |
| `/odom`      | 里程计坐标系   | Unitree Go2 里程计话题 |
| `/map`       | 地图坐标系     | SLAM Toolbox           |
| `/base_link` | 机器人基座坐标 | Unitree Go2 里程计话题 |

### ROS 话题

#### 发布者

| 组件             | 话题名                      | 类型        | 坐标系    |
| ---------------- | --------------------------- | ----------- | --------- |
| 机器人位姿       | `/utlidar/robot_pose`     | PoseStamped | `/odom` |
| 激光雷达（原始） | `/utlidar/cloud_deskewed` | PointCloud2 | `/odom` |
| 激光雷达（累积） | `/trans_cloud`            | PointCloud2 | `/odom` |
| 相机图像         | `/camera/image_raw`       | Image       | -         |

#### 订阅者

| 组件         | 话题名      | 类型  | 坐标系        |
| ------------ | ----------- | ----- | ------------- |
| 速度控制命令 | `/cmd_vel`  | Twist | `/base_link` |

## 🤝 贡献

欢迎贡献代码！请随时提交 issue 或 pull request。

## 📄 许可证

本项目采用 MIT 许可证，详见 [LICENSE](LICENSE) 文件。

## 🙏 鸣谢

- Unitree Robotics 提供 Go2 EDU 平台
- ROS2 社区的导航与 SLAM 工具
- 本工具箱的贡献者与用户

## 📞 支持

如遇问题或有疑问，请：

1. 查看 [Issues](https://github.com/andy-zhuo-02/go2_ros2_toolbox/issues) 页面
2. 创建新 issue 并详细描述问题
3. 附上系统信息与错误日志

---

**注意**：本工具箱为非官方项目，与 Unitree Robotics 无直接关联。

## 🆕 PLC / Go2 SSH 桥接 (`go2_plc_bridge`)

将原 `1.py` 中「PLC `I128.0` 上升沿 → SSH 到 Go2 主机执行 `standup.py` → 10s 后执行 `standown.py`」的流程封装为 ROS2 节点。

```bash
# 先装 Python 依赖
pip3 install paramiko python-snap7

# 启动（真实硬件）
ros2 launch go2_plc_bridge plc_dog_bridge.launch.py

# 调试用 dry-run：不读 PLC、不发 SSH
ros2 launch go2_plc_bridge plc_dog_bridge.launch.py use_plc:=false use_ssh:=false

# 无 PLC 也能复现一次完整 cycle
ros2 launch go2_plc_bridge plc_dog_bridge.launch.py use_plc:=false trigger_once:=true
```

观察话题：

- `/plc/i128_state` (`std_msgs/Bool`) — 每个 poll 周期发布当前 I128.0 状态
- `/dog/action_status` (`std_msgs/String`) — `stand_started` / `stand_hold_done` / `sit_done`
- `/plc/bridge_heartbeat` (`std_msgs/Int32`) — 1Hz 心跳计数

参数在 `go2_plc_bridge/config/plc_dog_bridge.yaml`；生产环境请改用 SSH key，避免在 YAML 中放明文密码。

## 🆕 Navigation TCP 桥 (`go2_navigation` 修复)

- `nav2_tcp_bridge` 与 `tcp_client_standalone` 现在是 `ros2 run` 可发现的 console script
- `config/tcp_config.yaml` 默认监听 `0.0.0.0:5432`（与 `go2_startup.launch.py` 中 `tcp_port=5432` 一致）

```bash
ros2 run go2_navigation nav2_tcp_bridge
ros2 run go2_navigation tcp_client_standalone
```
