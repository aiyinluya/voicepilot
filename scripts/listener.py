"""
listener.py — 语音监听 + 意图识别 + 命令执行
===============================================
语音输入 → Whisper 识别 → 指令匹配 → PowerShell/WScript 执行

用法:
    python listener.py [--config config.json]
"""

import os
import sys
import json
import time
import signal
import argparse
import subprocess
import numpy as np

# Windows UTF-8 编码修复
if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

# 音频
import sounddevice as sd

# 语音识别
from faster_whisper import WhisperModel

# ============================================================
# 配置
# ============================================================
SKILL_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_CONFIG = os.path.join(SKILL_DIR, "config.json")
HF_MIRROR = "https://hf-mirror.com"

# ============================================================
# 颜色配置（终端显示）
# ============================================================
C_RESET  = "\033[0m"
C_GREEN  = "\033[92m"
C_YELLOW = "\033[93m"
C_BLUE   = "\033[94m"
C_GRAY   = "\033[90m"
C_BOLD   = "\033[1m"

# Emoji fallback for Windows GBK terminal
EMOJI_LOADING = "[*]"
EMOJI_OK      = "[+]"
EMOJI_MIC     = "[MIC]"
EMOJI_CMD     = "[CMD]"
EMOJI_ERROR   = "[!]"

def log(text, color=""):
    ts = time.strftime("%H:%M:%S")
    # Remove emojis for Windows compatibility
    text = text.replace("\U0001f50a", "MIC").replace("\U0001f680", "LOAD")
    text = text.replace("\U0001f4a5", "WAKE").replace("\U0001f3b2", "PLAY")
    text = text.replace("\U0001f4e9", "SEND").replace("\U0001f4a4", "WAIT")
    print(f"{C_GRAY}[{ts}]{C_RESET} {color}{text}{C_RESET}", flush=True)

def log_cmd(cmd, keys=""):
    ts = time.strftime("%H:%M:%S")
    print(f"{C_GRAY}[{ts}]{C_RESET} {C_GREEN}CMD :{C_RESET} {C_BOLD}{cmd}{C_RESET}", end="", flush=True)
    if keys:
        print(f"  -> {C_YELLOW}{keys}{C_RESET}", flush=True)
    else:
        print(flush=True)

def log_txt(text):
    ts = time.strftime("%H:%M:%S")
    print(f"{C_GRAY}[{ts}]{C_RESET} {C_BLUE}TEXT:{C_RESET} {text}", flush=True)

def log_err(text):
    ts = time.strftime("%H:%M:%S")
    print(f"{C_GRAY}[{ts}]{C_RESET} {C_GRAY}ERR :{C_RESET} {C_RESET}{text}{C_RESET}", flush=True)

# ============================================================
# 配置加载
# ============================================================
def load_config(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

# ============================================================
# PowerShell 命令执行
# ============================================================
def run_ps(script_path, action, **kwargs):
    """执行 window.ps1，返回解析后的结果"""
    args = ["powershell", "-ExecutionPolicy", "Bypass", "-File", script_path, "-Action", action]
    for k, v in kwargs.items():
        if v is not None:
            args.extend([f"-{k}", str(v)])

    try:
        result = subprocess.run(
            args,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=5
        )
        if result.stdout.strip():
            try:
                return json.loads(result.stdout.strip())
            except Exception:
                return {"raw": result.stdout.strip()}
        if result.stderr:
            return {"stderr": result.stderr[:200]}
        return {}
    except subprocess.TimeoutExpired:
        return {"error": "PowerShell timeout"}
    except Exception as e:
        return {"error": str(e)}

# ============================================================
# 窗口激活
# ============================================================
def activate_app(script_path, app_name, apps_config):
    if app_name not in apps_config:
        log_err(f"未知应用: {app_name}")
        return

    app_cfg = apps_config[app_name]
    log_cmd(f"切换窗口 -> {app_name}", app_cfg.get("process", ""))

    result = run_ps(
        script_path, "activate",
        ProcessName=app_cfg.get("process", ""),
        AppTitle=app_cfg.get("title", "")
    )
    if result.get("success"):
        log(f"  [+] 已切换到 {app_name}")
    else:
        log_err(f"  [!] 切换失败: {result.get('error', 'unknown')}")

# ============================================================
# 快捷键发送
# ============================================================
def send_keys(script_path, keys):
    log_cmd("发送快捷键", keys)
    result = run_ps(script_path, "sendkeys", Keys=keys)
    if result.get("success"):
        log(f"  [+] 发送成功")
    else:
        log_err(f"  [!] 发送失败: {result.get('error', 'unknown')}")

# ============================================================
# 粘贴文字
# ============================================================
def paste_text(script_path, text):
    log_txt(text)

    result = run_ps(script_path, "paste", Text=text)
    if result.get("success"):
        log(f"  [+] 已粘贴 {result.get('textLength', len(text))} 字符")
    else:
        log_err(f"  [!] 粘贴失败: {result.get('error', 'unknown')}")

# ============================================================
# 指令解析与执行
# ============================================================
def parse_and_execute(text, config, script_path):
    """
    根据配置匹配指令，执行对应动作。
    返回: True=执行了指令, False=未匹配（进入粘贴模式）
    """
    text = text.strip()
    if not text:
        return False

    commands = config.get("commands", {})
    hotwords = config.get("hotwords", {})

    # 精确匹配
    if text in commands:
        cmd = commands[text]
        action = cmd.get("action")
        if action == "keys":
            send_keys(script_path, cmd["keys"])
            return True
        elif action == "app":
            activate_app(script_path, cmd["app"], config.get("apps", {}))
            return True

    # 前缀匹配（支持"切到 Cursor""去 Cursor"等）
    for key, cmd in commands.items():
        if text.startswith(key) or text.endswith(key):
            action = cmd.get("action")
            if action == "keys":
                send_keys(script_path, cmd["keys"])
                return True
            elif action == "app":
                activate_app(script_path, cmd["app"], config.get("apps", {}))
                return True

    # 部分匹配（关键词包含）
    for key, cmd in commands.items():
        if key in text:
            action = cmd.get("action")
            if action == "keys":
                send_keys(script_path, cmd["keys"])
                return True
            elif action == "app":
                activate_app(script_path, cmd["app"], config.get("apps", {}))
                return True

    return False

# ============================================================
# 音频录制：持续监听，停顿时识别
# ============================================================
def listen_loop(config, model, script_path):
    mic_cfg     = config["mic"]
    sample_rate  = mic_cfg["sample_rate"]
    channels    = mic_cfg["channels"]
    device      = mic_cfg["device"]
    silence_thr = mic_cfg.get("silence_threshold", 0.01)
    min_phrase  = mic_cfg.get("min_phrase_seconds", 0.5)
    silence_dur = mic_cfg.get("silence_seconds", 1.5)

    # 缓冲配置
    buf_samples     = int(sample_rate * 0.1)  # 每块 100ms
    silence_samples = int(sample_rate * silence_dur)

    log(f"{C_BOLD}[MIC] 开始监听{C_RESET}", color=C_GREEN)
    log(f"  模型: {config['whisper']['model']} | 设备: {device} | 停顿阈值: {silence_thr}")
    log(f"  说指令词直接执行，说普通内容粘贴到当前窗口")
    log(f"  按 Ctrl+C 停止监听")
    log("-" * 50)

    ring_buf = np.array([], dtype=np.float32)  # 语音缓冲
    silence_count = 0
    is_speaking = False
    phrase_started = False
    phrase_start_time = None

    def audio_callback(indata, frames, time_info, status):
        nonlocal ring_buf, silence_count, is_speaking, phrase_started, phrase_start_time
        if status:
            pass  # 忽略警告

        chunk = indata[:, 0].astype(np.float32)
        rms = np.sqrt(np.mean(chunk ** 2))

        # 显示音频级别（每秒最多一次）
        if rms > silence_thr * 1.5:
            bar = "=" * int(min(rms * 50, 20))
            ts = time.strftime("%H:%M:%S")
            print(f"{C_GRAY}[{ts}]{C_RESET} MIC {bar} {rms:.3f}", flush=True)

        if rms > silence_thr:
            # 有声音
            ring_buf = np.concatenate([ring_buf, chunk])
            silence_count = 0
            if not phrase_started:
                phrase_started = True
                phrase_start_time = time.time()
            is_speaking = True
        else:
            # 停顿
            if is_speaking:
                silence_count += frames
                # 停顿超过阈值，认为一句话结束
                if silence_count >= silence_samples / (frames / sample_rate):
                    is_speaking = False
                    duration = time.time() - (phrase_start_time or time.time())
                    if duration >= min_phrase and len(ring_buf) > 0:
                        # 复制音频避免引用问题
                        audio_copy = ring_buf.copy()
                        # 触发识别（异步更好，这里同步以便控制线程）
                        try:
                            transcribe_and_execute(audio_copy, model, config, script_path)
                        except Exception as e:
                            log_err(f"识别错误: {e}")
                    # 重置
                    ring_buf = np.array([], dtype=np.float32)
                    silence_count = 0
                    phrase_started = False
            else:
                silence_count = 0

    # 录制流
    stream = sd.InputStream(
        samplerate=sample_rate,
        channels=channels,
        dtype="float32",
        device=device,
        blocksize=buf_samples,
        callback=audio_callback
    )

    with stream:
        while True:
            time.sleep(0.5)  # 主线程保持活跃

# ============================================================
# 转录 + 执行
# ============================================================
def transcribe_and_execute(audio_data, model, config, script_path):
    """在独立线程中运行 Whisper 识别，然后执行"""
    # 重新采样为 16000Hz（如需要）
    # faster-whisper 内部处理

    segments, _ = model.transcribe(
        audio_data,
        language=config["whisper"].get("language", "zh"),
        beam_size=1,
        vad_filter=False,
    )

    text = "".join([s.text for s in segments]).strip()

    if not text:
        return

    ts = time.strftime("%H:%M:%S")
    print(f"{C_GRAY}[{ts}]{C_RESET} {C_BOLD}>>> 听到:{C_RESET} {C_YELLOW}{text}{C_RESET}", flush=True)

    # 尝试匹配指令
    matched = parse_and_execute(text, config, script_path)

    if not matched:
        # 未匹配指令 -> 粘贴文字到当前窗口
        paste_text(script_path, text)

# ============================================================
# 主入口
# ============================================================
def main():
    parser = argparse.ArgumentParser(description="VoiceDev - 语音驱动开发助理")
    parser.add_argument("--config", default=DEFAULT_CONFIG)
    args = parser.parse_args()

    # 确保 HF 镜像可用
    os.environ.setdefault("HF_ENDPOINT", HF_MIRROR)

    # 加载配置
    if not os.path.exists(args.config):
        print(f"错误: 配置文件不存在: {args.config}", file=sys.stderr)
        sys.exit(1)

    config = load_config(args.config)
    script_path = os.path.join(SKILL_DIR, "window.ps1")

    # 加载 Whisper 模型
    wcfg = config.get("whisper", {})
    model_name  = wcfg.get("model", "tiny")
    device      = wcfg.get("device", "cpu")
    compute_type = wcfg.get("compute_type", "int8")

    log(f"{C_BOLD}[LOAD] 加载 Whisper 模型 ({model_name})...{C_RESET}", color=C_GRAY)

    try:
        model = WhisperModel(model_name, device=device, compute_type=compute_type)
    except Exception as e:
        log_err(f"模型加载失败: {e}")
        log("提示: 首次运行需下载模型，请确保网络畅通，或手动设置 HF_ENDPOINT 镜像")
        sys.exit(1)

    log(f"{C_GREEN}[+] 模型就绪{C_RESET}")

    # 测试麦克风
    mic_cfg = config.get("mic", {})
    dev_id = mic_cfg.get("device", None)

    try:
        devices = sd.query_devices()
        if dev_id is None:
            dev_id = sd.query_devices(kind="input")["index"]
        log(f"使用麦克风设备 {dev_id}: {sd.query_devices(dev_id)['name']}")
    except Exception as e:
        log_err(f"麦克风初始化失败: {e}")
        sys.exit(1)

    # Ctrl+C 优雅退出
    def signal_handler(sig, frame):
        print(f"\n{C_GRAY}[*] 监听已停止{C_RESET}")
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # 开始监听
    try:
        listen_loop(config, model, script_path)
    except KeyboardInterrupt:
        print(f"\n{C_GRAY}[*] 监听已停止{C_RESET}")

if __name__ == "__main__":
    main()
