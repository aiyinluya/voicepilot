"""
voice-gui.py — 语音监听状态可视化界面
=======================================
显示：监听状态、音量条、识别结果

用法:
    python voice-gui.py [--config ../config.json]
"""

import os
import sys
import json
import time
import argparse
import threading
import numpy as np
import sounddevice as sd
from faster_whisper import WhisperModel

# Tkinter GUI
import tkinter as tk
from tkinter import ttk

# ============================================================
# 配置
# ============================================================
SKILL_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_CONFIG = os.path.join(SKILL_DIR, "config.json")
HF_MIRROR = "https://hf-mirror.com"

# ============================================================
# GUI 应用
# ============================================================
class VoiceGUI:
    def __init__(self, config_path):
        self.config = self.load_config(config_path)
        self.model = None
        self.is_listening = False
        self.running = True
        
        # 创建窗口
        self.root = tk.Tk()
        self.root.title("🎤 语音开发助理")
        self.root.geometry("400x300")
        self.root.resizable(False, False)
        
        # 样式
        self.root.configure(bg="#1e1e1e")
        
        # 状态标签
        self.status_label = tk.Label(
            self.root, 
            text="🔴 未启动", 
            font=("微软雅黑", 24, "bold"),
            fg="#ff5555",
            bg="#1e1e1e"
        )
        self.status_label.pack(pady=20)
        
        # 音量条画布
        self.canvas = tk.Canvas(self.root, width=300, height=60, bg="#2d2d2d", highlightthickness=0)
        self.canvas.pack(pady=10)
        self.level_rect = self.canvas.create_rectangle(0, 0, 0, 60, fill="#4ec9b0")
        
        # 识别结果标签
        self.result_label = tk.Label(
            self.root,
            text="等待语音...",
            font=("微软雅黑", 14),
            fg="#cccccc",
            bg="#1e1e1e",
            wraplength=350
        )
        self.result_label.pack(pady=10)
        
        # 按钮框架
        btn_frame = tk.Frame(self.root, bg="#1e1e1e")
        btn_frame.pack(pady=20)
        
        self.toggle_btn = tk.Button(
            btn_frame,
            text="▶ 开启监听",
            font=("微软雅黑", 12),
            width=12,
            command=self.toggle_listening,
            bg="#0e639c",
            fg="white",
            relief="flat"
        )
        self.toggle_btn.pack(side=tk.LEFT, padx=10)
        
        self.quit_btn = tk.Button(
            btn_frame,
            text="退出",
            font=("微软雅黑", 12),
            width=8,
            command=self.quit,
            bg="#444444",
            fg="white",
            relief="flat"
        )
        self.quit_btn.pack(side=tk.LEFT, padx=10)
        
        # 音频变量
        self.current_level = 0
        
        # 启动更新循环
        self.root.protocol("WM_DELETE_WINDOW", self.quit)
        self.root.after(100, self.update)
        self.root.mainloop()
    
    def load_config(self, path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    
    def toggle_listening(self):
        if self.is_listening:
            self.stop_listening()
        else:
            self.start_listening()
    
    def start_listening(self):
        if self.is_listening:
            return
        
        # 加载模型（如果还没加载）
        if self.model is None:
            self.update_status("⏳ 加载模型中...", "#ffaa00")
            self.root.update()
            
            model_name = self.config["whisper"].get("model", "tiny")
            os.environ.setdefault("HF_ENDPOINT", HF_MIRROR)
            
            self.model = WhisperModel(
                model_name,
                device=self.config["whisper"].get("device", "cpu"),
                compute_type=self.config["whisper"].get("compute_type", "int8")
            )
        
        # 启动监听线程
        self.is_listening = True
        self.thread = threading.Thread(target=self.listen_loop, daemon=True)
        self.thread.start()
        
        self.update_status("🟢 监听中", "#4ec9b0")
        self.toggle_btn.config(text="⏹ 停止监听", bg="#c94444")
    
    def stop_listening(self):
        self.is_listening = False
        self.update_status("🔴 已停止", "#ff5555")
        self.toggle_btn.config(text="▶ 开启监听", bg="#0e639c")
        self.result_label.config(text="等待语音...")
    
    def update_status(self, text, color):
        self.status_label.config(text=text, fg=color)
    
    def listen_loop(self):
        mic_config = self.config["mic"]
        sample_rate = mic_config.get("sample_rate", 16000)
        channels = mic_config.get("channels", 1)
        device = mic_config.get("device", 1)
        silence_thr = mic_config.get("silence_threshold", 0.02)
        
        ring_buf = np.array([], dtype=np.float32)
        is_speaking = False
        silence_count = 0
        
        def audio_callback(indata, frames, time_info, status):
            nonlocal ring_buf, is_speaking, silence_count
            
            chunk = indata[:, 0].astype(np.float32)
            rms = np.sqrt(np.mean(chunk ** 2))
            
            # 更新音量显示
            self.current_level = min(rms * 20, 1.0)  # 缩放到 0-1
            
            if rms > silence_thr:
                ring_buf = np.concatenate([ring_buf, chunk])
                is_speaking = True
                silence_count = 0
            else:
                if is_speaking:
                    silence_count += frames
                    if silence_count > sample_rate * 0.5:  # 500ms 静音
                        if len(ring_buf) > sample_rate * 0.3:  # 至少 300ms
                            # 处理音频
                            self.process_audio(ring_buf.copy())
                        ring_buf = np.array([], dtype=np.float32)
                        is_speaking = False
        
        try:
            with sd.InputStream(
                samplerate=sample_rate,
                channels=channels,
                dtype="float32",
                device=device,
                blocksize=1024,
                callback=audio_callback
            ):
                while self.is_listening:
                    time.sleep(0.1)
        except Exception as e:
            self.root.after(0, lambda: self.result_label.config(text=f"错误: {e}"))
    
    def process_audio(self, audio_data):
        # 识别
        segments, _ = self.model.transcribe(
            audio_data,
            language=self.config["whisper"].get("language", "zh"),
            beam_size=1,
            vad_filter=False,
        )
        
        text = "".join([s.text for s in segments]).strip()
        
        if text:
            self.root.after(0, lambda: self.result_label.config(
                text=f"识别: {text}",
                fg="#4ec9b0"
            ))
            # 执行命令
            self.execute_command(text)
        else:
            self.root.after(0, lambda: self.result_label.config(
                text="未识别到内容",
                fg="#ffaa00"
            ))
    
    def execute_command(self, text):
        """执行命令"""
        commands = self.config.get("commands", {})
        
        # 精确匹配
        for cmd_phrase, cmd_config in commands.items():
            if cmd_phrase in text or text in cmd_phrase:
                self.root.after(0, lambda: self.result_label.config(
                    text=f"执行: {cmd_phrase}",
                    fg="#4ec9b0"
                ))
                return
        
        # 没匹配到命令
        self.root.after(0, lambda: self.result_label.config(
            text=f"粘贴: {text}",
            fg="#ffaa00"
        ))
    
    def update(self):
        """更新音量条"""
        if self.is_listening:
            # 绘制音量条
            width = int(self.current_level * 300)
            self.canvas.coords(self.level_rect, 0, 0, width, 60)
        
        self.root.after(50, self.update)
    
    def quit(self):
        self.running = False
        self.is_listening = False
        self.root.destroy()

# ============================================================
# 主入口
# ============================================================
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="VoiceDev GUI")
    parser.add_argument("--config", default=DEFAULT_CONFIG)
    args = parser.parse_args()
    
    if not os.path.exists(args.config):
        print(f"错误: 配置文件不存在: {args.config}")
        sys.exit(1)
    
    VoiceGUI(args.config)
