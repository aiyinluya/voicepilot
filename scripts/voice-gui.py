"""
VoicePilot 主界面 — customtkinter 重构版
"""
import os, sys, json, time, subprocess, threading, queue
import numpy as np
import sounddevice as sd
from faster_whisper import WhisperModel
import customtkinter as ctk

# ============================================================
SKILL_DIR   = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(SKILL_DIR, "..", "config.json")
HF_MIRROR   = "https://hf-mirror.com"
WAKE_PHRASES = ["嘿贾维斯", "嘿jarvis", "启动语音", "打开语音", "嘿qclaw", "hey jarvis"]

# 颜色常量
C_BG      = "#0d1117"
C_SURFACE = "#161b22"
C_BORDER  = "#21262d"
C_TEXT    = "#e6edf3"
C_DIM     = "#8b949e"
C_GREEN   = "#3fb950"
C_YELLOW  = "#d29922"
C_RED     = "#f85149"
C_BLUE    = "#58a6ff"
C_PURPLE  = "#bc8cff"

# ============================================================
def load_config(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def check_wake(text):
    tn = text.lower().replace(" ", "").replace("\u3000", "")
    for p in WAKE_PHRASES:
        pn = p.lower().replace(" ", "").replace("\u3000", "")
        if pn in tn or tn in pn:
            return p
    return None

def send_keys(key_str):
    script = os.path.join(SKILL_DIR, "window.ps1")
    try:
        r = subprocess.run(
            ["powershell", "-ExecutionPolicy", "Bypass", "-File", script,
             "-Action", "keys", "-Keys", key_str],
            capture_output=True, timeout=10,
            creationflags=subprocess.CREATE_NO_WINDOW
        )
        return r.returncode == 0
    except Exception:
        return False

def activate_app(app_name):
    script = os.path.join(SKILL_DIR, "window.ps1")
    try:
        r = subprocess.run(
            ["powershell", "-ExecutionPolicy", "Bypass", "-File", script,
             "-Action", "activate", "-app", app_name],
            capture_output=True, timeout=10,
            creationflags=subprocess.CREATE_NO_WINDOW
        )
        return r.returncode == 0
    except Exception:
        return False

def to_simplified(text):
    pairs = [
        ('開','开'),('關','关'),('識別','识别'),('標籤','标签'),
        ('監','监'),('聽','听'),('語音','语音'),('們','们'),
        ('時','时'),('間','间'),('請','请'),('說','说'),
        ('話','话'),('對','对'),('為','为'),('過','过'),
        ('進','进'),('號','号'),('種','种'),
    ]
    for t, s in pairs:
        text = text.replace(t, s)
    return text

# ============================================================
class WaveCanvas(ctk.CTkCanvas):
    """实时波形显示，60fps"""
    def __init__(self, master, height=150, **kwargs):
        super().__init__(master, height=height, **kwargs)
        self.configure(bg=C_BG, highlightthickness=0, bd=0)
        self.height   = height
        self.data     = []
        self.max_pts  = 300
        self.rms_h    = []
        self.max_rms  = 50
        self._schedule()

    def push(self, chunk):
        rms = float(np.sqrt(np.mean(chunk ** 2)))
        self.rms_h.append(rms)
        if len(self.rms_h) > self.max_rms:
            self.rms_h.pop(0)
        step = max(1, len(chunk) // self.max_pts)
        self.data = chunk[::step].tolist()

    def _schedule(self):
        self._draw()
        if self.winfo_exists():
            self.after(50, self._schedule)

    def _draw(self):
        self.delete("all")
        w = self.winfo_width() or 640
        h = self.height
        cx = w / 2

        if self.rms_h:
            latest = self.rms_h[-1]
            bw  = min(int(latest * 250), w)
            col = C_GREEN if latest < 0.6 else C_YELLOW if latest < 0.85 else C_RED
            # tkinter 不支持 RGBA，用半透明多边形代替
            self.create_polygon(0, 0, bw, 0, bw, h, 0, h, fill=col, outline="")

        self.create_line(0, h/2, w, h/2, fill=C_BORDER, width=1)

        if self.data:
            n = len(self.data)
            xs = [int(i * w / max(n-1, 1)) for i in range(n)]
            for i in range(n-1):
                y0 = max(1, min(h-1, int(h/2 - self.data[i]   * h * 0.45)))
                y1 = max(1, min(h-1, int(h/2 - self.data[i+1] * h * 0.45)))
                self.create_line(xs[i], y0, xs[i+1], y1, fill=C_BLUE, width=2)

# ============================================================
def cframe(parent, **kw):
    return ctk.CTkFrame(parent, fg_color=kw.get("fg", C_SURFACE), corner_radius=12)

def clabel(parent, text, **kw):
    lb = ctk.CTkLabel(
        parent,
        text=text,
        font=kw.get("font", ("微软雅黑", kw.get("size", 12))),
        text_color=kw.get("color", C_DIM),
        anchor=kw.get("anchor", "w"),
        justify=kw.get("justify", "left"),
        wraplength=kw.get("wrap", 0)
    )
    # 间距由 .pack(padx=..., pady=...) 控制
    return lb

def cbtn(parent, text, cmd, **kw):
    return ctk.CTkButton(
        parent,
        text=text,
        font=kw.get("font", ("微软雅黑", 11)),
        width=kw.get("width", 80),
        height=kw.get("height", 36),
        command=cmd,
        fg_color=kw.get("fg", C_BORDER),
        hover_color=kw.get("hover", "#30363d"),
        text_color=kw.get("color", C_TEXT),
        corner_radius=6
    )

# ============================================================
class VoicePilotApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")

        self.cfg     = load_config(CONFIG_PATH)
        self.mic_cfg = self.cfg.get("mic", {})
        self.wy_cfg  = self.cfg.get("whisper", {})
        self.cmds    = self.cfg.get("commands", {})

        self.model        = None
        self.is_listening = False
        self.is_woken     = False
        self.last_seen    = time.time()
        self.start_time   = time.time()
        self.audio_q      = queue.Queue(maxsize=20)

        self.title("VoicePilot 语音开发助理")
        self.geometry("1100x740")
        self.resizable(False, False)
        self.configure(fg_color=C_BG)

        self._build_ui()
        self._load_model_async()
        self._tick()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.mainloop()

    # ------------------------------------------------------------------ UI
    def _build_ui(self):
        # === 标题栏 ===
        header = ctk.CTkFrame(self, height=72, fg_color=C_SURFACE)
        header.pack(fill="x")
        header.pack_propagate(False)

        self.orb = ctk.CTkCanvas(header, width=48, height=48,
                                   bg=C_SURFACE, highlightthickness=0)
        self.orb.create_oval(4, 4, 44, 44, fill=C_DIM, outline=C_DIM, width=2)
        self.orb.create_text(24, 24, text="🎤", font=("Segoe UI Emoji", 20))
        self.orb.pack(side="left", padx=20, pady=12)

        title_col = ctk.CTkFrame(header, fg_color="transparent")
        title_col.pack(side="left", pady=12)
        clabel(title_col, "VoicePilot",
               font=("微软雅黑", 20, "bold"), color=C_TEXT, padx=8, pady=0).pack(anchor="w")
        clabel(title_col, "动嘴不动手 · 语音开发助理",
               size=10, color=C_DIM, padx=8, pady=0).pack(anchor="w")

        st_col = ctk.CTkFrame(header, fg_color="transparent")
        st_col.pack(side="right", padx=20, pady=12)
        self.state_title = clabel(st_col, "未启动", font=("微软雅黑", 13, "bold"),
                                  color=C_DIM, anchor="e", padx=0, pady=2)
        self.state_title.pack(anchor="e")
        self.state_sub = clabel(st_col, "点击开始监听",
                                size=9, color="#484f58", anchor="e", padx=0, pady=0)
        self.state_sub.pack(anchor="e")

        # === 主区 ===
        main = ctk.CTkFrame(self, fg_color=C_BG)
        main.pack(fill="both", expand=True, padx=16, pady=(8, 16))
        main.columnconfigure(0, weight=4)
        main.columnconfigure(1, weight=3)

        # -- 左列 --
        left = ctk.CTkFrame(main, fg_color="transparent")
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 8))

        # 波形
        wfc = cframe(left)
        wfc.pack(fill="x", pady=(0, 8))
        clabel(wfc, "🔊  实时波形", size=12, color=C_DIM,
               anchor="w", padx=16, pady=(12, 0)).pack(fill="x")
        self.wave = WaveCanvas(wfc, height=150)
        self.wave.pack(fill="x", padx=12, pady=(0, 12))

        # 状态指标
        inc = cframe(left)
        inc.pack(fill="x", pady=(0, 8))
        clabel(inc, "📊  状态指标", size=12, color=C_DIM,
               anchor="w", padx=16, pady=(12, 0)).pack(fill="x")

        self.ind_labels = {}
        ind_grid = ctk.CTkFrame(inc, fg_color="transparent")
        ind_grid.pack(fill="x", padx=12, pady=(0, 12))
        for i, (t, v, col) in enumerate([
            ("🎙 麦克风",   "就绪",    C_DIM),
            ("📡 模式",     "等待唤醒", C_DIM),
            ("⏱ 运行时长", "0:00",    C_DIM),
            ("📝 最后指令", "—",       C_DIM),
        ]):
            cell = ctk.CTkFrame(ind_grid, fg_color=C_BG, corner_radius=8)
            cell.grid(row=0, column=i, padx=4, sticky="ew")
            ind_grid.columnconfigure(i, weight=1)
            clabel(cell, t, size=9, color="#484f58").pack(anchor="center", pady=2)
            lb = clabel(cell, v, size=11, color=col, pady=(2,8))
            lb.pack(anchor="center")
            self.ind_labels[t.split(" ", 1)[1]] = lb

        # 识别结果
        rc = cframe(left)
        rc.pack(fill="x", pady=(0, 8))
        clabel(rc, "[CLIP] 识别内容", size=12, color=C_DIM,
               anchor="w", padx=16, pady=(12, 0)).pack(fill="x")

        # 识别文字 + 复制按钮同行
        rb = ctk.CTkFrame(rc, fg_color="transparent")
        rb.pack(fill="x", padx=12, pady=(0, 12))
        rb.pack_info = dict  # dummy

        self.recog_tb = ctk.CTkTextbox(
            rb, height=80,
            font=("微软雅黑", 14),
            fg_color="#0d1117", text_color="#e6edf3",
            border_width=1, border_color="#21262d",
            corner_radius=8,
            scrollbar_button_color="#21262d",
            activate_scrollbars=False,
        )
        self.recog_tb.insert("0.0", "等待语音输入...")
        self.recog_tb.configure(state="disabled")
        self.recog_tb.pack(side="left", fill="x", expand=True, padx=(0, 8))

        def copy_recog():
            txt = self.recog_tb.get("0.0", "end").strip()
            if txt and txt != "等待语音输入...":
                self.clipboard_clear()
                self.clipboard_append(txt)
                self.update()
                self._hist_add(f"[COPY] {txt[:30]}{'...' if len(txt)>30 else ''}", C_BLUE)

        cbtn(rb, "复制", copy_recog, width=72, height=78,
             fg="#21262d", hover="#30363d",
             color=C_TEXT).pack(side="right", fill="y")

        # 快捷按钮
        qc = cframe(left)
        qc.pack(fill="x", pady=(0, 0))
        clabel(qc, "⚡  快捷指令（点击直接执行）",
               size=12, color=C_DIM, anchor="w", padx=16, pady=(12, 0)).pack(fill="x")
        qf = ctk.CTkFrame(qc, fg_color="transparent")
        qf.pack(fill="x", padx=12, pady=(0, 12))
        for i, (lb, key) in enumerate([
            ("新标签", "^t"), ("关标签", "^w"), ("保存", "^s"),
            ("撤销", "^z"), ("复制", "^c"), ("粘贴", "^v"),
            ("浏览器", "browser"), ("Cursor", "cursor"),
        ]):
            cbtn(qf, lb, lambda k=key, l=lb: self._quick(l, k),
                 width=70, height=34
                 ).grid(row=0, column=i, padx=3, pady=4)

        # -- 右列 --
        right = ctk.CTkFrame(main, fg_color="transparent")
        right.grid(row=0, column=1, sticky="nsew", padx=(8, 0))

        # 命令历史
        hc = cframe(right)
        hc.pack(fill="both", expand=True, pady=(0, 8))
        clabel(hc, "[CLIP] 命令历史（点击复制）", size=12, color=C_DIM,
               anchor="w", padx=16, pady=(12, 0)).pack(fill="x")
        self.hist_f = ctk.CTkScrollableFrame(
            hc, fg_color="transparent",
            scrollbar_button_color=C_BORDER, label_text=""
        )
        self.hist_f.pack(fill="both", expand=True, padx=12, pady=(0, 12))
        self.hist_items = []
        self._hist_add("欢迎使用 VoicePilot 👋", C_DIM)

        # 使用指南
        gc = cframe(right)
        gc.pack(fill="x", pady=(0, 0))
        clabel(gc, "📖  使用指南", size=12, color=C_BLUE,
               anchor="w", padx=16, pady=(12, 0)).pack(fill="x")
        guide_text = (
            "【操作步骤】\n"
            "① 点击「开始监听」按钮\n"
            "② 对着麦克风说话，音量条跳动\n"
            "③ 说唤醒词 → 进入命令模式\n"
            "④ 说指令 → 自动执行\n\n"
            "【唤醒词】\n"
            "嘿贾维斯 · 嘿Jarvis · 启动语音 · 打开语音\n\n"
            "【常用指令】\n"
            "新标签 · 关标签 · 保存 · 撤销 · 复制 · 粘贴\n"
            "切到浏览器 · 切到Cursor · 往下 · 往上\n\n"
            "【状态颜色】\n"
            "🟢 绿色 = 命令模式 / 执行成功\n"
            "🟡 黄色 = 识别中 / 执行中\n"
            "🔴 红色 = 未识别 / 执行失败\n"
            "🔵 蓝色 = 等待唤醒"
        )
        clabel(gc, guide_text, size=10, color=C_DIM,
               anchor="nw", justify="left", wrap=320,
               padx=16, pady=(0, 12)).pack(fill="x")

        # === 底部控制栏 ===
        footer = ctk.CTkFrame(self, height=80, fg_color=C_SURFACE)
        footer.pack(fill="x")
        footer.pack_propagate(False)
        ft = ctk.CTkFrame(footer, fg_color="transparent")
        ft.pack(fill="both", expand=True, padx=20, pady=12)

        self.main_btn = ctk.CTkButton(
            ft, text="▶  开始监听",
            font=("微软雅黑", 15, "bold"),
            width=180, height=48,
            command=self._toggle,
            fg_color="#1f6feb", hover_color="#388bfd",
            text_color="white", corner_radius=10
        )
        self.main_btn.pack(side="left", pady=4)

        info_lb = clabel(
            ft,
            f"模型: {self.wy_cfg.get('model','base')}  ·  "
            f"设备: {self.mic_cfg.get('device',1)}  ·  "
            f"阈值: {self.mic_cfg.get('silence_threshold',0.02)}",
            size=9, color="#484f58", anchor="w"
        )
        info_lb.pack(side="left", padx=16, fill="x", expand=True)

        ctk.CTkButton(
            ft, text="■ 停止",
            font=("微软雅黑", 13, "bold"),
            width=90, height=44,
            command=self._stop,
            fg_color=C_BORDER, hover_color="#30363d",
            text_color=C_DIM, corner_radius=8
        ).pack(side="left", padx=(0, 8))

        ctk.CTkButton(
            ft, text="✕ 退出",
            font=("微软雅黑", 13),
            width=80, height=44,
            command=self._on_close,
            fg_color="#3d1515", hover_color="#6e2424",
            text_color=C_RED, corner_radius=8
        ).pack(side="right")

    # ------------------------------------------------------------------ 辅助
    def _orb(self, icon, color):
        self.orb.delete("all")
        self.orb.create_oval(4, 4, 44, 44, fill=color, outline=color, width=2)
        self.orb.create_text(24, 24, text=icon, font=("Segoe UI Emoji", 20))

    def _hist_add(self, text, color=C_DIM):
        import time as _time
        ts = _time.strftime("%H:%M")
        full = f"[{ts}] {text}"

        # 外层 Frame：可点击
        item_f = ctk.CTkFrame(self.hist_f, fg_color="transparent", cursor="hand2")
        item_f.pack(fill="x", pady=1)
        item_f.bind("<Button-1>", lambda e, t=text: self._copy_hist(t))
        item_f.bind("<Enter>", lambda e, f=item_f: f.configure(fg_color="#1f2128"))
        item_f.bind("<Leave>", lambda e, f=item_f: f.configure(fg_color="transparent"))

        # 时间戳
        ts_lb = ctk.CTkLabel(
            item_f, text=f"[{ts}]", font=("微软雅黑", 8),
            text_color="#484f58", width=42, anchor="w"
        )
        ts_lb.pack(side="left", padx=(2, 4))

        # 文字标签
        lb = ctk.CTkLabel(
            item_f, text=text, font=("微软雅黑", 10),
            text_color=color, anchor="w", justify="left"
        )
        lb.pack(side="left", fill="x", expand=True)

        # 复制图标
        cp = ctk.CTkLabel(
            item_f, text="[copy]",
            font=("微软雅黑", 8),
            text_color="#484f58", cursor="hand2",
            width=40
        )
        cp.pack(side="right", padx=(0, 2))
        cp.bind("<Button-1>", lambda e, t=text, l=lb: self._copy_hist(t))
        cp.bind("<Enter>", lambda e, c=cp: c.configure(text_color=C_BLUE))
        cp.bind("<Leave>", lambda e, c=cp: c.configure(text_color="#484f58"))

        self.hist_items.append(item_f)
        if len(self.hist_items) > 30:
            old = self.hist_items.pop(0)
            old.destroy()

    def _copy_hist(self, text):
        self.clipboard_clear()
        self.clipboard_append(text)
        self.update()
        self._hist_add(f"[COPIED]", C_BLUE)

    def _set_state(self, icon, title, sub, color):
        self._orb(icon, color)
        self.state_title.configure(text=title, text_color=color)
        self.state_sub.configure(text=sub)

    # ------------------------------------------------------------------ 模型
    def _load_model_async(self):
        def run():
            try:
                os.environ.setdefault("HF_ENDPOINT", HF_MIRROR)
                mn = self.wy_cfg.get("model", "base")
                t0 = time.time()
                self.model = WhisperModel(
                    mn,
                    device=self.wy_cfg.get("device", "cpu"),
                    compute_type=self.wy_cfg.get("compute_type", "int8")
                )
                self.after(0, lambda: self._on_model_loaded(t0, mn))
            except Exception as e:
                self.after(0, lambda: self._set_state("❌", "加载失败", str(e)[:40], C_RED))
                self.after(0, lambda: self._hist_add(f"模型加载失败: {e}", C_RED))
        threading.Thread(target=run, daemon=True).start()

    def _on_model_loaded(self, t0, mn):
        self._set_state("✅", "就绪", f"Whisper {mn} 加载完成 ({t0:.1f}s)", C_GREEN)
        self._hist_add(f"✅ 模型加载完成 ({t0:.1f}s)", C_GREEN)

    # ------------------------------------------------------------------ 开关
    def _toggle(self):
        if self.is_listening:
            self._stop()
        else:
            self._start()

    def _start(self):
        if self.model is None:
            self._hist_add("⚠ 模型未加载，请稍候...", C_YELLOW)
            return
        self.is_listening = True
        self._set_state("🟢", "监听中", "等待唤醒词...", C_GREEN)
        self.ind_labels["麦克风"].configure(text="监听中", text_color=C_GREEN)
        self.ind_labels["模式"].configure(text="等待唤醒", text_color=C_YELLOW)
        self.main_btn.configure(text="⏹  监听中...", fg_color=C_GREEN, hover_color="#3fb950")
        self._hist_add("🎙 开始监听，等待语音...", C_GREEN)
        threading.Thread(target=self._listen_loop, daemon=True).start()

    def _stop(self):
        self.is_listening = False
        self.is_woken = False
        self._set_state("🔵", "已停止", "点击开始监听", C_DIM)
        self.ind_labels["麦克风"].configure(text="就绪", text_color=C_DIM)
        self.ind_labels["模式"].configure(text="已停止", text_color=C_DIM)
        self.main_btn.configure(text="▶  开始监听", fg_color="#1f6feb", hover_color="#388bfd")
        self._hist_add("⏹ 监听已停止", C_DIM)

    # ------------------------------------------------------------------ 音频
    def _listen_loop(self):
        cfg  = self.mic_cfg
        sr   = cfg.get("sample_rate", 16000)
        dev  = cfg.get("device", 1)
        thr  = cfg.get("silence_threshold", 0.02)
        min_ = cfg.get("min_phrase_seconds", 0.5)
        sil_ = cfg.get("silence_seconds", 1.5)
        buf  = 1024

        ring = np.array([], dtype=np.float32)
        sil  = 0
        spk  = False

        def cb(indata, frames, t_info, status):
            nonlocal ring, sil, spk
            chunk = indata[:, 0].astype(np.float32)
            rms   = np.sqrt(np.mean(chunk ** 2))

            if self.is_listening:
                try:
                    self.audio_q.put_nowait(chunk)
                except queue.Full:
                    pass

            if rms > thr:
                ring = np.concatenate([ring, chunk])
                sil  = 0
                spk  = True
                self.last_seen = time.time()
            else:
                if spk:
                    sil += frames
                    if sil >= int(sr * sil_):
                        dur = len(ring) / sr
                        if dur >= min_ and len(ring) > 0:
                            audio = ring.copy()
                            ring  = np.array([], dtype=np.float32)
                            spk   = False
                            self._transcribe(audio)
                        else:
                            ring = np.array([], dtype=np.float32)
                            spk  = False
                else:
                    sil = 0

        try:
            with sd.InputStream(samplerate=sr, channels=1, dtype="float32",
                               device=dev, blocksize=buf, callback=cb):
                while self.is_listening:
                    time.sleep(0.05)
        except Exception as e:
            self.after(0, lambda: self._hist_add(f"❌ 音频错误: {e}", C_RED))

    # ------------------------------------------------------------------ 识别
    def _transcribe(self, audio):
        def run():
            try:
                segs, _ = self.model.transcribe(
                    audio, language="zh",
                    task="transcribe",
                    beam_size=5, best_of=5,
                    patience=1.0, temperature=0.0,
                    condition_on_previous_text=False,
                    initial_prompt="以下是普通话的句子。"
                )
                text = to_simplified("".join(s.text for s in segs).strip())

                def show():
                    if text:
                        self.recog_tb.configure(state="normal")
                        self.recog_tb.delete("0.0", "end")
                        self.recog_tb.insert("0.0", text)
                        self.recog_tb.configure(state="disabled", text_color=C_TEXT)
                        self._hist_add(f"识别: {text}", C_BLUE)
                        self.ind_labels["麦克风"].configure(text="识别中", text_color=C_BLUE)
                    else:
                        self._hist_add("(未识别到内容)", C_DIM)

                self.after(0, show)
                if not text:
                    return

                wake = check_wake(text)
                if wake:
                    self.is_woken = True
                    def wake_ui():
                        self._set_state("🟡", "命令模式", f"唤醒: {wake}", C_YELLOW)
                        self.ind_labels["模式"].configure(text="命令模式", text_color=C_YELLOW)
                        self._hist_add(f"🎉 唤醒成功: {wake}", C_GREEN)
                    self.after(0, wake_ui)
                    return

                if self.is_woken:
                    self._do_cmd(text)
            except Exception as e:
                self.after(0, lambda: self._hist_add(f"❌ 识别错误: {e}", C_RED))

        threading.Thread(target=run, daemon=True).start()

    def _do_cmd(self, text):
        self.is_woken = False
        matched = None
        for k, v in self.cmds.items():
            if k in text or text in k:
                matched = (k, v)
                break

        if matched:
            k, v = matched
            action = v.get("action", "keys")
            val    = v.get("keys") or v.get("app", "")

            def ui1():
                self.ind_labels["麦克风"].configure(text="执行中", text_color=C_YELLOW)
                self.ind_labels["最后指令"].configure(text=k[:10], text_color=C_YELLOW)
                self._hist_add(f"⚡ 执行: {k}", C_YELLOW)

            self.after(0, ui1)

            ok = False
            if action == "keys":
                ok = send_keys(val)
            elif action == "app":
                ok = activate_app(val)

            def ui2():
                col = C_GREEN if ok else C_RED
                label = k + (" ✓" if ok else " ✗")
                self._set_state("🟢", "命令模式", label, col)
                self.ind_labels["麦克风"].configure(text="命令模式", text_color=C_GREEN)
                self.ind_labels["最后指令"].configure(text=k[:10], text_color=col)
                self._hist_add(label, col)
                if not ok:
                    self._hist_add(f"⚠ 执行失败", C_RED)

            self.after(0, ui2)
        else:
            def ui3():
                self._hist_add(f"⚠ 未知指令: {text[:15]!r}", C_YELLOW)
                send_keys("^v")
                self._hist_add(f"已粘贴: {text[:20]}...", C_BLUE)

            self.after(0, ui3)

    def _quick(self, label, key):
        self._hist_add(f"⚡ 快捷: {label}", C_BLUE)
        if key in ["browser", "cursor"]:
            activate_app(key)
        else:
            send_keys(key)

    # ------------------------------------------------------------------ 定时
    def _tick(self):
        chunks = []
        if self.is_listening:
            while True:
                try:
                    chunks.append(self.audio_q.get_nowait())
                except queue.Empty:
                    break
            if chunks:
                self.wave.push(np.concatenate(chunks))

        if self.is_listening:
            e = int(time.time() - self.start_time)
            m, s = divmod(e, 60)
            self.ind_labels["运行时长"].configure(text=f"{m}:{s:02d}")

        if self.is_woken and (time.time() - self.last_seen) > 300:
            self.is_woken = False
            self._set_state("🟢", "监听中", "5分钟超时，已退出命令模式", C_GREEN)
            self.ind_labels["模式"].configure(text="超时", text_color=C_DIM)

        self.after(60, self._tick)

    def _on_close(self):
        self.is_listening = False
        self.after(200, self.destroy)

# ============================================================
if __name__ == "__main__":
    VoicePilotApp()
