# VoicePilot

> 用语音控制电脑 — 窗口切换、快捷键发送、文字输入。动嘴不动手。

## 功能

- 🎤 **语音驱动** — 实时语音识别，基于 faster-whisper
- 🖥️ **窗口控制** — 喊名字直接切换到目标应用
- ⌨️ **快捷键发送** — 复制、粘贴、标签页、搜索... 动口不动手
- 📝 **语音输入** — 非指令内容直接粘贴到当前窗口
- 🎨 **可视化界面** — 实时音量条 + 状态显示
- 🔧 **可配置** — 修改 `config.json` 即可添加新指令

## 截图

```
┌─────────────────────────────┐
│  🎤 语音开发助理             │
│                             │
│      🟢 监听中              │
│  ████████████░░░░░░░░░░░░   │
│                             │
│  识别: 切到浏览器            │
│                             │
│  [▶ 开启监听]  [退出]        │
└─────────────────────────────┘
```

## 支持的指令

### 窗口切换

| 你说 | 效果 |
|------|------|
| 切到 Cursor | 激活 Cursor 窗口 |
| 去浏览器 | 激活 Edge 浏览器 |
| 打开 VS Code | 激活 VS Code |

### 快捷键

| 你说 | 效果 |
|------|------|
| 新标签 / 关标签 | `Ctrl+T` / `Ctrl+W` |
| 复制 / 粘贴 | `Ctrl+C` / `Ctrl+V` |
| 保存 | `Ctrl+S` |
| 撤销 / 重做 | `Ctrl+Z` / `Ctrl+Y` |
| 全选 | `Ctrl+A` |
| 查找 | `Ctrl+F` |
| 关闭应用 | `Alt+F4` |

### 导航

| 你说 | 效果 |
|------|------|
| 上 / 下 / 左 / 右 | `↑` / `↓` / `←` / `→` |
| 往上 / 往下 | `PageUp` / `PageDown` |
| 回车 / 退出 / Tab | `Enter` / `Esc` / `Tab` |

> 完整指令列表见 `config.json`

## 安装

### 环境要求

- Python 3.9+
- Windows / macOS / Linux
- 麦克风

### 依赖安装

```bash
pip install faster-whisper sounddevice
```

> 中国大陆用户建议使用阿里云镜像：
> ```bash
> pip install faster-whisper sounddevice -i https://mirrors.aliyun.com/pypi/simple/
> ```

### Whisper 模型

首次运行会自动下载 `tiny` 模型（约 39MB）。

如需其他模型，修改 `config.json`：

```json
{
  "whisper": {
    "model": "base"  // tiny / base / small / medium / large
  }
}
```

## 使用

### GUI 版本（有界面，推荐）

```bash
cd scripts
python voice-gui.py
```

### 命令行版本

```bash
cd scripts
python listener.py --config ../config.json
```

### OpenClaw Skill 版本

如果你使用 [OpenClaw](https://github.com/openclaw/openclaw)，可以将此项目作为 Skill 安装：

```bash
# 复制到 OpenClaw skills 目录
cp -r voicepilot ~/.openclaw/workspace/skills/voicepilot
```

然后对 OpenClaw 说「开启语音」即可触发。

## 配置

编辑 `config.json` 自定义指令：

```json
{
  "commands": {
    "我的指令": {
      "action": "keys",
      "keys": "^s"
    }
  },
  "apps": {
    "我的应用": {
      "process": "myapp.exe",
      "title": "MyApp"
    }
  }
}
```

### action 类型

- `keys` — 发送快捷键
- `app` — 切换到指定应用
- `type` — 直接输入文字

## 技术栈

- [faster-whisper](https://github.com/guillaumekln/faster-whisper) — 语音识别
- [Sounddevice](https://python-sounddevice.readthedocs.io/) — 音频采集
- [Tkinter](https://docs.python.org/3/library/tkinter.html) — GUI 界面
- [PowerShell](https://docs.microsoft.com/powershell/) — Windows 窗口控制

## 开源协议

MIT License

## 贡献

欢迎提交 Issue 和 Pull Request！
