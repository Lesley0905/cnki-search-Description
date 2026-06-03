---
name: cnki-search
description: Search CNKI (中国知网) for Chinese academic literature. Opens a browser for manual CAPTCHA solving, then automatically searches and extracts paper citations in GB/T 7714 format. Requires user to have CNKI access (institutional IP or personal account).
author: Claw & Lesley
license: MIT
triggers:
  - 知网
  - CNKI
  - 中文文献
  - 核心期刊
  - 搜中文论文
  - 找中文文献
  - cnki search
  - Chinese papers
  - 国内研究现状
---

# CNKI Search — 知网文献检索

Browser-automated CNKI literature search. Compatible with **any agent** that can run shell commands (OpenClaw / Claude Code / Codex / Cursor / etc.).

Open-source project: https://github.com/Lesley0905/cnki-search

## Trigger Phrases
- "在知网上搜索关于 [主题] 的核心期刊论文"
- "帮我找几篇关于 [关键词] 的中文文献"
- "search CNKI for [topic] papers from core journals"
- "找中文核心期刊论文"

## Capabilities
- **Browser Automation**: Opens Chrome/Edge, waits for manual CAPTCHA, then back to auto
- **Abstract Extraction**: Visits each paper's detail page to extract Chinese/English abstracts (random 1.5–3 s delay between requests)
- **Default 5-year window**: Searches last 5 years unless overridden
- **All journal types**: Journal articles, dissertations, conference papers
- **Multi-format export**: Markdown, JSON, CSV, BibTeX (all include abstract field)
- **Core journal filter**: 北大核心 / CSSCI / CSCD
- **Multi-query batch mode**: Single CAPTCHA session, multiple searches
- **Deduplication**: Automatic across queries

## Prerequisites
- Python 3.10+ with `pip install selenium webdriver-manager`
- Chrome or Edge browser
- CNKI access (university IP/VPN or personal account)

## Usage

```bash
# Default: last 5 years, all journals
python -m cnki_search "玉米病害 YOLO 深度学习"

# Core journals, specific years
python -m cnki_search "农作物病害 目标检测" --core-only --years 2020-2025

# Batch mode
python -m cnki_search --batch examples/queries.json

# Export JSON + CSV
python -m cnki_search "深度学习 农业" --output-format md,json,csv
```

## Agent Integration

**任何能执行 shell 命令的 Agent 均可免终端调用。**

### 免终端原理（`--signal-file`）

脚本通过文件信号替代 `input()` 等待，不依赖 stdin：

```
脚本: 创建 .cnki_waiting → 轮询 .cnki_continue 是否存在
Agent: 检测到 .cnki_waiting → 告知用户过验证码 → 用户确认后创建 .cnki_continue
脚本: 检测到 .cnki_continue → 删除两个文件 → 继续执行
```

### 通用免终端流程（所有 Agent）

1. **Agent 后台启动脚本**（加 `--signal-file` 和 `--keep-open`）：
   ```bash
   python -m cnki_search "关键词" --years 2021-2026 --signal-file --keep-open &
   ```

2. **Agent 轮询等待标记文件**（每 2 秒检查 `.cnki_waiting`）：
   ```bash
   # 轮询直到文件出现
   while [ ! -f results/.cnki_waiting ]; do sleep 2; done
   echo "等待用户操作"
   ```

3. **用户完成验证码后，Agent 创建继续信号**：
   ```bash
   touch results/.cnki_continue
   ```

4. **Agent 等待脚本完成**（进程退出或结果文件生成）

5. **Agent 读取结果**：`results/cnki_YYYYMMDD_HHMMSS.md`

### 各 Agent 具体指令

| Agent | 启动命令 | 信号检测 | 发送继续 |
|:---|:---|:---|:---|
| **OpenClaw** | `exec ... --signal-file &` (pty 或 background) | `exec` 轮询文件 | `exec` touch 文件 |
| **Claude Code** | Bash 后台运行 + `&` | Bash `while` 循环检测 | Bash `touch` |
| **Codex / Copilot** | 终端后台运行 | 同上 | 同上 |
| **Cursor** | 内置终端后台 | 同上 | 同上 |
| **任意 Shell Agent** | `python -m cnki_search ... --signal-file &` | `[ -f results/.cnki_waiting ]` | `touch results/.cnki_continue` |

### OpenClaw 简化版（pty 托管）

OpenClaw 有 pty，可更简单——无需信号文件，直接代理 Enter 键：

1. `exec` + `pty: true` 启动
2. 用户过验证码
3. `process send-keys <id> Enter`
4. `process poll` 等待完成

### 注意事项

- 多个验证码可能依次触发（搜索页、详情页），`--signal-file` 模式每次都会等待信号
- `--keep-open` 建议配合使用，避免浏览器提前关闭
- 结果文件带时间戳，不会互相覆盖
- 摘要提取每篇间隔 1.5~3s，40 篇约需 2 分钟

## Configuration

Optional `.env` file:
```bash
CNKI_BROWSER=chrome   # or edge (default)
CNKI_MAX_PAGES=5      # max pages per query
```
