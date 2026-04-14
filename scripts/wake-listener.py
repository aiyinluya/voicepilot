"""
wake-listener.py — 唤醒词检测（后台常驻）
============================================
持续监听麦克风，检测到唤醒词后通知 QClaw 启动语音会话。

唤醒词：「嘿 Jarvis」「启动语音」「打开语音」「嘿 QClaw」

通知方式：写入信号文件，由 QClaw Skill 读取并接管。

用法:
    python wake-listener.py [--config ../config.json]
    # 后台运行：pythonw wake-listener.py ...（无窗口）
"""

import os
import sys
import time
import signal
import argparse
import threading
import numpy as np

# Windows UTF-8
if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

import sounddevice as sd
from faster_whisper import WhisperModel

# ============================================================
# 配置
# ============================================================
SKILL_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_CONFIG = os.path.join(SKILL_DIR, "..", "config.json")
HF_MIRROR = "https://hf-mirror.com"

# 信号文件路径（QClaw 读取此文件获知唤醒事件）
SIGNAL_FILE = os.path.join(SKILL_DIR, "..", ".wake_signal")

# 唤醒词列表
WAKE_PHRASES = ["嘿贾维斯", "嘿jarvis", "启动语音", "打开语音", "嘿qclaw", "hey jarvis"]

# 颜色
C_GRAY = "\033[90m"
C_GREEN = "\033[92m"
C_YELLOW = "\033[93m"
C_RESET = "\033[0m"

def log(text):
    ts = time.strftime("%H:%M:%S")
    print(f"{C_GRAY}[{ts}]{C_RESET} {text}", flush=True)

# ============================================================
# 发送唤醒信号
# ============================================================
def send_wake_signal(phrase=""):
    """通知 QClaw：被唤醒了"""
    with open(SIGNAL_FILE, "w", encoding="utf-8") as f:
        f.write(phrase)
    log(f"{C_GREEN}[WAKE] 唤醒信号已发送 -> {phrase}{C_RESET}")

# ============================================================
# PowerShell 执行（通知 QClaw）
# ============================================================
def notify_qclaw():
    """通过 PowerShell 发送 Windows 通知，告知用户语音助手已就绪"""
    script = '''
Add-Type -AssemblyName System.Windows.Forms
$notify = New-Object System.Windows.Forms.NotifyIcon
$notify.Icon = [System.Drawing.SystemIcons]::Application
$notify.Visible = $true
$notify.ShowBalloonTip(3000, "VoicePilot", "嘿！我在呢，请说话...", "Info")
'''
    try:
        import subprocess
        subprocess.run(
            ["powershell", "-ExecutionPolicy", "Bypass", "-Command", script],
            capture_output=True, timeout=5
        )
    except Exception:
        pass  # 通知失败不影响主流程

# ============================================================
# 音频录制 + VAD
# ============================================================
def listen_for_wake(model_path=None, model_name="tiny", device_id=1,
                    sample_rate=16000, energy_threshold=0.02,
                    wake_phrase_duration=1.5):
    """
    持续监听，检测到唤醒词时触发 send_wake_signal + notify_qclaw。
    检测到唤醒后函数返回，调用方负责重启监听。
    """
    buf_samples = int(sample_rate * 0.1)
    wake_buffer = int(sample_rate * wake_phrase_duration)  # 唤醒词最长1.5秒
    silence_timeout = int(sample_rate * 3)  # 3秒静默则放弃当前唤醒词

    buffer = np.array([], dtype=np.float32)
    silence_count = 0
    is_capturing = False
    capture_start_time = None

    log(f"{C_GRAY}[INIT] 唤醒监听已启动，设备 {device_id}{C_RESET}")

    def audio_callback(indata, frames, time_info, status):
        nonlocal buffer, silence_count, is_capturing, capture_start_time

        if status:
            return

        chunk = indata[:, 0].astype(np.float32)
        rms = np.sqrt(np.mean(chunk ** 2))

        if rms > energy_threshold:
            # 有声音，添加到缓冲
            buffer = np.concatenate([buffer, chunk])
            silence_count = 0
            is_capturing = True
            capture_start_time = time.time()
        else:
            if is_capturing:
                silence_count += frames
                total_samples = len(buffer)
                total_duration = total_samples / sample_rate

                # 停顿超时，尝试识别
                if silence_count >= silence_timeout or total_duration > 3.0:
                    if len(buffer) >= wake_buffer:
                        # 缓冲够长，尝试识别唤醒词
                        audio_copy = buffer.copy()
                        # 在子线程做识别，不阻塞音频线程
                        threading.Thread(
                            target=check_wake_phrase,
                            args=(audio_copy, sample_rate, model_name),
                            daemon=True
                        ).start()

                    # 重置
                    buffer = np.array([], dtype=np.float32)
                    silence_count = 0
                    is_capturing = False
            else:
                silence_count = 0

    stream = sd.InputStream(
        samplerate=sample_rate,
        channels=1,
        dtype="float32",
        device=device_id,
        blocksize=buf_samples,
        callback=audio_callback
    )

    with stream:
        while True:
            time.sleep(0.3)

# ============================================================
# 唤醒词识别（子线程）
# ============================================================
def check_wake_phrase(audio_data, sample_rate, model_name):
    """对捕获的音频片段进行识别，检查是否包含唤醒词"""
    try:
        model = WhisperModel(model_name, device="cpu", compute_type="int8")
        segments, _ = model.transcribe(
            audio_data,
            language="zh",
            beam_size=1,
            vad_filter=False,
        )
        text = "".join([s.text for s in segments]).strip()
        log(f"{C_GRAY}[VAD] 识别到: {text}{C_RESET}")

        if not text:
            return

        # 检查是否匹配唤醒词（模糊匹配）
        text_lower = text.lower().replace(" ", "")
        for phrase in WAKE_PHRASES:
            if phrase in text_lower or text_lower in phrase:
                log(f"{C_GREEN}[WAKE] 唤醒词匹配: {phrase}{C_RESET}")
                send_wake_signal(phrase)
                notify_qclaw()
                return

    except Exception as e:
        log(f"[ERR] 唤醒词识别失败: {e}")

# ============================================================
# 主入口
# ============================================================
def main():
    parser = argparse.ArgumentParser(description="VoicePilot 唤醒词监听")
    parser.add_argument("--config", default=DEFAULT_CONFIG)
    args = parser.parse_args()

    os.environ.setdefault("HF_ENDPOINT", HF_MIRROR)

    # 加载配置获取设备ID
    device_id = 1
    model_name = "tiny"
    try:
        import json
        with open(args.config, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        device_id = cfg.get("mic", {}).get("device", 1)
        model_name = cfg.get("whisper", {}).get("model", "tiny")
    except Exception:
        pass

    log(f"[START] VoicePilot 唤醒监听器启动")
    log(f"[INFO] 唤醒词: {', '.join(WAKE_PHRASES)}")
    log(f"[INFO] 设备: {device_id} | 模型: {model_name}")

    # Ctrl+C 优雅退出
    def signal_handler(sig, frame):
        log("[STOP] 唤醒监听已停止")
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # 主循环：被唤醒后重启监听
    while True:
        try:
            listen_for_wake(
                device_id=device_id,
                model_name=model_name,
            )
        except Exception as e:
            log(f"[ERR] 监听异常: {e}，3秒后重启...")
            time.sleep(3)

if __name__ == "__main__":
    main()
