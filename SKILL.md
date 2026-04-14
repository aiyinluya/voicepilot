# VoiceDev Skill — 語音驅動開發助理

> 用意圖說話，就能控制窗口、切換應用、執行鍵盤快捷鍵。雙手不離鍵盤。

## 功能一覽

- 🎤 **語音指令 → 窗口控制**：切換軟件、打開標籤、關閉標籤
- ⌨️ **語音指令 → 快捷鍵發送**：Ctrl+T、Ctrl+W、Ctrl+Tab 等
- ⌨️ **語音輸入**：說話直接變成文字，輸入到當前焦點窗口
- 🔇 **靜默待機**：持續後台監聽，無需每次點擊
- ⚡ **意圖識別**：指令（切窗口）和普通輸入（打字）自動分流

## 指令詞典（可在 config.json 自定義）

### 窗口切換

| 指令 | 效果 |
|------|------|
| 切到 Cursor / 去 Cursor | 激活 Cursor 窗口 |
| 切到 Claude / 去 Claude | 激活 Claude Code（終端） |
| 切到瀏覽器 / 去瀏覽器 | 激活瀏覽器 |
| 切終端 | 切到集成終端面板 |
| 回編輯器 | 切回主編輯區 |

### 標籤操作

| 指令 | 快捷鍵 |
|------|--------|
| 新標籤 | Ctrl+T |
| 關標籤 / 關閉 | Ctrl+W |
| 下一個 / 右邊 | Ctrl+Tab |
| 上一个 / 左邊 | Ctrl+Shift+Tab |
| 第一個 ~ 第八個 | Ctrl+1 ~ Ctrl+8 |

### 滾動與導航

| 指令 | 快捷鍵 |
|------|--------|
| 往下 / 向下 | PageDown |
| 往上 / 向上 | PageUp |
| 文件總覽 / 大綱 | Ctrl+Shift+O |

### 通用編輯

| 指令 | 快捷鍵 |
|------|--------|
| 保存 | Ctrl+S |
| 撤銷 | Ctrl+Z |
| 重做 | Ctrl+Y / Ctrl+Shift+Z |
| 全選 | Ctrl+A |
| 複製 | Ctrl+C |
| 粘貼 | Ctrl+V |
| 查找 | Ctrl+F |
| 替換 | Ctrl+H |

### 模式切換

| 指令 | 效果 |
|------|------|
| 打字模式 | 識別結果直接輸入到當前窗口 |
| 命令模式 | 識別結果作為指令執行（默認） |
| 停止監聽 | 停止後台監聽 |

## 架構

```
話 → [麥克風] → [Whisper 語音識別] → [意圖分類]
                                          ↓
                    是指令？ → commander.py → window.ps1
                    是文字？ → 直接粘貼到當前窗口
```

## 依賴組件

| 組件 | 用途 | 安裝 |
|------|------|------|
| faster-whisper | 語音識別（本地，無需 API） | 首次運行自動下載 |
| sounddevice | 音頻錄製 | pip install sounddevice |
| PyAudio | 音頻後端 | pip install pyaudio |
| PowerShell | 窗口管理 + 快捷鍵發送 | Windows 內置 |

## 快速開始

### 方式一：一句話啟動

```
「打開語音模式」
「開始監聽」
「語音模式」
```

### 方式二：讓 OpenClaw 代你啟動

```
start voice-dev
```

### 運行流程

1. 腳本後台啟動，持續監聽麥克風
2. 檢測到語音 → Whisper 識別為文字
3. 文字 vs 指令詞典匹配：
   - **匹配到指令** → 執行對應快捷鍵或窗口切換
   - **未匹配** → 將文字粘貼到當前焦點窗口
4. 無按鍵中斷時，持續監聽下一句

## 配置文件說明（config.json）

```jsonc
{
  "mic": {
    "device": 1,              // 麥克風設備索引，-1=默認
    "sample_rate": 16000,     // 採樣率（不改）
    "channels": 1,            // 單聲道（不改）
    "silence_threshold": 0.01, // 停頓閾值，低於此值認為停頓
    "min_phrase_seconds": 0.5, // 最小說話時長（秒），過短忽略
    "silence_seconds": 1.5    // 停頓多久認為說完了
  },
  "whisper": {
    "model": "tiny",          // 模型：tiny/base/small/medium
    "language": "zh",         // 識別語言，zh=中文
    "device": "cpu"           // cpu 或 cuda
  },
  "apps": {
    // 軟件別名 → 軟件配置
    "cursor":  { "process": "Cursor.exe" },
    "claude":  { "process": "WindowsTerminal.exe" },
    "browser": { "process": "msedge.exe" }
  },
  "commands": {
    // 指令 → 執行動作
    "新標籤": { "action": "keys", "keys": "^t" },
    "關標籤": { "action": "keys", "keys": "^w" }
  },
  "hotwords": {
    // 熱詞觸發命令模式（不加熱詞時進入打字模式）
    "命令": "command",
    "指令": "command"
  }
}
```

## 模型選擇建議

| 模型 | 參數量 | 速度 | 準確率 | 磁盤佔用 |
|------|--------|------|--------|----------|
| tiny | 39M | ⚡⚡⚡ | ★★ | ~72 MB |
| base | 74M | ⚡⚡ | ★★★ | ~140 MB |
| small | 244M | ⚡ | ★★★★ | ~465 MB |
| medium | 769M | 🔄 | ★★★★★ | ~1.5 GB |

首次運行自動下載模型。建議先從 `tiny` 開始，確認流暢後換 `base` 提升準確率。

## 疑難排解

**Q: 識別不到聲音**
→ 檢查 config.json 中 `mic.device` 是否為正確的麥克風索引

**Q: 窗口切換無效**
→ 確認軟件進程名與 config.json 中一致，可在 PowerShell 中執行 `Get-Process` 確認

**Q: 按鍵發送混亂**
→ 有些軟件捕獲了系統熱鍵，可改用 `window.ps1` 中的 `SendKeysAbstraction` 層，或直接模擬鼠標點擊坐標
