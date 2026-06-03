#!/usr/bin/env python3
"""
CNKI Search — 知网文献检索工具
================================
Browser-automated CNKI (中国知网) literature search with manual CAPTCHA solving.
Extracts structured citations in GB/T 7714, BibTeX, JSON, and CSV formats.

Usage:
  python -m cnki_search "玉米病害 YOLO 深度学习"
  python -m cnki_search "玉米病害 YOLO" --years 2020-2025 --core-only
  python -m cnki_search --batch examples/queries.json
"""

import argparse
import json
import os
import random
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional
from urllib.parse import quote

try:
    from selenium import webdriver
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.webdriver.edge.service import Service as EdgeService
    from selenium.webdriver.chrome.service import Service as ChromeService
    from selenium.common.exceptions import TimeoutException, NoSuchElementException
    from webdriver_manager.microsoft import EdgeChromiumDriverManager
    from webdriver_manager.chrome import ChromeDriverManager
except ImportError:
    print("请先安装依赖: pip install selenium webdriver-manager")
    sys.exit(1)

# Fix console encoding for emoji on Windows
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

# ============================================================
# Configuration
# ============================================================

PROJECT_DIR = Path(__file__).resolve().parent.parent
OUTPUT_DIR = PROJECT_DIR / "results"
OUTPUT_DIR.mkdir(exist_ok=True)

# Load .env if exists
env_file = PROJECT_DIR / ".env"
if env_file.exists():
    with open(env_file, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())

CNKI_BROWSER = os.environ.get("CNKI_BROWSER", "edge")
CNKI_MAX_PAGES = int(os.environ.get("CNKI_MAX_PAGES", "5"))
CNKI_SEARCH_URL = "https://kns.cnki.net/kns8s/search"

_VERBOSE = False


def vprint(*args, **kwargs):
    """Print progress to stderr when verbose mode is on; silent otherwise."""
    if _VERBOSE:
        print(*args, file=sys.stderr, **kwargs)


# ============================================================
# Browser
# ============================================================

def create_driver() :
    """Create a Selenium WebDriver, auto-detecting browser."""
    if CNKI_BROWSER == "chrome":
        options = webdriver.ChromeOptions()
        options.add_argument("--start-maximized")
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option("useAutomationExtension", False)
        service = ChromeService(ChromeDriverManager().install())
        return webdriver.Chrome(service=service, options=options)
    else:
        options = webdriver.EdgeOptions()
        options.add_argument("--start-maximized")
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option("useAutomationExtension", False)
        service = EdgeService(EdgeChromiumDriverManager().install())
        return webdriver.Edge(service=service, options=options)


_SIGNAL_MODE = False
_SIGNAL_DIR = None

def wait_for_user(instructions: str = "请在浏览器中手动完成验证码/登录"):
    """Pause and wait for manual user action.

    In normal mode: uses input() to wait for Enter.
    In signal mode (--signal-file): creates .cnki_waiting marker and
    polls for .cnki_continue signal file. Works with any agent.
    """
    vprint(f"\n{'='*60}")
    vprint(f"⚠️  {instructions}")

    if _SIGNAL_MODE:
        signal_dir = Path(_SIGNAL_DIR) if _SIGNAL_DIR else PROJECT_DIR
        waiting_file = signal_dir / ".cnki_waiting"
        continue_file = signal_dir / ".cnki_continue"

        # Clean stale files
        waiting_file.unlink(missing_ok=True)
        continue_file.unlink(missing_ok=True)

        waiting_file.write_text(
            f"等待用户操作: {instructions}\n"
            f"时间: {datetime.now().isoformat()}\n"
            f"请创建 {continue_file} 以继续"
        )
        vprint(f"   📡 信号模式 — 等待 {continue_file.name}")
        vprint(f"   Agent 请在用户操作完成后创建此文件")
        vprint(f"{'='*60}")

        while not continue_file.exists():
            time.sleep(2)

        waiting_file.unlink(missing_ok=True)
        continue_file.unlink(missing_ok=True)
        vprint("   ✅ 收到继续信号")
    else:
        vprint(f"   完成后按 Enter 继续...")
        vprint(f"{'='*60}")
        input()


# ============================================================
# CNKI HTML Parser
# ============================================================

# CNKI result row pattern (from actual output):
# "[1] HTML阅读. 1 Title Authors(; separated) Journal Date Pages[J]. Journal,"
_RE_CNKI_ROW = re.compile(
    r'HTML阅读\.\s*'
    r'\d+\s*'
    r'(?P<title>.+?)\s+'
    r'(?P<authors>(?:[\u4e00-\u9fff\w·]+[;；]\s*)*[\u4e00-\u9fff\w·]+)\s+'
    r'(?P<journal>.+?)\s+'
    r'(?P<date>\d{4}-\d{2}-\d{2})\s+'
    r'(?P<pages>\d+)\s*'
    r'\[(?P<type>[A-Z])\]\..*'
)

# Simpler fallback: known CNKI structured text patterns
_RE_TITLE_AUTHORS = re.compile(
    r'^\d+\s+(.+?)\s+([\u4e00-\u9fff\w·]+(?:[;；][\u4e00-\u9fff\w·]+)+)'
)


def parse_cnki_result_row(text: str) -> Optional[dict]:
    """
    Parse a single CNKI search result row into structured paper info.

    Handles the CNKI format seen in practice:
      "1 Title Authors(分号分隔) Journal Date Pages[J]. Journal,"
    """
    text = text.strip()
    if not text or len(text) < 20:
        return None

    # Skip headers
    skip_keywords = ["序号", "题名", "作者", "来源", "发表时间", "操作", "被引", "下载"]
    if any(text.startswith(k) for k in skip_keywords):
        return None

    # Remove "HTML阅读." prefix and leading number
    cleaned = re.sub(r'^\d+\s*', '', text)
    cleaned = re.sub(r'HTML阅读\.\s*', '', cleaned).strip()

    paper: dict = {"raw": text}

    # --- Title ---
    # Title is everything up to the first Chinese-name sequence
    title_match = re.match(r'^(.+?)\s+([\u4e00-\u9fff\w·]+(?:[;；][\u4e00-\u9fff\w·]+){1,10})', cleaned)
    if title_match:
        paper["title"] = title_match.group(1).strip()
        remaining = cleaned[title_match.end():].strip()
        paper["authors"] = title_match.group(2).replace(";", "; ").replace("；", "; ")
    else:
        # Fallback
        paper["title"] = cleaned.split(" ")[0] if " " in cleaned else cleaned[:50]
        remaining = cleaned
        # Try to find authors
        author_match = re.search(
            r'([\u4e00-\u9fff\w·]{2,4}(?:[;；][\u4e00-\u9fff\w·]{2,4}){1,10})',
            remaining
        )
        if author_match:
            paper["authors"] = author_match.group(1).replace(";", "; ").replace("；", "; ")

    # --- Journal ---
    journal_match = re.search(r'《(.+?)》', remaining)
    if journal_match:
        paper["journal"] = journal_match.group(1)
    else:
        # Try patterns: "江苏农业学报", "*大学学报", "*学报"
        jm = re.search(r'([\u4e00-\u9fff]+(?:大学学报|学院学报|农业学报|农业科学|农业工程|农业机械)[^\s]*)', remaining)
        if jm:
            paper["journal"] = jm.group(1)
        else:
            jm2 = re.search(r'([\u4e00-\u9fff]+学报[^\s]*)', remaining)
            if jm2:
                paper["journal"] = jm2.group(1)
            else:
                # Generic: look for known journal indicators
                jm3 = re.search(r'([\u4e00-\u9fff]{2,}(?:学报|科学|技术|工程|应用|研究|进展|通报|杂志)[^\s]*)', remaining)
                if jm3:
                    paper["journal"] = jm3.group(1)

    # --- Date ---
    date_match = re.search(r'(\d{4})-(\d{2})-(\d{2})', remaining)
    if date_match:
        paper["year"] = date_match.group(1)
        paper["date"] = date_match.group(0)

    # --- Pages / volume info ---
    page_match = re.search(r'(\d+)\s*\[([A-Z])\]', remaining)
    if page_match:
        paper["page_count"] = page_match.group(1)
        paper["pub_type"] = page_match.group(2)  # J=journal, D=dissertation, C=conference, etc.

    # --- Volume/Issue from various patterns ---
    vol_match = re.search(r'(\d{4})[,，\s]*(\d+)\s*[\(（](\d+)[\)）]', remaining)
    if vol_match:
        paper["volume"] = vol_match.group(2)
        paper["issue"] = vol_match.group(3)

    # --- DOI ---
    doi_match = re.search(r'DOI[：:]\s*(10\.\S+)', text, re.IGNORECASE)
    if doi_match:
        paper["doi"] = doi_match.group(1)

    # --- Core journal flag ---
    if "北大核心" in text or "CSCD" in text or "CSSCI" in text or "CSTPCD" in text:
        paper["is_core"] = True

    return paper if paper.get("title") else None


def extract_all_from_page(driver) :
    """Extract all paper results from the current CNKI search page."""
    papers = []

    # CNKI wraps results in <tr> elements; try to find them
    rows = driver.find_elements(By.CSS_SELECTOR,
        "table.result-table-list tr, tr[class*='result'], .result-table-list tr")

    if not rows:
        # Try broader: any table row containing enough text
        all_rows = driver.find_elements(By.TAG_NAME, "tr")
        rows = [r for r in all_rows if len(r.text.strip()) > 40]

    for row in rows:
        try:
            text = row.text.strip()
            paper = parse_cnki_result_row(text)
            if paper:
                # Capture detail page URL from the title link
                try:
                    link = row.find_element(By.CSS_SELECTOR,
                        "a.fz14, a[href*='detail'], a[href*='abstract'], "
                        "a[href*='Article'], a[href*='kcms2'], td.name a")
                    paper['detail_url'] = link.get_attribute('href')
                except NoSuchElementException:
                    paper['detail_url'] = ''
                papers.append(paper)
        except Exception:
            continue

    return papers


def go_next_page(driver) -> bool:
    """Navigate to next page of CNKI search results. Returns False if no next page."""
    try:
        next_btn = driver.find_element(By.XPATH,
            "//a[contains(text(),'下一页') or contains(text(),'下页') or contains(@class,'next')]")
        driver.execute_script("arguments[0].scrollIntoView(true);", next_btn)
        time.sleep(0.5)
        try:
            next_btn.click()
        except Exception:
            driver.execute_script("arguments[0].click();", next_btn)
        time.sleep(3)
        return True
    except NoSuchElementException:
        return False


# ============================================================
# Search Engine
# ============================================================

def build_search_url(
    keywords: str = "",
    date_from: str = "",
    date_to: str = "",
    article_type: str = "journal",  # journal | dissertation | conference | all
) -> str:
    """Build a CNKI search URL."""
    params = [f"kw={quote(keywords)}", f"kwd={quote(keywords)}"]

    if article_type == "journal":
        params.append("classid=YSTT4HG0")
    elif article_type == "dissertation":
        params.append("classid=CDMD")
    elif article_type == "conference":
        params.append("classid=CPFD")

    if date_from:
        params.append(f"publishdate_from={date_from}-01-01")
    if date_to:
        params.append(f"publishdate_to={date_to}-12-31")

    return f"{CNKI_SEARCH_URL}?{'&'.join(params)}"


def apply_date_filter(driver, date_from: str = "", date_to: str = ""):
    """Attempt to click date range filter on CNKI page."""
    if not date_from and not date_to:
        return
    vprint(f"   📅 设置年份: {date_from or '不限'}-{date_to or '不限'}")
    try:
        from_input = driver.find_element(By.CSS_SELECTOR, "input[id*='datefrom'], input[name*='from']")
        if from_input and date_from:
            from_input.clear()
            from_input.send_keys(date_from)
    except NoSuchElementException:
        pass
    try:
        to_input = driver.find_element(By.CSS_SELECTOR, "input[id*='dateto'], input[name*='to']")
        if to_input and date_to:
            to_input.clear()
            to_input.send_keys(date_to)
    except NoSuchElementException:
        pass


def apply_core_filter(driver) -> bool:
    """Click '核心期刊' filter and wait for reload."""
    vprint("   🔍 筛选核心期刊...")
    selectors = [
        "//span[contains(text(),'核心期刊')]",
        "//label[contains(text(),'核心期刊')]",
        "//a[contains(text(),'核心期刊')]",
        "//div[contains(@class,'filter')]//span[contains(text(),'核心')]",
    ]
    for sel in selectors:
        try:
            elem = driver.find_element(By.XPATH, sel)
            elem.click()
            time.sleep(3)
            vprint("   ✅ 已筛选核心期刊")
            return True
        except NoSuchElementException:
            continue

    vprint("   ⚠️ 未找到核心期刊筛选按钮，请手动点击")
    wait_for_user("请手动点击'核心期刊'筛选，然后按 Enter")
    return True


def extract_abstract_from_detail(driver, paper) -> str:
    """
    Visit a paper's detail page and extract its abstract.

    Tries Chinese abstract first (id=ChDivSummary), then English abstract.
    Returns combined abstract string, or empty string on any failure.
    Does not raise — failures are logged via print and produce ''.
    """
    url = paper.get('detail_url', '')
    if not url or not url.startswith('http'):
        return ''

    try:
        driver.get(url)
        time.sleep(2)

        cn = ''
        for sel in ['#ChDivSummary', '.abstract-text', '.abstract', '#abstract',
                     'div.row-abstract', '[class*="summary"]', '[class*="abstract"]']:
            try:
                elem = driver.find_element(By.CSS_SELECTOR, sel)
                text = elem.text.strip()
                if text and len(text) > 20:
                    cn = text
                    break
            except NoSuchElementException:
                continue

        en = ''
        for sel in ['#EnDivSummary', '.en-abstract', '#en-abstract',
                     '[class*="abstract"][class*="en"]']:
            try:
                elem = driver.find_element(By.CSS_SELECTOR, sel)
                text = elem.text.strip()
                if text and len(text) > 10:
                    en = text
                    break
            except NoSuchElementException:
                continue

        parts = []
        if cn:
            parts.append(cn)
        if en:
            parts.append(f"[Abstract] {en}")
        return '\n'.join(parts) if parts else ''

    except Exception:
        return ''


def navigate_and_search(
    driver,
    keywords: str,
    date_from: str = "",
    date_to: str = "",
    core_only: bool = False,
    article_type: str = "journal",
):
    """Navigate to CNKI and execute a search."""
    url = build_search_url(keywords, date_from, date_to, article_type)
    vprint(f"\n🔍 检索: {keywords}")
    
    driver.get(url)
    time.sleep(3)

    if "verify" in driver.current_url.lower():
        wait_for_user("请完成滑块验证码")

    # Apply date filter on the page if URL params didn't stick
    try:
        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "table.result-table-list, .result-table-list, tr"))
        )
    except TimeoutException:
        wait_for_user("页面加载超时，请手动搜索后按 Enter")

    if core_only:
        apply_core_filter(driver)


def deduplicate_papers(papers: list) -> list:
    """Deduplicate papers: DOI as primary key, title+first_author as fallback.

    Only used in batch mode (multiple queries) to remove cross-query duplicates.
    Prints a one-line summary: 去重完成：原始 N 篇 → 去重后 M 篇（移除 K 条重复）
    """
    if not papers:
        return papers

    original_count = len(papers)
    seen_doi = set()
    seen_ta = set()
    deduped = []

    for p in papers:
        doi = (p.get('doi') or '').strip()
        if doi:
            if doi in seen_doi:
                continue
            seen_doi.add(doi)
            deduped.append(p)
            continue

        title = (p.get('title') or '').strip()
        authors = (p.get('authors') or '').strip()
        first_author = (authors.split(';')[0].split('；')[0].strip()
                        if authors else '')
        ta_key = f"{title}||{first_author}"

        if ta_key in seen_ta:
            continue
        seen_ta.add(ta_key)
        deduped.append(p)

    removed = original_count - len(deduped)
    if removed > 0:
        vprint(f"去重完成：原始 {original_count} 篇 → 去重后 {len(deduped)} 篇"
              f"（移除 {removed} 条重复）")

    return deduped


def search_cnki(
    queries,
    driver=None,
    max_pages: int = 5,
    core_only: bool = False,
    article_type: str = "journal",
) :
    """Execute multiple CNKI searches, return deduplicated paper list."""
    close_driver = driver is None
    if close_driver:
        driver = create_driver()

    all_papers = []
    seen = set()

    try:
        for idx, q in enumerate(queries):
            keywords = q.get("keywords", "")
            date_from = q.get("date_from", "")
            date_to = q.get("date_to", "")
            
            vprint(f"\n{'='*60}")
            vprint(f"[查询 {idx+1}/{len(queries)}] 关键词：\"{keywords}\"")

            q_type = q.get("article_type", article_type)  # per-query override
            navigate_and_search(driver, keywords, date_from, date_to, core_only, q_type)

            for page in range(max_pages):
                try:
                    vprint(f"[{page+1}/{max_pages} 页] 正在获取...", end=" ")
                    papers = extract_all_from_page(driver)

                    new_count = 0
                    for p in papers:
                        key = p.get("title", "")[:40]
                        if key and key not in seen:
                            seen.add(key)
                            p["search_keywords"] = keywords
                            all_papers.append(p)
                            new_count += 1

                    vprint(f"{len(papers)} 条, 新增 {new_count}（累计 {len(all_papers)}）")

                    if not go_next_page(driver):
                        break
                except Exception as e:
                    vprint(f"翻页跳过: {e}")
                    break
                time.sleep(2)

        # --- Extract abstracts from detail pages ---
        if all_papers:
            vprint(f"\n{'='*60}")
            vprint(f"📝 正在提取摘要... ({len(all_papers)} 篇)")
            abstract_count = 0
            for i, paper in enumerate(all_papers):
                delay = 1.5 + random.random() * 1.5  # 1.5–3.0 s
                time.sleep(delay)
                paper['abstract'] = extract_abstract_from_detail(driver, paper)
                if paper.get('abstract'):
                    abstract_count += 1
                ok = paper.get('abstract')
                vprint(f"摘要提取中 [{i+1}/{len(all_papers)}] "
                      f"{'✅' if ok else '❌'}《{paper.get('title', '?')}》")
            vprint(f"📝 摘要提取完成: {abstract_count}/{len(all_papers)} 篇成功")
        else:
            for p in all_papers:
                p['abstract'] = ''

        # --- Batch deduplication (multi-query only) ---
        if len(queries) > 1:
            all_papers = deduplicate_papers(all_papers)

    finally:
        if close_driver:
            vprint("\n🔒 浏览器将在 5 秒后关闭...")
            time.sleep(5)
            driver.quit()

    return all_papers


# ============================================================
# Citation Formatting
# ============================================================

def format_gbt7714(paper: dict) -> str:
    """GB/T 7714-2015 journal article format (with optional abstract)."""
    authors = paper.get("authors", "")
    title = paper.get("title", "")
    journal = paper.get("journal", "")
    year = paper.get("year", "")
    volume = paper.get("volume", "")
    issue = paper.get("issue", "")
    pages = paper.get("pages", "") or paper.get("page_count", "")
    pub_type = paper.get("pub_type", "J")

    parts = []
    if authors:
        parts.append(f"{authors}.")
    if title:
        type_map = {"J": "[J]", "D": "[D]", "C": "[C]", "M": "[M]", "N": "[N]"}
        suffix = type_map.get(pub_type, "[J]")
        parts.append(f"{title}{suffix}.")
    if journal:
        parts.append(f"{journal},")
    if year:
        date_part = year
        if volume:
            date_part += f", {volume}"
        if issue:
            date_part += f"({issue})"
        if pages:
            date_part += f": {pages}"
        parts.append(f"{date_part}.")
    citation = " ".join(parts)
    if paper.get("abstract"):
        citation += f"\n摘要: {paper['abstract']}"
    return citation


def format_bibtex(paper: dict) -> str:
    """BibTeX entry for the paper (with optional abstract)."""
    authors = paper.get("authors", "Unknown")
    first_author = authors.split(";")[0].split(" ")[0].strip() if authors else "Unknown"
    title_key = re.sub(r'[^a-zA-Z0-9]', '', paper.get("title", "")[:20] or "paper")
    cite_key = f"{first_author}{paper.get('year', '')}{title_key}"

    lines = [f"@article{{{cite_key},"]
    lines.append(f'  title = {{{{{paper.get("title", "")}}}}},')
    lines.append(f'  author = {{{{{authors.replace(";", " and ")}}}}},')
    lines.append(f'  journal = {{{{{paper.get("journal", "")}}}}},')
    if paper.get("year"):
        lines.append(f'  year = {{{{{paper.get("year")}}}}},')
    if paper.get("volume"):
        lines.append(f'  volume = {{{{{paper.get("volume")}}}}},')
    if paper.get("issue"):
        lines.append(f'  number = {{{{{paper.get("issue")}}}}},')
    if paper.get("pages") or paper.get("page_count"):
        lines.append(f'  pages = {{{{{paper.get("pages") or paper.get("page_count")}}}}},')
    if paper.get("doi"):
        lines.append(f'  doi = {{{{{paper.get("doi")}}}}},')
    if paper.get("abstract"):
        lines.append(f'  abstract = {{{{{paper["abstract"]}}}}},')
    lines.append("}")
    return "\n".join(lines)


# ============================================================
# Output Exporters
# ============================================================

def export_markdown(papers, output_path: Path) -> Path:
    """Export results as a readable Markdown report."""
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(f"# CNKI Search Results\n\n")
        f.write(f"**Search time**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"**Total**: {len(papers)} papers\n\n---\n\n")

        for i, p in enumerate(papers, 1):
            f.write(f"## [{i}] {p.get('title', 'N/A')}\n\n")
            f.write(f"- **Authors**: {p.get('authors', 'N/A')}\n")
            f.write(f"- **Journal**: {p.get('journal', 'N/A')}\n")
            f.write(f"- **Year**: {p.get('year', 'N/A')}\n")
            if p.get("volume") or p.get("issue"):
                f.write(f"- **Vol/Issue**: {p.get('volume','?')}({p.get('issue','?')})\n")
            if p.get("pages") or p.get("page_count"):
                f.write(f"- **Pages**: {p.get('pages') or p.get('page_count')}\n")
            if p.get("doi"):
                f.write(f"- **DOI**: {p.get('doi')}\n")
            if p.get("is_core"):
                f.write(f"- **⭐ Core Journal**\n")
            if p.get("abstract"):
                f.write(f"- **Abstract**: {p.get('abstract')}\n")
            f.write(f"\n**GB/T 7714**:\n> {format_gbt7714(p)}\n\n")
            f.write(f"**BibTeX**:\n```bibtex\n{format_bibtex(p)}\n```\n\n---\n\n")
    return output_path


def export_json(papers, output_path: Path) -> Path:
    """Export as JSON."""
    output = []
    for p in papers:
        output.append({
            "title": p.get("title"),
            "authors": p.get("authors"),
            "journal": p.get("journal"),
            "year": p.get("year"),
            "volume": p.get("volume"),
            "issue": p.get("issue"),
            "pages": p.get("pages") or p.get("page_count"),
            "abstract": p.get("abstract", ""),
            "doi": p.get("doi"),
            "is_core": p.get("is_core", False),
            "citation_gbt7714": format_gbt7714(p),
            "citation_bibtex": format_bibtex(p),
            "search_keywords": p.get("search_keywords"),
        })
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    return output_path


def export_csv(papers, output_path: Path) -> Path:
    """Export as CSV for spreadsheet use."""
    import csv
    with open(output_path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["序号", "标题", "作者", "期刊", "年份", "卷", "期", "页码",
                         "摘要", "DOI", "核心期刊", "GB/T 7714引用"])
        for i, p in enumerate(papers, 1):
            writer.writerow([
                i,
                p.get("title", ""),
                p.get("authors", ""),
                p.get("journal", ""),
                p.get("year", ""),
                p.get("volume", ""),
                p.get("issue", ""),
                p.get("pages") or p.get("page_count", ""),
                p.get("abstract", ""),
                p.get("doi", ""),
                "是" if p.get("is_core") else "",
                format_gbt7714(p),
            ])
    return output_path


def save_results(papers, output_path: Optional[str] = None,
                 formats = ("md",)) :
    """Save results in specified formats. Returns list of output paths."""
    if output_path is None:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        base = OUTPUT_DIR / f"cnki_{timestamp}"
    else:
        base = Path(output_path).with_suffix("")

    paths = []
    if "md" in formats:
        paths.append(export_markdown(papers, Path(f"{base}.md")))
    if "json" in formats:
        paths.append(export_json(papers, Path(f"{base}.json")))
    if "csv" in formats:
        paths.append(export_csv(papers, Path(f"{base}.csv")))

    for p in paths:
        print(f"✅ {p}")
    return paths


# ============================================================
# Keyword Extraction from Project
# ============================================================

# Chinese stopwords — words that don't carry topic meaning
_CN_STOP = set("的 了 在 是 我 有 和 就 不 人 都 一 一个 上 也 很 到 说 要 去 你 会 着 没有 看 好 自己 这 他 她 它 们 那 些 什么 而 为 所以 因为 但是 可以 这个 如果 虽然 然后 之后 之前 已经 比较 非常 还是 或者 以及 不仅 而且 之 其 与 及 等 该 被 把 从 对 向 往 当 于 中 以 后 前 内 外 间 所 呢 吗 吧 啊 呀 哦 嗯".split())

# Known domain-specific keywords to prioritize (expandable)
_DOMAIN_BOOST = set(
    "深度学习 机器学习 神经网络 卷积 目标检测 图像识别 图像分类 语义分割 "
    "YOLO CNN R-CNN SSD Transformer ResNet MobileNet EfficientNet "
    "病害 病虫害 作物 农作物 玉米 小麦 水稻 大豆 棉花 番茄 苹果 柑橘 "
    "轻量化 注意力机制 特征融合 多尺度 迁移学习 数据增强 "
    "检测系统 软件设计 边缘计算 嵌入式 无人机 "
    "综述 研究进展 现状 综述研究".split()
)


def _text_from_dir(project_path: str) -> str:
    """Extract readable text from a project directory."""
    root = Path(project_path)
    if not root.exists():
        return ""

    texts = []
    # Priority files to scan
    for pattern in ["README*", "*.md", "*.txt", "abstract*.txt", "主题*.txt", "介绍*.txt"]:
        for f in root.glob(pattern):
            if f.suffix in (".png", ".jpg", ".pdf"):
                continue
            try:
                content = f.read_text(encoding="utf-8", errors="ignore")
                texts.append(content)
            except Exception:
                pass
            if len(texts) >= 3:
                break
        if texts:
            break

    # Also check one level down
    if not texts:
        for sub in root.iterdir():
            if sub.is_dir() and not sub.name.startswith("."):
                for pattern in ["README*", "*.md", "*.txt"]:
                    for f in sub.glob(pattern):
                        try:
                            texts.append(f.read_text(encoding="utf-8", errors="ignore"))
                        except Exception:
                            pass
                        break
                if texts:
                    break

    return "\n".join(texts)


def extract_keywords(text: str, topk: int = 15) -> list[str]:
    """Extract key phrases from project text for CNKI search."""
    if not text:
        return []

    # Extract Chinese word bigrams and trigrams
    chinese_chars = re.findall(r'[\u4e00-\u9fff]+', text)
    phrases = {}

    for segment in chinese_chars:
        for n in [2, 3, 4]:
            for i in range(len(segment) - n + 1):
                phrase = segment[i:i + n]
                # Skip stopwords
                if phrase in _CN_STOP:
                    continue
                # Boost domain-specific phrases
                weight = 1.0
                if phrase in _DOMAIN_BOOST or any(term in phrase for term in _DOMAIN_BOOST):
                    weight = 2.0
                phrases[phrase] = phrases.get(phrase, 0) + weight

    # Also extract English acronyms and terms
    eng_terms = re.findall(r'\b[A-Z][A-Za-z0-9+]{2,}(?:\s?\d+)?\b', text)
    for term in set(eng_terms):
        if len(term) >= 3:
            phrases[term] = phrases.get(term, 0) + 3.0  # English terms get boost

    # Split into Chinese and English, sort by score*length
    cn_sorted = sorted(
        [(p, s) for p, s in phrases.items() if re.search(r'[\u4e00-\u9fff]', p)],
        key=lambda x: -(x[1] * len(x[0]))
    )
    en_sorted = sorted(
        [(p, s) for p, s in phrases.items() if not re.search(r'[\u4e00-\u9fff]', p)],
        key=lambda x: -(x[1] * len(x[0]))
    )
    all_sorted = cn_sorted + en_sorted

    result = []
    seen = set()
    for phrase, _ in all_sorted:
        if len(phrase) < 2:
            continue
        if re.match(r'^[0-9\s\.\-\+\*\/\=\{\}\(\)\[\]\<\>\|\&\#\@\!\?\:\;\,\"\']+$', phrase):
            continue
        if phrase in seen:
            continue
        if any(phrase in existing for existing in seen):
            continue
        seen.add(phrase)
        result.append(phrase)
        if len(result) >= topk:
            break

    return result


def generate_queries(keywords, num_queries=5):
    """Generate search queries from extracted keywords (Chinese-first)."""
    if not keywords:
        return []

    cn = [k for k in keywords if any('\u4e00' <= c <= '\u9fff' for c in k)]
    kw = cn + [k for k in keywords if k not in cn]
    if not kw:
        return []
    n = len(kw)

    qs = []
    if n >= 3:
        qs.append({"keywords": " ".join(kw[:3])})
    if n >= 1:
        qs.append({"keywords": "%s 检测 识别" % kw[0]})
    if n >= 1:
        qs.append({"keywords": "%s 综述 研究进展" % kw[0]})
    if n >= 2:
        suffix = "深度学习" if "深度" not in kw[0]+kw[1] else "目标检测"
        qs.append({"keywords": "%s %s %s" % (kw[0], kw[1], suffix)})
    if n >= 2:
        qs.append({"keywords": "%s 轻量化 注意力机制" % kw[0]})

    seen = set()
    uniq = []
    for q in qs:
        k = q["keywords"]
        if k not in seen:
            seen.add(k)
            uniq.append(q)
    return uniq[:num_queries]


# ============================================================
# CLI
# ============================================================

def default_year_range() -> str:
    """Return a 5-year window ending this year."""
    this_year = datetime.now().year
    return f"{this_year - 5}-{this_year}"


def main():
    parser = argparse.ArgumentParser(
        prog="cnki-search",
        description="CNKI Search — 知网文献检索 (浏览器自动化 + 手动验证码)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python -m cnki_search "玉米病害 YOLO 深度学习"
  python -m cnki_search "农作物病害 目标检测" --core-only --years 2020-2025
  python -m cnki_search --batch examples/queries.json
  python -m cnki_search "深度学习 图像识别" --output-format json,csv
  python -m cnki_search "机器学习" --article-type dissertation
  python -m cnki_search --from-project .                    自动从项目提取关键词
  python -m cnki_search --from-project ~/my-paper/README.md

Output formats: md (Markdown), json, csv, bib (BibTeX)
Default year range: last 5 years (adjustable with --years)
""",
    )
    parser.add_argument("query", nargs="?", help="Search keywords (use quotes for multi-word)")
    parser.add_argument("--years", "-y",
                        default=default_year_range(),
                        help=f"Year range, e.g. '2020-2025' (default: last 5 years)")
    parser.add_argument("--core-only", "-c", action="store_true",
                        help="Only core journals (北大核心/CSSCI/CSCD)")
    parser.add_argument("--article-type", "-t", default="journal",
                        choices=["journal", "dissertation", "conference", "all"],
                        help="Article type (default: journal)")
    parser.add_argument("--max-pages", "-p", type=int, default=CNKI_MAX_PAGES,
                        help=f"Max pages per query (default: {CNKI_MAX_PAGES})")
    parser.add_argument("--batch", "-b", help="Path to JSON file with batch queries")
    parser.add_argument("--output", "-o", help="Output file path (without extension)")
    parser.add_argument("--output-format", "-f", default="md",
                        help="Output formats: md, json, csv (comma-separated)")
    parser.add_argument("--from-project", "-P", metavar="PATH",
                        help="Auto-extract keywords from project dir/file")
    parser.add_argument("--keep-open", action="store_true",
                        help="Keep browser open after search")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="Show progress output (agent mode: omit for silence)")
    parser.add_argument("--signal-file", "-S", action="store_true",
                        help="Use file-based signaling instead of stdin (agent automation)")
    parser.add_argument("--no-headless-check", action="store_true",
                        help="Skip checking for headless mode")

    args = parser.parse_args()

    # Enable verbose progress output
    if args.verbose:
        global _VERBOSE
        _VERBOSE = True

    # Enable signal mode for agent automation
    if args.signal_file:
        global _SIGNAL_MODE, _SIGNAL_DIR
        _SIGNAL_MODE = True
        _SIGNAL_DIR = str(OUTPUT_DIR)

    # --- Build queries ---
    queries = []

    if args.from_project:
        project_path = Path(args.from_project).expanduser()
        if not project_path.exists():
            print(f"❌ 路径不存在: {args.from_project}")
            sys.exit(1)
        if project_path.is_file():
            text = project_path.read_text(encoding="utf-8", errors="ignore")
        else:
            text = _text_from_dir(str(project_path))
        if not text:
            print(f"⚠️  未在 {args.from_project} 中找到可读文本")
            sys.exit(1)
        keywords = extract_keywords(text)
        if not keywords:
            print("⚠️  未能提取关键词，请手动指定搜索词")
            sys.exit(1)
        vprint(f"🔑 提取关键词: {', '.join(keywords[:10])}")
        queries = generate_queries(keywords)
        vprint(f"📋 生成 {len(queries)} 组检索式:")
        for q in queries:
            vprint(f"   - {q['keywords']}")

    if args.batch:
        with open(args.batch, "r", encoding="utf-8") as f:
            data = json.load(f)
        queries = data if isinstance(data, list) else data.get("queries", [data])
    elif not queries:
        keyword = args.query or ""
        if not keyword:
            print("❌ 请提供搜索关键词")
            print("   python -m cnki_search \"关键词\" [--years 2020-2025]")
            print("   python -m cnki_search --batch queries.json")
            print("   python -m cnki_search --from-project .")
            sys.exit(1)
        queries = [{"keywords": keyword}]

    # Parse year range
    year_parts = args.years.replace(" ", "").split("-")
    date_from = year_parts[0] if year_parts else ""
    date_to = year_parts[1] if len(year_parts) > 1 else ""
    for q in queries:
        q.setdefault("date_from", date_from)
        q.setdefault("date_to", date_to)

    # Parse output formats
    formats = tuple(f.strip() for f in args.output_format.split(","))

    # --- Run ---
    vprint("🚀 CNKI Search")
    vprint(f"   检索组数: {len(queries)}")
    vprint(f"   时间范围: {date_from} — {date_to}")
    vprint(f"   核心期刊: {'是' if args.core_only else '所有'}")
    vprint(f"   文献类型: {args.article_type}")
    vprint(f"   每查询最多翻页: {args.max_pages}")

    driver = create_driver()
    try:
        papers = search_cnki(
            queries=queries,
            driver=driver,
            max_pages=args.max_pages,
            core_only=args.core_only,
            article_type=args.article_type,
        )

        if papers:
            save_results(papers, args.output, formats)
            print(f"\n📊 总计: {len(papers)} 篇")
            print(f"\n--- 预览 (GB/T 7714) ---")
            for i, p in enumerate(papers[:5], 1):
                print(f"[{i}] {format_gbt7714(p)}")
            if len(papers) > 5:
                print(f"... 共 {len(papers)} 篇")
        else:
            print("\n⚠️  未检索到文献。请检查搜索词或手动在浏览器中搜索。")
            print("   浏览器保持打开，可手动操作。")
            if args.keep_open:
                wait_for_user("操作完成后按 Enter 关闭")
    finally:
        if not args.keep_open:
            time.sleep(2)
        driver.quit()

