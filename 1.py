import snap7
import socket
import paramiko
import time
import threading
import json

# ====================== 配置区 ======================
PLC_IP = "192.168.101.15"
PLC_RACK = 0
PLC_SLOT = 1
CHECK_INTERVAL = 0.2

# PLC触发 I128.0
TRIG_I_BYTE = 128
TRIG_I_BIT = 0

# 机器狗SSH
DOG_IP = "192.168.101.5"
DOG_USER = "unitree"
DOG_PWD = "123"
DOG_SSH_PORT = 22
STAND_CMD = "cd ~/unitree_sdk2_python/unitree_sdk2py && PYTHONPATH=../ python3 standup.py"
SIT_CMD = "cd ~/unitree_sdk2_python/unitree_sdk2py && PYTHONPATH=../ python3 standown.py"
STAND_DURATION = 10

# UDP
UDP_LISTEN_IP = "0.0.0.0"
UDP_LISTEN_PORT = 8888
TARGET_IP = "192.168.101.10"
TARGET_PORT = 8888
SEND_MSG = b"Q0.0_ON_TRIGGER"
# ====================================================

last_trig_state = False
is_running_action = False

def connect_plc():
    plc = snap7.client.Client()
    try:
        plc.connect(PLC_IP, PLC_RACK, PLC_SLOT)
        if plc.get_connected():
            print(f"✅ PLC连接成功 {PLC_IP} 机架{PLC_RACK} 插槽{PLC_SLOT}")
            return plc
        else:
            print("❌ PLC连接失败，请检查IP/机架插槽")
            return None
    except Exception as e:
        print(f"❌ PLC连接异常: {str(e)}")
        return None

def read_i_bit(plc, byte_num, bit_num):
    try:
        i_data = plc.read_area(0x81, 0, byte_num, 1)
        if len(i_data) < 1:
            return False
        byte_val = snap7.util.get_byte(i_data, 0)
        bit_status = (byte_val >> bit_num) & 1
        return bool(bit_status)
    except Exception as e:
        print(f"\r⚠️ I区读取异常: {str(e)}", end="")
        return False

def ssh_run_single_cmd(cmd: str):
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        ssh.connect(
            hostname=DOG_IP,
            username=DOG_USER,
            password=DOG_PWD,
            port=DOG_SSH_PORT,
            timeout=8
        )
        print(f"\n🚀 执行命令：{cmd}")
        stdin, stdout, stderr = ssh.exec_command(cmd)
        # 删除读取并打印机器终端输出的代码，只执行不打印
        stdout.read()
        stderr.read()
    except Exception as e:
        print(f"❌ SSH执行失败: {str(e)}")
    finally:
        ssh.close()

def dog_stand_then_sit():
    global is_running_action
    is_running_action = True
    try:
        ssh_run_single_cmd(STAND_CMD)
        print(f"⏱️ 保持站立 {STAND_DURATION} 秒...")
        time.sleep(STAND_DURATION)
        ssh_run_single_cmd(SIT_CMD)
        print("\n======================")
        print("finish")
        print("======================\n")
    finally:
        is_running_action = False

def udp_send_trigger():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.sendto(SEND_MSG, (TARGET_IP, TARGET_PORT))
    sock.close()
    print(f"📤 UDP发送 {SEND_MSG.decode()} → {TARGET_IP}:{TARGET_PORT}")

# UDP接收线程，解析机器狗回传的真实关节JSON
def udp_receiver():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind((UDP_LISTEN_IP, UDP_LISTEN_PORT))
    print(f"\n📡 UDP接收线程启动，监听 {UDP_LISTEN_PORT} 等待机器狗关节状态反馈...")
    while True:
        data, addr = sock.recvfrom(2048)
        try:
            recv_json = json.loads(data.decode("utf-8"))
            if recv_json.get("status") == "finish":
                print("\n=====================================")
                print(f"🟢 收到机器狗动作完成反馈 | 动作类型：{recv_json['action']}")
                print("【当前全部关节角度（rad）】")
                joints = recv_json["joint_rad"]
                for name, val in joints.items():
                    print(f"{name:15s} = {val:.4f}")
                print("=====================================\n")
        except json.JSONDecodeError:
            text = data.decode().strip()
            print(f"\n📩 收到普通UDP消息：{text} 来源 {addr[0]}")

def main_loop():
    global last_trig_state
    recv_thread = threading.Thread(target=udp_receiver)
    recv_thread.daemon = True
    recv_thread.start()

    plc = connect_plc()
    if not plc:
        return
    print("🔍 开始循环检测 I128.0 输入信号...")
    try:
        while True:
            current_state = read_i_bit(plc, TRIG_I_BYTE, TRIG_I_BIT)
            print(f"\rI128.0 当前状态: {'ON' if current_state else 'OFF'} | 动作运行中: {is_running_action}", end="")

            if current_state and not last_trig_state and not is_running_action:
                print("\n⚡ 检测到I128.0上升沿，启动站立10秒自动坐下流程！")
                udp_send_trigger()
                action_thread = threading.Thread(target=dog_stand_then_sit)
                action_thread.daemon = True
                action_thread.start()

            last_trig_state = current_state
            time.sleep(CHECK_INTERVAL)
    except KeyboardInterrupt:
        print("\n\n🔴 程序手动终止")
    finally:
        if plc.get_connected():
            plc.disconnect()
            print("PLC连接已断开")

if __name__ == "__main__":
    main_loop()
