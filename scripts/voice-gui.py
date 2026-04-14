"""
voice-gui.py — VoicePilot 可视化界面 v2
=========================================
功能：实时音量可视化 + 唤醒词检测 + 语音识别 + 执行反馈

使用方式:
    python voice-gui.py --config ../config.json
"""

import os, sys, json, time, subprocess, threading, signal as _signal
import numpy as np
import sounddevice as sd
from faster_whisper import WhisperModel

import tkinter as tk
from tkinter import font as tkfont

# ============================================================
# 配置
# ============================================================
SKILL_DIR   = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(SKILL_DIR, "..", "config.json")
HF_MIRROR   = "https://hf-mirror.com"

# 唤醒词列表（需与 wake-listener.py 保持一致）
WAKE_PHRASES = ["嘿贾维斯", "嘿jarvis", "启动语音", "打开语音", "嘿qclaw", "hey jarvis"]

# ============================================================
# 颜色主题
# ============================================================
BG        = "#0d1117"
SURFACE   = "#161b22"
BORDER    = "#30363d"
TEXT      = "#e6edf3"
DIM       = "#8b949e"
GREEN     = "#3fb950"
RED       = "#f85149"
YELLOW    = "#d29922"
PURPLE    = "#bc8cff"
BLUE      = "#58a6ff"

# ============================================================
# 工具函数
# ============================================================
def log(msg):
    ts = time.strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)

def check_wake(text):
    text_norm = text.lower().replace(" ", "").replace("\u3000", "")
    for phrase in WAKE_PHRASES:
        phrase_norm = phrase.lower().replace(" ", "").replace("\u3000", "")
        if phrase_norm in text_norm or text_norm in phrase_norm:
            return phrase
    return None

def run_powershell(script_path):
    """安全执行 PowerShell 脚本，返回 (success, output)"""
    try:
        r = subprocess.run(
            ["powershell", "-ExecutionPolicy", "Bypass", "-File", script_path],
            capture_output=True, text=True, timeout=15
        )
        out = r.stdout.strip()
        ok = r.returncode == 0 and "false" not in out.lower()
        return ok, out
    except Exception as e:
        return False, str(e)

def send_keys(keys_str):
    """通过 window.ps1 发送快捷键"""
    script = os.path.join(SKILL_DIR, "window.ps1")
    r = subprocess.run(
        ["powershell", "-ExecutionPolicy", "Bypass", "-File", script,
         "-action", "keys", "-keys", keys_str],
        capture_output=True, text=True, timeout=10
    )
    return r.returncode == 0

def activate_app(app_name):
    """通过 window.ps1 激活应用"""
    script = os.path.join(SKILL_DIR, "window.ps1")
    r = subprocess.run(
        ["powershell", "-ExecutionPolicy", "Bypass", "-File", script,
         "-action", "activate", "-app", app_name],
        capture_output=True, text=True, timeout=10
    )
    return r.returncode == 0

# ============================================================
# 主应用
# ============================================================
class VoicePilotApp:
    def __init__(self, config_path):
        with open(config_path, "r", encoding="utf-8") as f:
            self.cfg = json.load(f)
        self.mic_cfg  = self.cfg.get("mic", {})
        self.wy_cfg   = self.cfg.get("whisper", {})
        self.cmds     = self.cfg.get("commands", {})

        # 运行时状态
        self.model          = None
        self.stream         = None
        self.is_running    = False
        self.is_woken       = False    # 是否已唤醒（进入命令模式）
        self.ring_buf       = np.array([], dtype=np.float32)
        self.silence_count  = 0
        self.is_speaking    = False
        self.current_rms    = 0.0
        self.last_activity  = time.time()
        self.cmd_history    = []       # 最近执行的命令

        # 日志行（显示在滚动 text widget 里）
        self.log_lines = []
        self.max_log   = 50

        # 加载模型（异步）
        self._load_model_async()

        # ---- Tk 窗口 ----
        self.root = tk.Tk()
        self.root.title("VoicePilot — 语音开发助理")
        self.root.configure(bg=BG)
        self.root.geometry("520x680")
        self.root.resizable(False, False)
        self._build_ui()

        # 定期更新 UI
        self.root.after(80, self._ui_tick)

        # 优雅退出
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.mainloop()

    # ------------------------------------------------------------------ UI 构建
    def _build_ui(self):
        container = tk.Frame(self.root, bg=BG)
        container.pack(fill=tk.BOTH, expand=True, padx=20, pady=16)

        # ---- 标题栏 ----
        title_frame = tk.Frame(container, bg=BG)
        title_frame.pack(fill=tk.X, pady=(0, 14))

        tk.Label(title_frame, text="🎤 VoicePilot",
                 font=tkfont.Font(size=18, weight="bold"), fg=TEXT, bg=BG
                 ).pack(side=tk.LEFT)

        self.status_chip = tk.Label(
            title_frame, text="⏳ 加载模型…",
            font=tkfont.Font(size=10), fg=BG, bg=YELLOW,
            padx=10, pady=3, relief=tk.GROOVE, bd=2
        )
        self.status_chip.pack(side=tk.RIGHT)

        sep(container, BORDER).pack(fill=tk.X, pady=(0, 14))

        # ---- 主状态卡片 ----
        card = tk.Frame(container, bg=SURFACE, relief=tk.GROOVE, bd=1)
        card.pack(fill=tk.X, pady=(0, 14))

        # 状态行
        row = tk.Frame(card, bg=SURFACE)
        row.pack(fill=tk.X, padx=18, pady=(18, 4))
        tk.Label(row, text="状态", font=tkfont.Font(size=11), fg=DIM, bg=SURFACE
                 ).pack(side=tk.LEFT)
        self.state_label = tk.Label(
            row, text="🔴 已停止",
            font=tkfont.Font(size=13, weight="bold"), fg=RED, bg=SURFACE
        )
        self.state_label.pack(side=tk.RIGHT)

        sep(card, BORDER).pack(fill=tk.X, padx=18, pady=4)

        # 唤醒状态行
        row2 = tk.Frame(card, bg=SURFACE)
        row2.pack(fill=tk.X, padx=18, pady=4)
        tk.Label(row2, text="唤醒", font=tkfont.Font(size=11), fg=DIM, bg=SURFACE
                 ).pack(side=tk.LEFT)
        self.wake_label = tk.Label(
            row2, text="等待唤醒…",
            font=tkfont.Font(size=11), fg=DIM, bg=SURFACE
        )
        self.wake_label.pack(side=tk.RIGHT)

        sep(card, BORDER).pack(fill=tk.X, padx=18, pady=4)

        # 最后命令行
        row3 = tk.Frame(card, bg=SURFACE)
        row3.pack(fill=tk.X, padx=18, pady=(4, 18))
        tk.Label(row3, text="命令", font=tkfont.Font(size=11), fg=DIM, bg=SURFACE
                 ).pack(side=tk.LEFT)
        self.cmd_label = tk.Label(
            row3, text="—",
            font=tkfont.Font(size=11), fg=DIM, bg=SURFACE
        )
        self.cmd_label.pack(side=tk.RIGHT)

        # ---- 音量条 ----
        vol_frame = tk.Frame(container, bg=SURFACE, relief=tk.GROOVE, bd=1)
        vol_frame.pack(fill=tk.X, pady=(0, 14))

        tk.Label(vol_frame, text="🔊 音量", font=tkfont.Font(size=11), fg=DIM,
                 bg=SURFACE
                 ).pack(anchor=tk.W, padx=18, pady=(12, 4))

        self.vol_canvas = tk.Canvas(vol_frame, height=32, bg=BG,
                                    highlightthickness=0)
        self.vol_canvas.pack(fill=tk.X, padx=18, pady=(0, 12))
        self.vol_bg    = self.vol_canvas.create_rectangle(0, 0, 9999, 32, fill="#1c2128")
        self.vol_bar   = self.vol_canvas.create_rectangle(0, 0, 0, 32, fill=GREEN)
        self.vol_text  = self.vol_canvas.create_text(8, 16, text="0%", anchor=tk.W,
                                                      fill=TEXT, font=tkfont.Font(size=10))

        # ---- 识别结果 ----
        recog_frame = tk.Frame(container, bg=SURFACE, relief=tk.GROOVE, bd=1)
        recog_frame.pack(fill=tk.X, pady=(0, 14))

        tk.Label(recog_frame, text="🗣 识别内容",
                 font=tkfont.Font(size=11), fg=DIM, bg=SURFACE
                 ).pack(anchor=tk.W, padx=18, pady=(12, 6))

        self.recog_text = tk.Text(
            recog_frame, height=5, wrap=tk.WORD,
            font=tkfont.Font(size=13), fg=TEXT, bg=BG,
            relief=tk.FLAT, bd=0, padx=14, pady=10,
            insertbackground=TEXT,
            state=tk.DISABLED
        )
        self.recog_text.pack(fill=tk.X, padx=18, pady=(0, 12))

        # ---- 日志区域 ----
        log_frame = tk.Frame(container, bg=SURFACE, relief=tk.GROOVE, bd=1)
        log_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 14))

        tk.Label(log_frame, text="📋 日志",
                 font=tkfont.Font(size=11), fg=DIM, bg=SURFACE
                 ).pack(anchor=tk.W, padx=18, pady=(12, 6))

        self.log_widget = tk.Text(
            log_frame, height=7, wrap=tk.WORD,
            font=tkfont.Font(size=9), fg=DIM, bg=BG,
            relief=tk.FLAT, bd=0, padx=14, pady=8,
            state=tk.DISABLED
        )
        self.log_widget.pack(fill=tk.BOTH, expand=True, padx=18, pady=(0, 12))

        # ---- 控制按钮 ----
        btn_row = tk.Frame(container, bg=BG)
        btn_row.pack(fill=tk.X)

        self.toggle_btn = tk.Button(
            btn_row, text="▶ 开启监听",
            font=tkfont.Font(size=13, weight="bold"),
            width=16, height=2,
            command=self._toggle,
            bg="#0d419d", fg=TEXT, relief=tk.FLAT,
            activebackground="#1a6fd4", activeforeground=TEXT,
            cursor="hand2"
        )
        self.toggle_btn.pack(side=tk.LEFT, expand=True, fill=tk.X, padx=(0, 6))

        tk.Button(
            btn_row, text="✕ 退出",
            font=tkfont.Font(size=13, weight="bold"),
            width=8, height=2,
            command=self._on_close,
            bg="#6e1616", fg=TEXT, relief=tk.FLAT,
            activebackground="#9d2424", activeforeground=TEXT,
            cursor="hand2"
        ).pack(side=tk.RIGHT, fill=tk.X)

    # ------------------------------------------------------------------ 模型加载
    def _load_model_async(self):
        threading.Thread(target=self._do_load_model, daemon=True).start()

    def _do_load_model(self):
        try:
            os.environ.setdefault("HF_ENDPOINT", HF_MIRROR)
            model_name = self.wy_cfg.get("model", "tiny")
            self._append_log(f"加载模型 {model_name} …")
            t0 = time.time()
            self.model = WhisperModel(
                model_name,
                device=self.wy_cfg.get("device", "cpu"),
                compute_type=self.wy_cfg.get("compute_type", "int8")
            )
            self._append_log(f"✅ 模型加载完成 ({time.time()-t0:.1f}s)", GREEN)
            self.root.after(0, lambda: self.status_chip.config(
                text="✅ 已就绪", bg=GREEN, fg=BG))
        except Exception as e:
            self._append_log(f"❌ 模型加载失败: {e}", RED)
            self.root.after(0, lambda: self.status_chip.config(
                text="❌ 加载失败", bg=RED, fg=TEXT))

    # ------------------------------------------------------------------ 开关监听
    def _toggle(self):
        if self.is_running:
            self._stop()
        else:
            self._start()

    def _start(self):
        if self.model is None:
            self._append_log("⚠ 模型尚未加载，请稍候…", YELLOW)
            return
        self.is_running = True
        self._append_log("🎙 监听已开启（等待语音…）", GREEN)
        self.state_label.config(text="🟢 监听中", fg=GREEN)
        self.toggle_btn.config(text="⏹ 停止监听", bg="#c94444")
        self.status_chip.config(text="🟢 监听中", bg=GREEN, fg=BG)

        threading.Thread(target=self._listen_loop, daemon=True).start()

    def _stop(self):
        self.is_running = False
        self.is_woken   = False
        self._append_log("⏹ 监听已停止", DIM)
        self.state_label.config(text="🔴 已停止", fg=RED)
        self.wake_label.config(text="等待唤醒…", fg=DIM)
        self.toggle_btn.config(text="▶ 开启监听", bg="#0d419d")
        self.status_chip.config(text="✅ 已就绪", bg=GREEN, fg=BG)
        self.recog_clear()

    # ------------------------------------------------------------------ 音频循环
    def _listen_loop(self):
        cfg   = self.mic_cfg
        sr    = cfg.get("sample_rate", 16000)
        dev   = cfg.get("device", None)
        thr   = cfg.get("silence_threshold", 0.02)
        min_  = cfg.get("min_utterance_s", 0.3)
        sil_  = cfg.get("silence_gap_s", 1.5)

        buf_s = int(sr * 0.5)   # 每块 0.5s

        def callback(indata, frames, t_info, status):
            chunk = indata[:, 0].astype(np.float32)
            rms   = np.sqrt(np.mean(chunk ** 2))

            # 更新音量（主线程读取）
            self.current_rms = rms

            if rms > thr:
                self.ring_buf  = np.concatenate([self.ring_buf, chunk])
                self.silence_count = 0
                self.is_speaking   = True
                self.last_activity = time.time()
            else:
                if self.is_speaking:
                    self.silence_count += frames
                    min_samples = int(sr * min_)
                    if self.silence_count >= int(sr * sil_):
                        if len(self.ring_buf) >= min_samples:
                            audio = self.ring_buf.copy()
                            self.ring_buf = np.array([], dtype=np.float32)
                            self.is_speaking = False
                            self._transcribe_and_act(audio)
                        else:
                            self.ring_buf = np.array([], dtype=np.float32)
                            self.is_speaking = False

        try:
            with sd.InputStream(samplerate=sr, channels=1, dtype="float32",
                                device=dev, blocksize=buf_s,
                                callback=callback):
                while self.is_running:
                    time.sleep(0.1)
        except Exception as e:
            self._append_log(f"❌ 音频流错误: {e}", RED)

    # ------------------------------------------------------------------ 识别 + 执行
    def _transcribe_and_act(self, audio):
        lang  = self.wy_cfg.get("language", "zh")
        segs, _ = self.model.transcribe(audio, language=lang,
                                         beam_size=1, vad_filter=False)
        text  = "".join(s.text for s in segs).strip()
        self._show_recog(text)

        if not text:
            self._append_log("(未识别到内容)", DIM)
            return

        # 检查唤醒词
        wake = check_wake(text)
        if wake:
            self._on_wake(wake, text)
            return

        # 若已唤醒 → 执行命令
        if self.is_woken:
            self._execute(text)
        else:
            self._append_log(f"（未识别为唤醒词，忽略）", DIM)

    def _on_wake(self, phrase, text):
        self.is_woken = True
        self._append_log(f"🎉 唤醒！模式: 语音命令", GREEN)
        self.root.after(0, lambda: self.wake_label.config(
            text=f"🎙 命令模式", fg=YELLOW))
        self.root.after(0, lambda: self.state_label.config(
            text="🟡 唤醒状态", fg=YELLOW))

    def _execute(self, text):
        self.is_woken = False  # 每条命令单独确认
        matched_key = None
        for key, info in self.cmds.items():
            if key in text or text in key:
                matched_key = key
                break

        if matched_key:
            info = self.cmds[matched_key]
            action = info.get("action", "keys")
            value  = info.get("keys") or info.get("app", "")

            self._append_log(f"执行 [{matched_key}]  {action}={value}", GREEN)

            ok = False
            if action == "keys":
                ok = send_keys(value)
            elif action == "app":
                ok = activate_app(value)

            self.root.after(0, lambda _, k=matched_key, o=ok:
                self.cmd_label.config(text=k, fg=GREEN if o else RED))

            if not ok:
                self._append_log("⚠ 执行可能失败", YELLOW)
        else:
            self._append_log(f"⚠ 未知指令: {text!r}  → 粘贴文字", YELLOW)
            # 未匹配：粘贴文字
            send_keys("^v")

    # ------------------------------------------------------------------ UI 刷新
    def _ui_tick(self):
        # 音量条
        w = self.vol_canvas.winfo_width()
        if w > 0:
            vol_pct = min(self.current_rms * 25, 1.0)
            bw = int(w * vol_pct)
            self.vol_canvas.coords(self.vol_bar, 0, 0, bw, 32)
            self.vol_canvas.itemconfigure(self.vol_text,
                                          text=f"{int(vol_pct*100)}%")

            # 音量颜色
            color = GREEN if vol_pct < 0.7 else (YELLOW if vol_pct < 0.9 else RED)
            self.vol_canvas.itemconfigure(self.vol_bar, fill=color)

        # 5分钟无活动自动退出唤醒状态
        if self.is_woken and (time.time() - self.last_activity) > 300:
            self.is_woken = False
            self.root.after(0, lambda: self.wake_label.config(
                text="超时，已退出命令模式", fg=DIM))
            self.root.after(0, lambda: self.state_label.config(
                text="🟢 监听中", fg=GREEN))

        self.root.after(60, self._ui_tick)

    # ------------------------------------------------------------------ 日志 / 识别结果
    def _append_log(self, msg, color=DIM):
        ts   = time.strftime("%H:%M:%S")
        line = f"[{ts}] {msg}"
        self.log_lines.append((line, color))
        if len(self.log_lines) > self.max_log:
            self.log_lines.pop(0)

        def do():
            self.log_widget.config(state=tk.NORMAL)
            self.log_widget.insert(tk.END, line + "\n", color)
            self.log_widget.see(tk.END)
            self.log_widget.config(state=tk.DISABLED)
        try:
            self.root.after(0, do)
        except Exception:
            pass

    def _show_recog(self, text):
        def do():
            self.recog_text.config(state=tk.NORMAL)
            self.recog_text.delete("1.0", tk.END)
            self.recog_text.insert("1.0", text if text else "(空)")
            self.recog_text.config(state=tk.DISABLED)
        try:
            self.root.after(0, do)
        except Exception:
            pass

    def recog_clear(self):
        def do():
            self.recog_text.config(state=tk.NORMAL)
            self.recog_text.delete("1.0", tk.END)
            self.recog_text.insert("1.0", "等待语音…")
            self.recog_text.config(state=tk.DISABLED)
        try:
            self.root.after(0, do)
        except Exception:
            pass

    # ------------------------------------------------------------------ 退出
    def _on_close(self):
        self.is_running = False
        time.sleep(0.2)
        self.root.destroy()

# ============================================================
# 辅助
# ============================================================
def sep(parent, color):
    f = tk.Frame(parent, height=1, bg=color)
    return f

# ============================================================
# 主入口
# ============================================================
if __name__ == "__main__":
    cfg = CONFIG_PATH
    if not os.path.exists(cfg):
        print(f"[ERROR] 配置文件不存在: {cfg}")
        sys.exit(1)

    app = VoicePilotApp(cfg)
