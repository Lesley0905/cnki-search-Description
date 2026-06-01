# CNKI Search — 知网文献检索

[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-blue.svg)](https://www.python.org/)

Browser-automated CNKI (中国知网 / China National Knowledge Infrastructure) literature search tool.  
Opens a browser for **manual CAPTCHA solving**, then **automatically** searches, paginates, and extracts structured citations.

✅ GB/T 7714 citation format  
✅ BibTeX export  
✅ JSON / CSV export  
✅ Multi-query batch mode  
✅ Core journal filter (北大核心 / CSSCI / CSCD)  
✅ Default 5-year window (configurable)  
✅ Works with **OpenClaw** (as a Skill) and **Claude Code** (as a standalone tool)

---

## Quick Start

### 1. Install

```bash
pip install selenium webdriver-manager
git clone https://github.com/Lesley0905/cnki-search-Description.git
cd cnki-search-Description
```

### 2. Search

```bash
# Single search (default: last 5 years, all journals)
python -m cnki_search "玉米病害 YOLO 深度学习"

# Core journals only, specific year range
python -m cnki_search "农作物病害 目标检测" --core-only --years 2020-2025

# Batch mode (multiple queries from a JSON file)
python -m cnki_search --batch examples/queries.json

# Export as JSON + CSV + Markdown
python -m cnki_search "深度学习 图像识别" --output-format md,json,csv
```

### 3. Solve CAPTCHA

When the browser opens to CNKI:
1. Complete the slider CAPTCHA manually in the browser
2. Switch back to terminal → press **Enter**
3. Everything after that is **fully automatic**

---

## Output Formats

| Flag | Format | Use Case |
|------|--------|----------|
| `md` | Markdown | Readable report, copy-paste into papers |
| `json` | JSON | Programmatic processing |
| `csv` | CSV | Excel / spreadsheet analysis |

Each paper includes:
- Title, Authors, Journal, Year, Volume, Issue, Pages
- DOI (when available)
- Core journal flag
- GB/T 7714 formatted citation
- BibTeX entry

---

## Batch Queries

Create a JSON file with your search queries:

```json
{
  "queries": [
    {"keywords": "玉米病害 YOLO 深度学习", "date_from": "2020", "date_to": "2025"},
    {"keywords": "农作物病害 目标检测 轻量化"},
    {"keywords": "深度学习 农业 综述"}
  ]
}
```

Then:

```bash
python -m cnki_search --batch my_queries.json --core-only
```

---

## Integration with AI Agents

### OpenClaw Skill

Copy to `~/.agents/skills/cnki-search/` and it auto-registers:

```bash
cp -r cnki_search ~/.agents/skills/cnki-search/
```

Then ask your OpenClaw agent: "在知网上搜索玉米病害检测的核心期刊文献"

### Claude Code / Other Agents

Run directly as a CLI tool:

```bash
python -m cnki_search "machine learning crop disease" --years 2021-2025
```

The Markdown output is ready to be consumed by any agent.

---

## Configuration

Optional `.env` file in the project root:

```bash
# Browser: chrome or edge (default: edge)
CNKI_BROWSER=chrome

# Max pages to fetch per query (default: 5)
CNKI_MAX_PAGES=10
```

---

## Requirements

- **Python** ≥ 3.10
- **Chrome** or **Edge** browser
- **CNKI access** — university IP/VPN or personal CNKI account
- Packages: `selenium`, `webdriver-manager`

---

## Limitations

- Requires **manual CAPTCHA** solving (CNKI's anti-bot protection — by design, not a bug)
- Works with CNKI's journal search (kns8s); dissertation and conference search supported experimentally
- Rate limit: CNKI may throttle after many rapid requests; the tool includes built-in delays

---

## License

MIT © 2026 Claw & Lesley

---

## Acknowledgments

Built to solve a real problem: finding Chinese core journal papers for academic thesis writing when existing tools (arXiv, PubMed, Semantic Scholar) don't index CNKI.
