"""
voice-agent.py — QClaw 语音会话（QClaw 的子进程）
==================================================
由 QClaw 启动，持续监听麦克风 → 识别 → 执行 → 返回结果

用法（由 QClaw 调用）:
    python voice-agent.py --config ../config.json

输出格式（stdout）：
    [LISTENING]                    <- 开始监听
    [HEARD] <text>                 <- 识别到内容
    [EXEC] <command> <keys>         <- 执行快捷键
    [ACTIVATE] <app>               <- 切换窗口
    [TYPE] <text>                  <- 粘贴文字
    [DONE] <result_text>           <- 完成，QClaw 显示给用户
    [EXIT]                         <- 退出语音模式
"""

import os
import sys
import json
import time
import signal
import subprocess
import numpy as np
import sounddevice as sd
from faster_whisper import WhisperModel

# ============================================================
# 配置
# ============================================================
SKILL_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_CONFIG = os.path.join(SKILL_DIR, "..", "config.json")
HF_MIRROR = "https://hf-mirror.com"

# ============================================================
# 工具函数
# ============================================================
def log(text):
    ts = time.strftime("%H:%M:%S")
    print(f"[{ts}] {text}", flush=True, file=sys.stderr)

def out(tag, value=""):
    """输出结构化行到 stdout（QClaw 解析）"""
    if value:
        print(f"[{tag}] {value}", flush=True)
    else:
        print(f"[{tag}]", flush=True)

# ============================================================
# PowerShell 执行
# ============================================================
def run_ps(action, **kwargs):
    script_path = os.path.join(SKILL_DIR, "window.ps1")
    args = ["powershell", "-ExecutionPolicy", "Bypass", "-File", script_path, "-Action", action]
    for k, v in kwargs.items():
        if v is not None:
            args.extend([f"-{k}", str(v)])

    try:
        result = subprocess.run(
            args, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=5
        )
        if result.stdout.strip():
            try:
                return json.loads(result.stdout.strip())
            except Exception:
                return {"raw": result.stdout.strip()}
        return {}
    except Exception as e:
        return {"error": str(e)}

# ============================================================
# 指令匹配
# ============================================================
def match_command(text, config):
    """返回 (matched: bool, action_type, action_detail)"""
    commands = config.get("commands", {})
    text = text.strip()
    if not text:
        return False, None, None

    # 精确匹配
    if text in commands:
        return True, commands[text].get("action"), commands[text]

    # 前缀匹配
    for key, cmd in commands.items():
        if text.startswith(key) or text.endswith(key):
            return True, cmd.get("action"), cmd

    # 部分匹配
    for key, cmd in commands.items():
        if key in text:
            return True, cmd.get("action"), cmd

    return False, None, None

# ============================================================
# 执行动作
# ============================================================
def execute_action(action_type, action_detail, config):
    script_path = os.path.join(SKILL_DIR, "window.ps1")

    if action_type == "keys":
        keys = action_detail.get("keys", "")
        result = run_ps("sendkeys", Keys=keys)
        if result.get("success"):
            return f"已发送快捷键: {keys}"
        return f"快捷键发送失败: {result.get('error', 'unknown')}"

    elif action_type == "app":
        app_name = action_detail.get("app", "")
        app_cfg = config.get("apps", {}).get(app_name, {})
        result = run_ps(
            "activate",
            ProcessName=app_cfg.get("process", ""),
            AppTitle=app_cfg.get("title", "")
        )
        if result.get("success"):
            return f"已切换到 {app_name}"
        return f"切换 {app_name} 失败: {result.get('error', 'unknown')}"

    return "未知动作类型"

# ============================================================
# 退出检测
# ============================================================
EXIT_WORDS = ["退出", "停止", "取消", "关闭语音", "退出语音", "停止语音", "算了", "exit", "quit", "stop"]

def is_exit(text):
    t = text.strip().lower()
    for w in EXIT_WORDS:
        if w in t:
            return True
    return False

# ============================================================
# 语音会话主循环
# ============================================================
def voice_session(config, model):
    mic_cfg = config["mic"]
    sample_rate = mic_cfg.get("sample_rate", 16000)
    channels = mic_cfg.get("channels", 1)
    device = mic_cfg.get("device", 1)
    silence_thr = mic_cfg.get("silence_threshold", 0.02)
    silence_dur_samples = int(sample_rate * mic_cfg.get("silence_seconds", 1.5))

    buf_samples = int(sample_rate * 0.1)
    ring_buf = np.array([], dtype=np.float32)
    silence_count = 0
    is_speaking = False
    phrase_started = False
    phrase_start_time = None

    out("LISTENING")

    def audio_callback(indata, frames, time_info, status):
        nonlocal ring_buf, silence_count, is_speaking, phrase_started, phrase_start_time

        if status:
            return

        chunk = indata[:, 0].astype(np.float32)
        rms = np.sqrt(np.mean(chunk ** 2))

        if rms > silence_thr:
            ring_buf = np.concatenate([ring_buf, chunk])
            silence_count = 0
            if not phrase_started:
                phrase_started = True
                phrase_start_time = time.time()
            is_speaking = True
        else:
            if is_speaking:
                silence_count += frames
                if silence_count >= silence_dur_samples / (frames / sample_rate):
                    is_speaking = False
                    duration = time.time() - (phrase_start_time or time.time())
                    min_dur = mic_cfg.get("min_phrase_seconds", 0.5)
                    if duration >= min_dur and len(ring_buf) > 0:
                        audio_copy = ring_buf.copy()
                        # 在子线程处理，不阻塞音频线程
                        handle_audio(audio_copy, model, config)
                    ring_buf = np.array([], dtype=np.float32)
                    silence_count = 0
                    phrase_started = False
            else:
                silence_count = 0

    stream = sd.InputStream(
        samplerate=sample_rate, channels=channels,
        dtype="float32", device=device,
        blocksize=buf_samples, callback=audio_callback
    )

    try:
        with stream:
            while True:
                time.sleep(0.3)
    except KeyboardInterrupt:
        out("EXIT")

# ============================================================
# 处理识别结果
# ============================================================
def handle_audio(audio_data, model, config):
    try:
        segments, _ = model.transcribe(
            audio_data,
            language=config["whisper"].get("language", "zh"),
            beam_size=1,
            vad_filter=False,
        )
        text = "".join([s.text for s in segments]).strip()
        if not text:
            return

        out("HEARD", text)

        # 检查退出
        if is_exit(text):
            out("EXIT")
            time.sleep(0.5)
            sys.exit(0)

        # 匹配指令
        matched, action_type, action_detail = match_command(text, config)

        if matched:
            out("EXEC", f"{action_type} -> {action_detail}")
            result = execute_action(action_type, action_detail, config)
            out("DONE", result)
        else:
            # 非指令内容 -> 粘贴
            out("TYPE", text)
            script_path = os.path.join(SKILL_DIR, "window.ps1")
            run_ps("paste", Text=text)
            out("DONE", f"已粘贴文字: {text[:20]}{'...' if len(text) > 20 else ''}")

    except Exception as e:
        out("ERROR", str(e))

# ============================================================
# 主入口
# ============================================================
def main():
    config_path = os.environ.get("VOICEPILOT_CONFIG", DEFAULT_CONFIG)

    # 加载配置
    with open(config_path, "r", encoding="utf-8") as f:
        config = json.load(f)

    os.environ.setdefault("HF_ENDPOINT", HF_MIRROR)

    # 加载模型
    wcfg = config.get("whisper", {})
    model_name = wcfg.get("model", "tiny")
    device = wcfg.get("device", "cpu")
    compute_type = wcfg.get("compute_type", "int8")

    log(f"加载模型: {model_name}")
    model = WhisperModel(model_name, device=device, compute_type=compute_type)
    log("模型加载完成")

    # 信号处理
    def signal_handler(sig, frame):
        out("EXIT")
        sys.exit(0)
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # 开始语音会话
    out("READY")
    voice_session(config, model)

if __name__ == "__main__":
    main()
