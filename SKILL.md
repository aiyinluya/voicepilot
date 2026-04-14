# VoicePilot Skill — QClaw 语音控制

> 嘿 Jarvis → QClaw 苏醒 → 随时说话 → 执行命令 → 可随时打断

## 触发方式

**文字触发：**
- "打开语音" / "开启语音" / "语音控制" / "开始监听"
- "关闭语音" / "停止监听" / "退出语音"

**语音触发：**
- 说"嘿 Jarvis"唤醒 → 自动开启语音模式

## 工作原理

```
wake-listener.py（后台常驻）
    ↓ 检测到唤醒词
.wake_signal 文件被写入
    ↓
QClaw Skill 读取信号
    ↓
启动 voice-agent.py（子进程）
    ↓
持续监听麦克风 → 识别 → 执行 → 回复
    ↓
用户说"退出" → 停止 voice-agent.py
```

## 快捷键指令

### 窗口切换

| 你说 | 效果 |
|------|------|
| 切到浏览器 / 去浏览器 | 激活 Edge |
| 切到 cursor / 去 cursor | 激活 Cursor |
| 切到 claude / 去 claude | 激活 Windows Terminal |
| 切终端 | 切换到集成终端 |
| 回编辑器 | 切换回主编辑区 |

### 快捷键

| 你说 | 执行 |
|------|------|
| 新标签 | Ctrl+T |
| 关闭 | Ctrl+W |
| 保存 | Ctrl+S |
| 复制 / 粘贴 | Ctrl+C / Ctrl+V |
| 撤销 / 重做 | Ctrl+Z / Ctrl+Y |
| 全选 | Ctrl+A |
| 查找 | Ctrl+F |
| 替换 | Ctrl+H |
| 下一个 / 上一个 | Ctrl+Tab / Ctrl+Shift+Tab |
| 往下 / 往上 | PageDown / PageUp |
| 大纲 / 总览 | Ctrl+Shift+O |
| 回车 / 确定 / 取消 / 退出 | Enter / Esc |

### 文字输入
说任何不在指令表里的内容 → 直接粘贴到当前窗口

## 使用流程

**Step 1：启动后台唤醒监听（一次性）**
```powershell
cd C:\Users\liz-an\.qclaw\workspace\voice-dev-skill\scripts
set HF_ENDPOINT=https://hf-mirror.com
python wake-listener.py
```
（可以加 `pythonw` 变成无窗口后台运行，或用任务计划程序开机自启）

**Step 2：唤醒 QClaw**
- 喊"嘿 Jarvis"或"打开语音"
- QClaw 回复"好的，已开启语音模式，请说话"

**Step 3：发出指令**
- 随意说话，QClaw 识别后执行

**Step 4：说"退出"结束语音模式**

## 文件说明

| 文件 | 作用 |
|------|------|
| `wake-listener.py` | 唤醒词检测（后台常驻） |
| `voice-agent.py` | 语音会话子进程（QClaw 启动） |
| `window.ps1` | 窗口控制和快捷键执行 |
| `config.json` | 指令词典（可自定义） |
| `.wake_signal` | 唤醒信号文件（自动生成） |

## 依赖安装

```powershell
pip install faster-whisper sounddevice -i https://mirrors.aliyun.com/pypi/simple/
```

## 自定义指令

编辑 `config.json` 中的 `commands` 区块，添加你自己的指令：

```json
"commands": {
    "我的指令": { "action": "keys", "keys": "^s" }
}
```

`action` 支持：
- `keys` — 发送快捷键
- `app` — 切换应用（在 `apps` 中定义）
- `type` — 粘贴文字
