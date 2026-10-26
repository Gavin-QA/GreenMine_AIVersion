"""
==============================================================================
utils/zentao_sync.py —— 禅道缺陷双向绑定与自动提单同步工具 (ZenTao Bug Sync Engine)
==============================================================================

功能与职责：
1. 身份与血缘标记：
   - 提交到禅道时，标题自动带上【AI自动化·<矿山名称>】[BUG-ID] 标识
   - 提交富文本详单，包含：触发业务路径、报错堆栈/接口失败快照、复现频次、AI 根因分析笔记、完整测试报告回溯链接
2. 双向闭环与自动回填：
   - 提交成功后自动获取禅道生成的 Bug 编号 (zentao_id)，并自动回填至全局缺陷知识库 (artifacts/bugs/global_bugs_*.json)
     以及单次运行目录中的 (reports/runs/<app>/<run_id>/bugs/<bug_id>.json)
   - 状态联动流转为“已提单”
3. 支持人工手动绑定：
   - 针对在禅道网页端已有人工建单或历史单据的情况，支持一键将本地 Bug ID 绑定至指定禅道号
"""

from __future__ import annotations

import argparse
import html
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

# Windows GBK 终端保护
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

PROJECT_ROOT = Path(__file__).parent.parent.resolve()
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config.settings import settings
from utils.paths import GLOBAL_BUGS_DIR, get_all_run_folders

logger = logging.getLogger("zentao_sync")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

APP_NAME_MAP = {
    "zhaiwan": "寨湾矿山",
    "liwutong": "里伍铜矿山",
    "default": "寨湾矿山"
}


class ZenTaoClient:
    def __init__(self, url: Optional[str] = None, account: Optional[str] = None, password: Optional[str] = None):
        self.url = (url or settings.zentao_url or "http://192.140.163.129:8080").rstrip("/")
        self.account = account or settings.zentao_account or "guoxiaoqi"
        self.password = password or settings.zentao_password or ""
        self.default_product_id = settings.zentao_default_product_id or 10
        self._token: Optional[str] = None

    def get_token(self) -> str:
        """获取或复用禅道 REST API 访问令牌"""
        if self._token:
            return self._token
        import requests

        token_url = f"{self.url}/api.php/v1/tokens"
        payload = {"account": self.account, "password": self.password}
        try:
            resp = requests.post(token_url, json=payload, timeout=10)
            if resp.status_code not in (200, 201):
                raise RuntimeError(f"禅道鉴权失败 (HTTP {resp.status_code}): {resp.text}")
            res_json = resp.json()
            token = res_json.get("token")
            if not token:
                raise RuntimeError(f"响应中未包含 token: {res_json}")
            self._token = token
            return token
        except Exception as e:
            logger.error(f"连接禅道服务器 {self.url} 失败: {e}")
            raise

    def get_products(self) -> List[Dict[str, Any]]:
        """列出当前用户有权访问的禅道产品列表"""
        import requests

        token = self.get_token()
        url = f"{self.url}/api.php/v1/products"
        resp = requests.get(url, headers={"Token": token}, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        return data.get("products", [])

    def submit_bug(
        self,
        product_id: int,
        title: str,
        steps_html: str,
        severity: int = 3,
        pri: int = 3,
        bug_type: str = "codeerror",
    ) -> Dict[str, Any]:
        """向禅道提交缺陷"""
        import requests

        token = self.get_token()
        url = f"{self.url}/api.php/v1/bugs"
        payload = {
            "product": int(product_id),
            "title": title,
            "steps": steps_html,
            "severity": int(severity),
            "pri": int(pri),
            "type": bug_type,
            "os": "windows",
            "browser": "electron",
        }
        resp = requests.post(url, json=payload, headers={"Token": token}, timeout=15)
        if resp.status_code not in (200, 201):
            raise RuntimeError(f"提交禅道缺陷失败 (HTTP {resp.status_code}): {resp.text}")
        return resp.json()


def find_bug_in_databases(bug_id: str, app_name: Optional[str] = None) -> tuple[Optional[Dict[str, Any]], Optional[Path], List[Path]]:
    """在全局库与运行目录中精准定位 Bug 数据与对应的物理文件路径"""
    matched_bug: Optional[Dict[str, Any]] = None
    matched_global_file: Optional[Path] = None
    matched_run_files: List[Path] = []

    # 1. 查找全局库文件
    candidates = []
    if app_name:
        candidates.append(GLOBAL_BUGS_DIR / f"global_bugs_{app_name}.json")
    active_app = getattr(settings, "active_app", "zhaiwan")
    candidates.append(GLOBAL_BUGS_DIR / f"global_bugs_{active_app}.json")
    candidates.append(GLOBAL_BUGS_DIR / "global_bugs_zhaiwan.json")
    candidates.append(GLOBAL_BUGS_DIR / "global_bugs_liwutong.json")
    candidates.append(GLOBAL_BUGS_DIR / "global_bugs.json")

    # 去重
    seen_paths = set()
    unique_candidates = []
    for c in candidates:
        if c.resolve() not in seen_paths and c.exists():
            seen_paths.add(c.resolve())
            unique_candidates.append(c)

    for g_path in unique_candidates:
        try:
            with open(g_path, "r", encoding="utf-8") as f:
                bugs = json.load(f)
            for b in bugs:
                if b.get("id") == bug_id:
                    matched_bug = b
                    matched_global_file = g_path
                    break
            if matched_bug:
                break
        except Exception as e:
            logger.debug(f"读取 {g_path} 异常: {e}")

    # 2. 查找运行目录中的 bug json
    for r_dir in get_all_run_folders():
        r_bug_file = r_dir / "bugs" / f"{bug_id}.json"
        if r_bug_file.exists():
            matched_run_files.append(r_bug_file)
            if not matched_bug:
                try:
                    with open(r_bug_file, "r", encoding="utf-8") as rf:
                        matched_bug = json.load(rf)
                except Exception:
                    pass

    return matched_bug, matched_global_file, matched_run_files


def format_bug_details_html(bug: Dict[str, Any], app_key: str) -> str:
    """组织提交给禅道的结构化富文本内容"""
    app_chinese = APP_NAME_MAP.get(app_key, "寨湾矿山")
    ui_path = html.escape(str(bug.get("ui_path") or "首页/未知"))
    actual_error = html.escape(str(bug.get("actual") or bug.get("error_log") or "无报错日志"))
    occurrences = bug.get("occurrences", 1)
    run_id = html.escape(str(bug.get("run_id") or "未知"))
    date_str = html.escape(str(bug.get("date") or bug.get("last_seen") or "未知"))
    analysis = html.escape(str(bug.get("analysis_notes") or "AI 暂未录入复盘备注"))

    html_parts = [
        f"<p><strong>【测试来源】</strong>Electron Vision AI 自动化多模态探索巡检系统</p>",
        f"<p><strong>【所属矿山】</strong>{app_chinese} (App: {app_key})</p>",
        f"<p><strong>【巡检批次】</strong><code>{run_id}</code> (首次发现: {date_str}，历史累计复现: {occurrences} 次)</p>",
        f"<p><strong>【业务路径】</strong>📍 <code>{ui_path}</code></p>",
        f"<hr/>",
        f"<p><strong>【案发现场异常 / 接口堆栈】</strong></p>",
        f"<pre style='background:#f1f5f9;color:#0f172a;padding:10px;border-radius:4px;border:1px solid #cbd5e1;font-family:monospace;white-space:pre-wrap;'>{actual_error}</pre>",
        f"<hr/>",
        f"<p><strong>【AI 智能归因与复盘研判】</strong></p>",
        f"<div style='background:#eff6ff;color:#1e3a8a;padding:10px;border-radius:4px;border-left:4px solid #3b82f6;'>{analysis}</div>",
    ]
    return "".join(html_parts)


def update_bug_records(bug_id: str, zentao_id: str, global_file: Optional[Path], run_files: List[Path]) -> bool:
    """将禅道 ID 和已提单状态同步持久化写入所有目标文件"""
    zentao_id_str = str(zentao_id).strip()
    updated = False

    # 1. 更新全局缺陷库
    if global_file and global_file.exists():
        try:
            with open(global_file, "r", encoding="utf-8") as f:
                bugs = json.load(f)
            changed = False
            for b in bugs:
                if b.get("id") == bug_id:
                    b["zentao_id"] = zentao_id_str
                    b["status"] = "已提单"
                    changed = True
                    break
            if changed:
                with open(global_file, "w", encoding="utf-8") as f:
                    json.dump(bugs, f, ensure_ascii=False, indent=2)
                logger.info(f"💾 已更新全局缺陷库: {global_file.name} (zentao_id: {zentao_id_str})")
                updated = True
        except Exception as e:
            logger.error(f"更新全局缺陷库 {global_file} 失败: {e}")

    # 2. 更新运行目录单据
    for rf in run_files:
        try:
            with open(rf, "r", encoding="utf-8") as f:
                b_data = json.load(f)
            b_data["zentao_id"] = zentao_id_str
            b_data["status"] = "已提单"
            with open(rf, "w", encoding="utf-8") as f:
                json.dump(b_data, f, ensure_ascii=False, indent=2)
            logger.info(f"💾 已更新运行单据: {rf.as_posix()} (zentao_id: {zentao_id_str})")
            updated = True
        except Exception as e:
            logger.error(f"更新运行单据 {rf} 失败: {e}")

    return updated


def main():
    parser = argparse.ArgumentParser(description="禅道缺陷双向绑定与自动提单工具")
    parser.add_argument("--list-products", action="store_true", help="列出当前禅道实例中所有可访问的产品")
    parser.add_argument("--submit-bug", type=str, help="指定本地 Bug ID 并自动提交到禅道 (如 BUG-20261023-003)")
    parser.add_argument("--bind", type=str, help="指定本地 Bug ID 进行手动绑定")
    parser.add_argument("--zentao-id", type=str, help="与 --bind 搭配使用的禅道 Bug 编号 (如 852)")
    parser.add_argument("--product-id", type=int, help="禅道产品 ID (默认读取配置)")
    parser.add_argument("--app", type=str, help="所属矿山应用 (zhaiwan / liwutong，默认自适应)")

    args = parser.parse_args()
    client = ZenTaoClient()

    if args.list_products:
        try:
            products = client.get_products()
            print("\n📋 禅道可用产品列表 (Product List):")
            print("-" * 55)
            for p in products:
                print(f"  • ID: {p.get('id'):<4} | 名称: {p.get('name')}")
            print("-" * 55)
            print(f"👉 当前配置默认产品 ID: {client.default_product_id}\n")
        except Exception as e:
            print(f"❌ 获取产品列表失败: {e}")
            sys.exit(1)
        return

    if args.bind:
        bug_id = args.bind.strip()
        if not args.zentao_id:
            print("❌ 手动绑定模式必须提供 --zentao-id 参数，例如: --bind BUG-20261023-003 --zentao-id 852")
            sys.exit(1)
        zentao_id = str(args.zentao_id).strip()

        bug, g_file, r_files = find_bug_in_databases(bug_id, args.app)
        if not bug:
            print(f"❌ 在本地缺陷知识库及运行目录中未找到 Bug: {bug_id}")
            sys.exit(1)

        ok = update_bug_records(bug_id, zentao_id, g_file, r_files)
        if ok:
            print(f"🎉 成功完成双向绑定！Bug {bug_id} ↔ 禅道 #{zentao_id} (状态联动: 已提单)")
            print(f"🔗 禅道查看直达链接: {client.url}/index.php?m=bug&f=view&bugID={zentao_id}")
        else:
            print(f"❌ 绑定写入失败，请检查文件权限")
            sys.exit(1)
        return

    if args.submit_bug:
        bug_id = args.submit_bug.strip()
        target_product_id = args.product_id or client.default_product_id

        bug, g_file, r_files = find_bug_in_databases(bug_id, args.app)
        if not bug:
            print(f"❌ 在本地缺陷知识库及运行目录中未找到 Bug: {bug_id}")
            sys.exit(1)

        app_key = args.app or getattr(settings, "active_app", "zhaiwan")
        if not args.app and g_file and "liwutong" in g_file.name:
            app_key = "liwutong"
        app_chinese = APP_NAME_MAP.get(app_key, "寨湾矿山")

        raw_title = bug.get("title") or "自动化探索发现异常"
        clean_title = raw_title.replace("【AI自动化】", "").strip()
        final_title = f"【AI自动化·{app_chinese}】[{bug_id}] {clean_title}"

        # 禅道严重度 mapping
        sev_raw = bug.get("severity", 3)
        try:
            sev_int = int(sev_raw)
        except Exception:
            sev_int = 3
        if sev_int not in (1, 2, 3, 4):
            sev_int = 3

        steps_html = format_bug_details_html(bug, app_key)

        print(f"\n🚀 正在向禅道提交缺陷...")
        print(f"  • 禅道地址: {client.url}")
        print(f"  • 产品 ID:  {target_product_id}")
        print(f"  • 缺陷标题: {final_title}")
        print(f"  • 严重等级: {sev_int}")

        try:
            res = client.submit_bug(
                product_id=target_product_id,
                title=final_title,
                steps_html=steps_html,
                severity=sev_int,
                pri=sev_int,
            )
            zen_id = res.get("id")
            if not zen_id:
                raise RuntimeError(f"提单成功但未能解析出禅道 Bug ID: {res}")

            print(f"✅ 禅道提单成功！分配单号: #{zen_id}")
            update_bug_records(bug_id, str(zen_id), g_file, r_files)
            print(f"🎉 本地缺陷库已自动回填关联，状态流转为【已提单】！")
            print(f"🔗 禅道查看直达链接: {client.url}/index.php?m=bug&f=view&bugID={zen_id}\n")
        except Exception as e:
            print(f"❌ 提单失败: {e}")
            sys.exit(1)
        return

    parser.print_help()


if __name__ == "__main__":
    main()
