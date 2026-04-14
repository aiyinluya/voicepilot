# VoiceDev Skill — 语音驱动开发助理

> 用意图说话，就能控制窗口、切换应用、执行键盘快捷键。双手不离键盘。

## 功能一览

- 🎤 **语音指令 -> 窗口控制**：切换软件、打开标签、关闭标签
- ⌨️ **语音指令 -> 快捷键发送**：Ctrl+T、Ctrl+W、Ctrl+Tab 等
- ⌨️ **语音输入**：说话直接变成文字，输入到当前焦点窗口
- 🔇 **静默待机**：持续后台监听，无需每次点击
- ⚡ **意图识别**：指令（切窗口）和普通输入（打字）自动分流

## 指令词典（可在 config.json 自定义）

### 窗口切换

| 指令 | 效果 |
|------|------|
| 切到 Cursor / 去 Cursor | 激活 Cursor 窗口 |
| 切到 Claude / 去 Claude | 激活 Claude Code（终端） |
| 切到浏览器 / 去浏览器 | 激活浏览器 |
| 切终端 | 切到集成终端面板 |
| 回编辑器 | 切回主编辑区 |

### 标签操作

| 指令 | 快捷键 |
|------|--------|
| 新标签 | Ctrl+T |
| 关标签 / 关闭 | Ctrl+W |
| 下一个 / 右边 | Ctrl+Tab |
| 上一个 / 左边 | Ctrl+Shift+Tab |
| 第一个 ~ 第八个 | Ctrl+1 ~ Ctrl+8 |

### 滚动与导航

| 指令 | 快捷键 |
|------|--------|
| 往下 / 向下 | PageDown |
| 往上 / 向上 | PageUp |
| 文件总览 / 大纲 | Ctrl+Shift+O |

### 通用编辑

| 指令 | 快捷键 |
|------|--------|
| 保存 | Ctrl+S |
| 撤销 | Ctrl+Z |
| 重做 | Ctrl+Y / Ctrl+Shift+Z |
| 全选 | Ctrl+A |
| 复制 | Ctrl+C |
| 粘贴 | Ctrl+V |
| 查找 | Ctrl+F |
| 替换 | Ctrl+H |

### 模式切换

| 指令 | 效果 |
|------|------|
| 打字模式 | 识别结果直接输入到当前窗口 |
| 命令模式 | 识别结果作为指令执行（默认） |
| 停止监听 | 停止后台监听 |

## 架构

```
话 -> [麦克风] -> [Whisper 语音识别] -> [意图分类]
                                         ↓
                    是指令？ -> commander.py -> window.ps1
                    是文字？ -> 直接粘贴到当前窗口
```

## 依赖组件

| 组件 | 用途 | 安装 |
|------|------|------|
| faster-whisper | 语音识别（本地，无需 API） | 首次运行自动下载 |
| sounddevice | 音频录制 | pip install sounddevice |
| PyAudio | 音频后端 | pip install pyaudio |
| PowerShell | 窗口管理 + 快捷键发送 | Windows 内置 |

## 快速开始

### 方式一：一句话启动

```
"打开语音模式"
"开始监听"
"语音模式"
```

### 方式二：让 OpenClaw 代你启动

```
start voice-dev
```

### 运行流程

1. 脚本后台启动，持续监听麦克风
2. 检测到语音 -> Whisper 识别为文字
3. 文字 vs 指令词典匹配：
   - **匹配到指令** -> 执行对应快捷键或窗口切换
   - **未匹配** -> 将文字粘贴到当前焦点窗口
4. 无按键中断时，持续监听下一句

## 配置文件说明（config.json）

```jsonc
{
  "mic": {
    "device": 1,              // 麦克风设备索引，-1=默认
    "sample_rate": 16000,     // 采样率（不改）
    "channels": 1,            // 单声道（不改）
    "silence_threshold": 0.01, // 停顿阈值，低于此值认为停顿
    "min_phrase_seconds": 0.5, // 最小说话时长（秒），过短忽略
    "silence_seconds": 1.5    // 停顿多久认为说完了
  },
  "whisper": {
    "model": "tiny",          // 模型：tiny/base/small/medium
    "language": "zh",         // 识别语言，zh=中文
    "device": "cpu"           // cpu 或 cuda
  },
  "apps": {
    // 软件别名 -> 软件配置
    "cursor":  { "process": "Cursor.exe" },
    "claude":  { "process": "WindowsTerminal.exe" },
    "browser": { "process": "msedge.exe" }
  },
  "commands": {
    // 指令 -> 执行动作
    "新标签": { "action": "keys", "keys": "^t" },
    "关标签": { "action": "keys", "keys": "^w" }
  },
  "hotwords": {
    // 热词触发命令模式（不加热词时进入打字模式）
    "命令": "command",
    "指令": "command"
  }
}
```

## 模型选择建议

| 模型 | 参数量 | 速度 | 准确率 | 磁盘占用 |
|------|--------|------|--------|----------|
| tiny | 39M | ⚡⚡⚡ | ★★ | ~72 MB |
| base | 74M | ⚡⚡ | ★★★ | ~140 MB |
| small | 244M | ⚡ | ★★★★ | ~465 MB |
| medium | 769M | 🔄 | ★★★★★ | ~1.5 GB |

首次运行自动下载模型。建议先从 `tiny` 开始，确认流畅后换 `base` 提升准确率。

## 疑难排解

**Q: 识别不到声音**
-> 检查 config.json 中 `mic.device` 是否为正确的麦克风索引

**Q: 窗口切换无效**
-> 确认软件进程名与 config.json 中一致，可在 PowerShell 中执行 `Get-Process` 确认

**Q: 按键发送混乱**
-> 有些软件捕获了系统热键，可改用 `window.ps1` 中的 `SendKeysAbstraction` 层，或直接模拟鼠标点击坐标
