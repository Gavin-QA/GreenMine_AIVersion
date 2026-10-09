"""
==============================================================================
utils/report_hub.py —— 自动化巡检与探索全量大盘门户引擎 (Test Report Hub)
==============================================================================

职责：
1. 遍历 reports/runs/ 下的所有历史运行目录；
2. 聚合全局运行指标（总运行次数、总步数、总Bug数、总运行时长）；
3. 生成 reports/runs/index.html 统一门户首页，彻底消灭默认的黑白目录列表；
4. 支持一键本地/内网启动固定服务：python utils/report_hub.py --serve --port 8080。
"""

from __future__ import annotations

import argparse
import html
import io
import json
import logging
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

# Windows GBK 终端保护
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

PROJECT_ROOT = Path(__file__).parent.parent.resolve()
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from utils.paths import RUNS_DIR

logger = logging.getLogger("report_hub")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] [%(name)s] %(message)s")


class ReportHub:
    def __init__(self, runs_dir: Optional[Path | str] = None):
        self.runs_dir = Path(runs_dir).resolve() if runs_dir else RUNS_DIR.resolve()

    def collect_all_runs(self) -> List[Dict[str, Any]]:
        """扫描所有运行目录并聚合元数据"""
        from utils.report_generator import ReportGenerator

        runs_data = []
        if not self.runs_dir.exists():
            return runs_data

        subdirs = sorted([d for d in self.runs_dir.iterdir() if d.is_dir()], key=lambda p: p.stat().st_mtime, reverse=True)

        for d in subdirs:
            # 确保每个运行目录内部都有 report.html
            report_file = d / "report.html"
            generator = ReportGenerator(d)
            if not report_file.exists():
                try:
                    generator.generate_html()
                except Exception as e:
                    logger.warning(f"为 {d.name} 补充生成 report.html 失败: {e}")

            try:
                data = generator.parse_run_data()
                data["folder_name"] = d.name
                data["report_url"] = f"./{d.name}/report.html"
                data["mtime"] = d.stat().st_mtime
                runs_data.append(data)
            except Exception as e:
                logger.error(f"解析运行目录 {d.name} 失败: {e}")

        return runs_data

    def build_index_html(self, output_path: Optional[Path | str] = None) -> Path:
        """生成统一门户首页 reports/runs/index.html"""
        runs = self.collect_all_runs()
        out_file = Path(output_path).resolve() if output_path else (self.runs_dir / "index.html")

        # 统计宏观总计数据
        total_runs = len(runs)
        total_steps = sum(r.get("kpi", {}).get("total_steps", 0) for r in runs)
        total_bugs = sum(r.get("kpi", {}).get("bugs_count", 0) for r in runs)
        
        # 统计全局 Bug 列表
        all_bugs = []
        for r in runs:
            r_id = r.get("run_id", "")
            r_link = r.get("report_url", "#")
            for b in r.get("bugs", []):
                all_bugs.append({
                    "id": b.get("id", "BUG"),
                    "title": b.get("title", ""),
                    "run_id": r_id,
                    "date": b.get("creation_date", ""),
                    "step": (b.get("details") or {}).get("step", ""),
                    "actual": (b.get("details") or {}).get("actual", ""),
                    "report_link": r_link
                })

        runs_json = json.dumps(runs, ensure_ascii=False)
        bugs_json = json.dumps(all_bugs, ensure_ascii=False)
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        html_content = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Electron Vision AI · 自动化巡检与探索全景门户</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&family=JetBrains+Mono:wght@400;500;600&display=swap" rel="stylesheet">
  <style>
    :root {{
      --bg-base: #07090e;
      --bg-surface: #0f1422;
      --bg-card: rgba(18, 24, 38, 0.75);
      --bg-card-hover: rgba(28, 38, 62, 0.9);
      --border-subtle: rgba(255, 255, 255, 0.08);
      --border-focus: rgba(99, 102, 241, 0.45);
      --text-main: #f8fafc;
      --text-muted: #94a3b8;
      --text-dim: #64748b;
      --primary: #6366f1;
      --primary-glow: rgba(99, 102, 241, 0.25);
      --emerald: #10b981;
      --emerald-bg: rgba(16, 185, 129, 0.12);
      --rose: #f43f5e;
      --rose-bg: rgba(244, 63, 94, 0.15);
      --cyan: #06b6d4;
      --cyan-bg: rgba(6, 182, 212, 0.15);
      --amber: #f59e0b;
      --font-sans: 'Inter', -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      --font-mono: 'JetBrains Mono', Consolas, Monaco, monospace;
    }}

    * {{
      box-sizing: border-box;
      margin: 0;
      padding: 0;
    }}

    body {{
      font-family: var(--font-sans);
      background-color: var(--bg-base);
      color: var(--text-main);
      line-height: 1.5;
      min-height: 100vh;
      background-image: 
        radial-gradient(circle at 20% 10%, rgba(99, 102, 241, 0.15) 0%, transparent 45%),
        radial-gradient(circle at 80% 20%, rgba(139, 92, 246, 0.12) 0%, transparent 40%),
        radial-gradient(circle at 50% 90%, rgba(16, 185, 129, 0.07) 0%, transparent 50%);
      background-attachment: fixed;
    }}

    .container {{
      max-width: 1440px;
      margin: 0 auto;
      padding: 36px 24px 80px 24px;
    }}

    /* Hero Header */
    .hero {{
      background: var(--bg-card);
      border: 1px solid var(--border-subtle);
      border-radius: 24px;
      padding: 36px 40px;
      backdrop-filter: blur(20px);
      box-shadow: 0 24px 48px -15px rgba(0, 0, 0, 0.6);
      margin-bottom: 32px;
      position: relative;
      overflow: hidden;
    }}

    .hero::before {{
      content: '';
      position: absolute;
      top: 0; left: 0; right: 0;
      height: 3px;
      background: linear-gradient(90deg, #6366f1, #8b5cf6, #ec4899, #10b981);
    }}

    .hero-top {{
      display: flex;
      justify-content: space-between;
      align-items: flex-start;
      gap: 20px;
      flex-wrap: wrap;
      margin-bottom: 24px;
    }}

    .hero-title-group h1 {{
      font-size: 28px;
      font-weight: 800;
      letter-spacing: -0.02em;
      display: flex;
      align-items: center;
      gap: 12px;
      color: #fff;
    }}

    .hero-title-group p {{
      color: var(--text-muted);
      font-size: 14px;
      margin-top: 6px;
    }}

    .hero-status-pill {{
      background: rgba(16, 185, 129, 0.12);
      border: 1px solid rgba(16, 185, 129, 0.3);
      color: #34d399;
      padding: 6px 14px;
      border-radius: 999px;
      font-size: 13px;
      font-weight: 600;
      display: flex;
      align-items: center;
      gap: 6px;
    }}

    .pulse-dot {{
      width: 8px;
      height: 8px;
      border-radius: 50%;
      background: #10b981;
      box-shadow: 0 0 10px #10b981;
      animation: pulse 2s infinite;
    }}

    @keyframes pulse {{
      0% {{ transform: scale(0.95); opacity: 0.8; }}
      50% {{ transform: scale(1.3); opacity: 1; }}
      100% {{ transform: scale(0.95); opacity: 0.8; }}
    }}

    /* Global KPIs */
    .kpi-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
      gap: 16px;
    }}

    .kpi-card {{
      background: rgba(15, 23, 42, 0.6);
      border: 1px solid var(--border-subtle);
      border-radius: 16px;
      padding: 18px 22px;
      transition: transform 0.2s, border-color 0.2s;
    }}

    .kpi-card:hover {{
      transform: translateY(-2px);
      border-color: var(--border-focus);
    }}

    .kpi-card .label {{
      font-size: 13px;
      color: var(--text-dim);
      font-weight: 500;
      display: flex;
      align-items: center;
      gap: 6px;
      margin-bottom: 6px;
    }}

    .kpi-card .value {{
      font-size: 26px;
      font-weight: 800;
      letter-spacing: -0.02em;
      color: #fff;
    }}

    .kpi-card .value span.sub {{
      font-size: 13px;
      color: var(--text-dim);
      font-weight: 500;
      margin-left: 4px;
    }}

    /* Tabs Bar */
    .tabs-bar {{
      display: flex;
      gap: 12px;
      margin-bottom: 24px;
      border-bottom: 1px solid var(--border-subtle);
      padding-bottom: 14px;
    }}

    .tab-btn {{
      background: transparent;
      border: 1px solid transparent;
      color: var(--text-muted);
      padding: 10px 20px;
      border-radius: 10px;
      font-size: 14px;
      font-weight: 600;
      cursor: pointer;
      display: flex;
      align-items: center;
      gap: 8px;
      transition: all 0.2s;
    }}

    .tab-btn:hover {{
      color: #fff;
      background: rgba(255, 255, 255, 0.05);
    }}

    .tab-btn.active {{
      color: #fff;
      background: var(--primary);
      box-shadow: 0 4px 16px var(--primary-glow);
    }}

    .tab-btn .badge {{
      font-size: 11px;
      padding: 2px 8px;
      border-radius: 999px;
      background: rgba(0, 0, 0, 0.35);
    }}

    .tab-btn.active .badge {{
      background: rgba(255, 255, 255, 0.25);
    }}

    /* Filter & Search Bar */
    .filter-bar {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 16px;
      flex-wrap: wrap;
      margin-bottom: 24px;
    }}

    .filter-pills {{
      display: flex;
      gap: 8px;
    }}

    .filter-pill {{
      background: rgba(15, 23, 42, 0.7);
      border: 1px solid var(--border-subtle);
      color: var(--text-muted);
      padding: 7px 16px;
      border-radius: 999px;
      font-size: 13px;
      font-weight: 500;
      cursor: pointer;
      transition: all 0.2s;
    }}

    .filter-pill:hover {{
      color: #fff;
      border-color: rgba(255, 255, 255, 0.2);
    }}

    .filter-pill.active {{
      background: rgba(99, 102, 241, 0.2);
      border-color: var(--primary);
      color: #a5b4fc;
      font-weight: 600;
    }}

    .search-box {{
      background: rgba(15, 23, 42, 0.7);
      border: 1px solid var(--border-subtle);
      color: #fff;
      padding: 8px 18px;
      border-radius: 10px;
      font-size: 13px;
      width: 280px;
      outline: none;
      transition: border-color 0.2s;
    }}

    .search-box:focus {{
      border-color: var(--primary);
      box-shadow: 0 0 10px var(--primary-glow);
    }}

    /* Runs Cards List */
    .runs-grid {{
      display: flex;
      flex-direction: column;
      gap: 18px;
    }}

    .run-card {{
      background: var(--bg-card);
      border: 1px solid var(--border-subtle);
      border-radius: 18px;
      padding: 24px 28px;
      backdrop-filter: blur(12px);
      transition: transform 0.2s, border-color 0.2s, box-shadow 0.2s;
      display: grid;
      grid-template-columns: 1fr auto;
      gap: 24px;
      align-items: center;
    }}

    .run-card:hover {{
      transform: translateY(-2px);
      border-color: var(--border-focus);
      box-shadow: 0 16px 36px -10px rgba(0, 0, 0, 0.5);
    }}

    .run-card-main {{
      display: flex;
      flex-direction: column;
      gap: 12px;
    }}

    .run-header {{
      display: flex;
      align-items: center;
      gap: 12px;
      flex-wrap: wrap;
    }}

    .mode-tag {{
      font-size: 12px;
      font-weight: 700;
      padding: 4px 10px;
      border-radius: 6px;
      text-transform: uppercase;
      letter-spacing: 0.04em;
    }}

    .mode-tag.explore {{
      background: rgba(99, 102, 241, 0.2);
      color: #a5b4fc;
      border: 1px solid rgba(99, 102, 241, 0.4);
    }}

    .mode-tag.smoke {{
      background: var(--cyan-bg);
      color: #38bdf8;
      border: 1px solid rgba(6, 182, 212, 0.4);
    }}

    .mode-tag.yaml {{
      background: var(--emerald-bg);
      color: #34d399;
      border: 1px solid rgba(16, 185, 129, 0.4);
    }}

    .run-id-title {{
      font-family: var(--font-mono);
      font-size: 17px;
      font-weight: 700;
      color: #fff;
    }}

    .run-meta-row {{
      display: flex;
      align-items: center;
      gap: 16px;
      font-size: 13px;
      color: var(--text-dim);
    }}

    .run-meta-item {{
      display: flex;
      align-items: center;
      gap: 6px;
    }}

    .run-meta-item strong {{
      color: var(--text-muted);
    }}

    .objective-quote {{
      background: rgba(10, 15, 26, 0.6);
      border-left: 3px solid var(--primary);
      padding: 10px 14px;
      border-radius: 6px;
      font-size: 13px;
      color: #cbd5e1;
      max-width: 900px;
    }}

    .run-badges-row {{
      display: flex;
      gap: 12px;
      flex-wrap: wrap;
    }}

    .metric-badge {{
      background: rgba(15, 23, 42, 0.6);
      border: 1px solid var(--border-subtle);
      padding: 4px 12px;
      border-radius: 8px;
      font-size: 12px;
      font-weight: 600;
      display: flex;
      align-items: center;
      gap: 6px;
      color: var(--text-muted);
    }}

    .metric-badge.bugs {{
      background: var(--rose-bg);
      border-color: rgba(244, 63, 94, 0.3);
      color: #fb7185;
    }}

    .open-report-btn {{
      background: var(--primary);
      color: #fff;
      padding: 12px 24px;
      border-radius: 12px;
      font-size: 14px;
      font-weight: 600;
      text-decoration: none;
      display: inline-flex;
      align-items: center;
      gap: 8px;
      transition: all 0.2s;
      white-space: nowrap;
      box-shadow: 0 4px 16px var(--primary-glow);
    }}

    .open-report-btn:hover {{
      background: #4f46e5;
      transform: translateY(-2px);
      box-shadow: 0 8px 24px var(--primary-glow);
    }}

    /* Global Bugs Table */
    .bugs-table {{
      width: 100%;
      border-collapse: collapse;
      font-size: 13px;
      background: var(--bg-card);
      border: 1px solid var(--border-subtle);
      border-radius: 16px;
      overflow: hidden;
    }}

    .bugs-table th, .bugs-table td {{
      padding: 14px 18px;
      text-align: left;
      border-bottom: 1px solid var(--border-subtle);
    }}

    .bugs-table th {{
      color: var(--text-dim);
      font-size: 11px;
      text-transform: uppercase;
      font-weight: 700;
      background: rgba(15, 23, 42, 0.5);
    }}

    .bugs-table tr:hover td {{
      background: rgba(255, 255, 255, 0.02);
    }}

    .bug-link {{
      color: #38bdf8;
      text-decoration: none;
      font-weight: 600;
    }}

    .bug-link:hover {{
      text-decoration: underline;
    }}

    .tab-pane {{
      display: none;
    }}

    .tab-pane.active {{
      display: block;
      animation: fadeIn 0.3s ease-out;
    }}

    @keyframes fadeIn {{
      from {{ opacity: 0; transform: translateY(6px); }}
      to {{ opacity: 1; transform: translateY(0); }}
    }}

    @media (max-width: 900px) {{
      .run-card {{
        grid-template-columns: 1fr;
      }}
    }}
  </style>
</head>
<body>

  <div class="container">
    
    <!-- Hero Header -->
    <div class="hero">
      <div class="hero-top">
        <div class="hero-title-group">
          <h1>⚡ Electron Vision AI · 自动化巡检与探索全景门户</h1>
          <p>多模态大模型端到端巡检全要素大盘 · 所有历史运行轨迹与缺陷汇总</p>
        </div>

        <div class="hero-status-pill">
          <div class="pulse-dot"></div>
          <span>服务常驻就绪 · 实时归档中</span>
        </div>
      </div>

      <!-- Global KPIs -->
      <div class="kpi-grid">
        <div class="kpi-card">
          <div class="label">🚀 累计执行巡检</div>
          <div class="value">{total_runs} <span class="sub">次运行</span></div>
        </div>
        <div class="kpi-card">
          <div class="label">🎯 累计探索步数</div>
          <div class="value">{total_steps} <span class="sub">步轨迹</span></div>
        </div>
        <div class="kpi-card" style="border-color: rgba(244, 63, 94, 0.3);">
          <div class="label">🐞 捕获历史缺陷</div>
          <div class="value" style="color: #fb7185;">{total_bugs} <span class="sub">个已归档</span></div>
        </div>
        <div class="kpi-card">
          <div class="label">⏱️ 最近更新时间</div>
          <div class="value" style="font-size: 16px; font-family: var(--font-mono); margin-top: 6px;">{now_str.split(' ')[1]} <span class="sub">{now_str.split(' ')[0]}</span></div>
        </div>
      </div>
    </div>

    <!-- Navigation Tabs -->
    <div class="tabs-bar">
      <button class="tab-btn active" onclick="switchMainTab('tab-runs', event)">
        🎬 历史巡检记录大盘 <span class="badge">{total_runs}</span>
      </button>
      <button class="tab-btn" onclick="switchMainTab('tab-bugs', event)">
        🐞 全局缺陷知识库 <span class="badge" style="background:#f43f5e;color:#fff;">{total_bugs}</span>
      </button>
    </div>

    <!-- Tab 1: Runs List -->
    <div id="tab-runs" class="tab-pane active">
      <div class="filter-bar">
        <div class="filter-pills">
          <button class="filter-pill active" onclick="filterRuns('all', event)">全部模式 ({total_runs})</button>
          <button class="filter-pill" onclick="filterRuns('explore', event)">自主探索</button>
          <button class="filter-pill" onclick="filterRuns('smoke', event)">全量冒烟</button>
          <button class="filter-pill" onclick="filterRuns('yaml', event)">回归测试</button>
        </div>

        <input type="text" id="runSearch" class="search-box" placeholder="搜索 Run ID、宏观目标或日期..." oninput="handleSearch()">
      </div>

      <div id="runsContainer" class="runs-grid"></div>
    </div>

    <!-- Tab 2: Bugs Table -->
    <div id="tab-bugs" class="tab-pane">
      <table class="bugs-table">
        <thead>
          <tr>
            <th style="width: 140px;">缺陷编号</th>
            <th style="width: 220px;">来源 Run ID</th>
            <th>触发步骤 / 页面路径</th>
            <th>异常详情</th>
            <th style="width: 110px;">操作</th>
          </tr>
        </thead>
        <tbody id="bugsTbody"></tbody>
      </table>
    </div>

  </div>

  <script>
    const allRuns = {runs_json};
    const allBugs = {bugs_json};
    let currentFilter = 'all';
    let searchQuery = '';

    function switchMainTab(tabId, event) {{
      document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
      document.querySelectorAll('.tab-pane').forEach(p => p.classList.remove('active'));
      document.getElementById(tabId).classList.add('active');
      event.currentTarget.classList.add('active');
    }}

    function filterRuns(type, event) {{
      currentFilter = type;
      document.querySelectorAll('.filter-pill').forEach(b => b.classList.remove('active'));
      event.currentTarget.classList.add('active');
      renderRuns();
    }}

    function handleSearch() {{
      searchQuery = document.getElementById('runSearch').value.toLowerCase().trim();
      renderRuns();
    }}

    function renderRuns() {{
      const container = document.getElementById('runsContainer');
      const filtered = allRuns.filter(r => {{
        const runId = (r.run_id || '').toLowerCase();
        if (currentFilter === 'explore' && !runId.startsWith('explore_')) return false;
        if (currentFilter === 'smoke' && !runId.startsWith('smoke_')) return false;
        if (currentFilter === 'yaml' && (runId.startsWith('explore_') || runId.startsWith('smoke_'))) return false;

        if (searchQuery) {{
          const matchId = runId.includes(searchQuery);
          const matchObj = (r.macro_objective || '').toLowerCase().includes(searchQuery);
          const matchStart = (r.start_time || '').toLowerCase().includes(searchQuery);
          if (!matchId && !matchObj && !matchStart) return false;
        }}
        return true;
      }});

      if (filtered.length === 0) {{
        container.innerHTML = '<div style="text-align:center;padding:80px;color:var(--text-dim);">没有符合条件的运行记录</div>';
        return;
      }}

      let html = '';
      filtered.forEach(r => {{
        const runId = r.run_id || '';
        let modeClass = 'explore';
        let modeLabel = '自主探索';
        if (runId.startsWith('smoke_')) {{
          modeClass = 'smoke';
          modeLabel = '全量冒烟';
        }} else if (!runId.startsWith('explore_')) {{
          modeClass = 'yaml';
          modeLabel = '回归用例';
        }}

        const kpi = r.kpi || {{}};
        const totalSteps = kpi.total_steps || 0;
        const bugsCount = kpi.bugs_count || 0;
        const apisCount = kpi.apis_count || 0;
        const pagesCount = kpi.page_scopes_count || 0;

        html += `
          <div class="run-card">
            <div class="run-card-main">
              <div class="run-header">
                <span class="mode-tag ${{modeClass}}">${{modeLabel}}</span>
                <span class="run-id-title">${{escapeHtml(runId)}}</span>
              </div>

              <div class="run-meta-row">
                <div class="run-meta-item">⏱️ 耗时: <strong>${{escapeHtml(r.duration || '未知')}}</strong></div>
                <div class="run-meta-item">📅 开始: <strong>${{escapeHtml(r.start_time || '未知')}}</strong></div>
                <div class="run-meta-item">🏁 结束: <strong>${{escapeHtml(r.end_time || '未知')}}</strong></div>
              </div>

              <div class="objective-quote">
                <strong>🎯 宏观目标:</strong> ${{escapeHtml(r.macro_objective || '常规测试')}}
              </div>

              <div class="run-badges-row">
                <div class="metric-badge">🎯 ${{totalSteps}} 步轨迹</div>
                <div class="metric-badge ${{bugsCount > 0 ? 'bugs' : ''}}">🐞 ${{bugsCount}} 个缺陷</div>
                <div class="metric-badge">🌐 ${{apisCount}} 个业务接口</div>
                <div class="metric-badge">🗺️ ${{pagesCount}} 个业务页面</div>
              </div>
            </div>

            <div>
              <a href="${{r.report_url}}" class="open-report-btn">
                <span>👉 查看视觉全景报告</span>
              </a>
            </div>
          </div>
        `;
      }});

      container.innerHTML = html;
    }}

    function renderBugs() {{
      const tbody = document.getElementById('bugsTbody');
      if (allBugs.length === 0) {{
        tbody.innerHTML = '<tr><td colspan="5" style="text-align:center;padding:50px;color:var(--text-dim);">🎉 全局无任何历史缺陷记录</td></tr>';
        return;
      }}

      let html = '';
      allBugs.forEach(b => {{
        html += `
          <tr>
            <td><span style="font-family:var(--font-mono);font-weight:700;color:#fb7185;">${{escapeHtml(b.id)}}</span></td>
            <td><span style="font-family:var(--font-mono);color:var(--text-muted);font-size:12px;">${{escapeHtml(b.run_id)}}</span></td>
            <td style="color:#cbd5e1;">${{escapeHtml(b.step || '(无步骤)')}}</td>
            <td><div style="font-family:var(--font-mono);font-size:12px;color:#fca5a5;max-width:400px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${{escapeHtml(b.actual || '')}}</div></td>
            <td><a href="${{b.report_link}}" class="bug-link">核验证据 →</a></td>
          </tr>
        `;
      }});
      tbody.innerHTML = html;
    }}

    function escapeHtml(str) {{
      if (!str) return '';
      return String(str)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#039;');
    }}

    document.addEventListener('DOMContentLoaded', () => {{
      renderRuns();
      renderBugs();
    }});
  </script>
</body>
</html>
"""
        out_file.write_text(html_content, encoding="utf-8")
        logger.info(f"🎉 统一巡检门户大盘已生成: {out_file}")
        return out_file

    def serve(self, port: int = 8080):
        """启动轻量本地/局域网 Web 门户服务"""
        import http.server
        import socketserver

        self.build_index_html()
        os.chdir(self.runs_dir)

        Handler = http.server.SimpleHTTPRequestHandler
        # 支持端口复用
        socketserver.TCPServer.allow_reuse_address = True

        with socketserver.TCPServer(("", port), Handler) as httpd:
            print("\n" + "=" * 65)
            print(f"🚀 Electron Vision AI 全量巡检大盘门户已启动！")
            print(f"👉 本地访问地址: http://localhost:{port}/")
            print(f"👉 局域网访问:   http://0.0.0.0:{port}/ (或使用你的内网 IP)")
            print(f"📁 根目录指向:   {self.runs_dir}")
            print("=" * 65 + "\n")
            try:
                httpd.serve_forever()
            except KeyboardInterrupt:
                print("\n🛑 服务已停止。")


def main():
    parser = argparse.ArgumentParser(description="Electron Vision AI 统一巡检门户引擎")
    parser.add_argument("--build", action="store_true", help="仅重新生成 reports/runs/index.html")
    parser.add_argument("--serve", action="store_true", help="启动常驻 Web 服务")
    parser.add_argument("--port", type=int, default=8080, help="Web 服务端口 (默认 8080)")
    args = parser.parse_args()

    hub = ReportHub()

    if args.serve:
        hub.serve(port=args.port)
    else:
        out = hub.build_index_html()
        print(f"✅ 门户已生成：file:///{out.as_posix()}\n如果需要在线浏览，请运行: python utils/report_hub.py --serve --port {args.port}")


if __name__ == "__main__":
    main()
