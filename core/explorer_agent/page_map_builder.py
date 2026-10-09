import logging
import re
import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List

from utils.paths import TOPOLOGY_DIR, TOPOLOGY_SNAPSHOTS_DIR, DOCS_DIR

logger = logging.getLogger("explorer_agent.page_map")

class PageMapBuilder:
    @staticmethod
    def parse_base_rules() -> dict:
        """从 explore_rules.md 中提取预设的一、二级菜单，作为动态架构树的底座"""
        base_tree = {}
        try:
            rules_path = Path("docs") / "explore_rules.md"
            if rules_path.exists():
                content = rules_path.read_text(encoding="utf-8")
                # 简单解析 Markdown 表格
                for line in content.splitlines():
                    if "|" in line and "---" not in line:
                        parts = [p.strip() for p in line.split("|")]
                        if len(parts) >= 4 and parts[2] != "一级菜单":
                            # 提取 1、2 级菜单（去掉加粗的 **）
                            lvl1 = parts[2].replace("**", "").strip()
                            lvl2 = parts[3].replace("**", "").strip()
                            if lvl1 and lvl2:
                                if lvl1 not in base_tree:
                                    base_tree[lvl1] = {}
                                if lvl2 not in base_tree[lvl1]:
                                    base_tree[lvl1][lvl2] = {}
                logger.info(f"🌳 成功加载基准架构底座！共包含 {len(base_tree)} 个一级模块与 {sum(len(v) for v in base_tree.values())} 个二级业务菜单。")
        except Exception as e:
            logger.warning(f"加载基准架构底座失败: {e}")
        return base_tree

    @staticmethod
    def format_node_label(name: str, depth: int = 0) -> str:
        """根据节点语义和层级，为节点赋予极度直观的组件 Emoji"""
        clean_name = str(name or "").strip()
        if not clean_name:
            return ""
        # 如果已经带有常见 Emoji，则直接返回
        if any(clean_name.startswith(em) for em in ["📁", "📄", "📋", "🪟", "🔲", "📝", "🔽", "☑️", "🗺️", "📊", "📦", "⚙️"]):
            return clean_name

        lower = clean_name.lower()

        # 1. 弹窗/抽屉/浮层
        if any(k in clean_name for k in ["弹窗", "浮窗", "浮层", "抽屉", "对话框"]) or "modal" in lower or "dialog" in lower:
            return f"🪟 {clean_name}"

        # 2. 地图/3D大屏渲染
        if any(k in clean_name for k in ["地图", "定位地图", "采场可视化", "三维", "3D", "数字孪生"]) or "map" in lower:
            return f"🗺️ {clean_name}"

        # 3. 表格/列表/滚动列表
        if any(k in clean_name for k in ["列表", "表格", "滚动列表", "台账", "清单", "记录"]) or "table" in lower or "list" in lower:
            return f"📋 {clean_name}"

        # 4. 下拉框/选择器
        if any(k in clean_name for k in ["下拉", "选择器", "下拉框", "日期范围", "时间范围"]) or "select" in lower:
            return f"🔽 {clean_name}"

        # 5. 勾选框/单选框
        if any(k in clean_name for k in ["勾选", "单选", "复选", "开关", "switch", "checkbox", "radio"]):
            return f"☑️ {clean_name}"

        # 6. 输入框
        if any(k in clean_name for k in ["输入框", "搜索框", "文本框", "input"]):
            return f"📝 {clean_name}"

        # 7. 按钮/操作
        if any(k in clean_name for k in ["按钮", "查询", "重置", "确定", "取消", "导出", "提交", "刷新", "操作"]) or "btn" in lower or "button" in lower:
            return f"🔲 {clean_name}"

        # 8. 图表/曲线/进度条
        if any(k in clean_name for k in ["图表", "曲线", "柱状图", "饼图", "进度条", "趋势图", "统计"]) or "chart" in lower:
            return f"📊 {clean_name}"

        # 9. 基于层级默认分配
        if depth == 0:
            return f"📁 {clean_name}"
        elif depth == 1:
            return f"📄 {clean_name}"
        elif depth == 2:
            return f"📋 {clean_name}"

        return clean_name

    @staticmethod
    def fold_duplicate_list_items(tree: dict) -> dict:
        """
        对列表/表格内部重复的操作按钮进行泛化聚合折叠。
        例如将“第一条记录的‘历史轨迹’按钮”、“第二条记录的‘历史轨迹’按钮”聚合为“‘历史轨迹’按钮（操作列）”
        """
        if not isinstance(tree, dict):
            return tree

        new_tree = {}
        row_action_pattern = re.compile(r'(?:第\s*[\d一二三四五六七八九十]+\s*条|【[^】]+】|（[^）]+）|\b\w+\b\s*行)(?:记录)?(?:的)?\s*[‘"\'“]?(.*?)[’"\'”]?\s*(?:按钮|操作|查看|编辑|删除|轨迹)?$')

        for key, subtree in tree.items():
            processed_subtree = PageMapBuilder.fold_duplicate_list_items(subtree)
            
            # 检测是否可以泛化
            match = row_action_pattern.search(key)
            if match and any(k in key for k in ["按钮", "操作", "轨迹", "查看", "编辑", "删除"]):
                action_name = match.group(1).strip().strip("‘'“\"”’")
                if action_name:
                    folder_key = f"🔲 “{action_name}”按钮（操作列）"
                    if folder_key not in new_tree:
                        new_tree[folder_key] = processed_subtree
                    else:
                        new_tree[folder_key].update(processed_subtree)
                    continue

            new_tree[key] = processed_subtree

        return new_tree

    @staticmethod
    def render_markdown_tree(tree: dict, prefix: str = "", depth: int = 0) -> str:
        """
        将树形字典递归渲染为纯 Markdown 目录树形式：
        📁 首页
        ├── 📄 生产管理
        │   ├── 📋 卡车调度
        │   │   ├── 📋 滚动列表
        │   │   │   └── 🔲 “历史轨迹”按钮
        """
        lines = []
        items = list(tree.items())
        total = len(items)

        for i, (key, subtree) in enumerate(items):
            is_last = (i == total - 1)
            branch = "└── " if is_last else "├── "
            formatted_name = PageMapBuilder.format_node_label(key, depth=depth)

            if depth == 0:
                # 根节点不加前缀树枝，或者加根标记
                lines.append(f"{formatted_name}")
                child_prefix = "    "
            else:
                lines.append(f"{prefix}{branch}{formatted_name}")
                child_prefix = prefix + ("    " if is_last else "│   ")

            if isinstance(subtree, dict) and subtree:
                child_text = PageMapBuilder.render_markdown_tree(subtree, prefix=child_prefix, depth=depth + 1)
                if child_text:
                    lines.append(child_text)

        return "\n".join(lines)

    @staticmethod
    def dict_to_mermaid_string(page_tree: dict) -> str:
        """将架构树字典转换为精简易读的 Mermaid 拓扑图"""
        lines = ["graph LR"]
        
        node_id_counter = [0]
        node_id_map = {}
        
        def get_node_id(name):
            if name not in node_id_map:
                node_id_map[name] = f"N{node_id_counter[0]}"
                node_id_counter[0] += 1
            return node_id_map[name]
            
        def traverse(tree, parent_name=None, depth=1):
            for child_name, child_tree in tree.items():
                clean_child = child_name.replace('"', '').replace('[', '').replace(']', '').replace('(', '（').replace(')', '）')
                c_id = get_node_id(clean_child)
                
                if parent_name:
                    clean_parent = parent_name.replace('"', '').replace('[', '').replace(']', '').replace('(', '（').replace(')', '）')
                    p_id = get_node_id(clean_parent)
                    indent = "    " * depth
                    lines.append(f'{indent}{p_id}["{clean_parent}"] --> {c_id}["{clean_child}"]')
                
                if isinstance(child_tree, dict):
                    traverse(child_tree, clean_child, depth + 1 if parent_name else 1)
                
        traverse(page_tree)
        return "\n".join(lines)

    @staticmethod
    def sanitize_page_tree(tree: dict, base_rules: dict = None, is_root: bool = True) -> dict:
        """
        清洗架构树，剔除全局导航冗余（如“顶部导航栏”、“下拉菜单”、非法嵌套的一级菜单等），
        剔除“等待...加载完成”等纯过渡性辅助动作，解包伪浮窗容器，
        确保只有纯粹的业务组件和页面容器被挂载在架构树中。
        """
        if not isinstance(tree, dict):
            return tree

        nav_noise_keywords = ["顶部导航栏", "导航栏", "下拉菜单", "菜单栏"]
        wait_noise_keywords = ["等待", "wait", "加载完成", "完全加载", "完全可见", "渲染完成"]
        base_l1_keys = set(base_rules.keys()) if base_rules else set()

        sanitized = {}
        for key, subtree in tree.items():
            # 1. 剔除导航栏、下拉菜单等临时过渡组件
            if any(noise in key for noise in nav_noise_keywords):
                continue

            # 2. 剔除等待/过渡动作辅助描述（如“等待‘胶带监测预警’列表加载完成”）
            if any(noise in key for noise in wait_noise_keywords):
                continue

            # 3. 避免一级菜单被错误嵌套在非根层级下（例如“首页”下面错误嵌套了“生产管理”）
            if not is_root and base_rules and key in base_l1_keys:
                continue

            # 4. 递归清洗子树
            cleaned_subtree = PageMapBuilder.sanitize_page_tree(subtree, base_rules=base_rules, is_root=False)

            # 5. 解包伪浮窗（例如““智能胶带运输”浮窗”或““底部标签栏中的‘1#中央配电室’标签”浮窗”）
            # 许多 Tab 切换或按钮点击因 3D 渲染光影变暗被误当成了浮窗，将子节点提升解包到当前层级
            if ("”浮窗" in key or "”弹窗" in key or "浮窗" in key) and any(k in key for k in ["标签", "tab", "Tab", "按钮", "菜单", "导航", "总览", "运输"]):
                PageMapBuilder._deep_merge(sanitized, cleaned_subtree)
                continue

            # 6. 跨模块子Tab泄漏伪容器智能解包（如“证照管理”下误挂包含证照卡片的“资源储量”；或“矿山简介”下误挂包含简介内容的“采矿许可证”）
            cert_keywords = ["许可证", "执照", "证号", "证照"]
            if "证照管理" in sanitized or any(k in key for k in ["证照", "资质"]):
                pass
            if "资源储量" in key and any(any(kw in item for kw in cert_keywords) for item in cleaned_subtree.keys()):
                logger.info(f"🧹 [Sanitize] 识别并解包跨页泄漏的伪容器: [{key}]，将其中的证照组件提升至上一级")
                PageMapBuilder._deep_merge(sanitized, cleaned_subtree)
                continue

            if "采矿许可证" in key and any(item in cleaned_subtree for item in ["矿山简介卡片", "资源储量", "矿石品位图表"]):
                logger.info(f"🧹 [Sanitize] 识别并解包矿山简介内误挂的采矿许可证伪节点: [{key}]")
                PageMapBuilder._deep_merge(sanitized, cleaned_subtree)
                continue

            # 7. 解包在数据卡片内部误吞的独立媒体播放器（如“资源储量”内部误吞了“企业简介视频播放器”）
            if any(card in key for card in ["资源储量", "数据卡片", "统计", "品位"]) and "企业简介视频播放器" in cleaned_subtree:
                player_node = cleaned_subtree.pop("企业简介视频播放器")
                if "企业简介视频播放器" not in sanitized:
                    sanitized["企业简介视频播放器"] = player_node
                else:
                    PageMapBuilder._deep_merge(sanitized["企业简介视频播放器"], player_node)

            # 8. 标签名称规范化（去除前缀冗余，使重复标签自动折叠合并）
            norm_key = key
            if "底部标签栏中的‘" in norm_key:
                norm_key = norm_key.replace("底部标签栏中的‘", "").replace("’标签", "标签").replace("’", "")
            elif "底部标签栏中‘" in norm_key:
                norm_key = norm_key.replace("底部标签栏中‘", "").replace("’标签", "标签").replace("’", "")

            # 9. 同名/同义套娃容器自动解包（如“资源储量”同级存在“资源储量数据卡片”，或内部包含同名卡片）
            clean_norm = re.sub(r'^[📁📄📋🪟🔲📝🔽☑️🗺️📊📦⚙️\s]+', '', norm_key).strip()
            suffix_pattern = r'(?:数据卡片|卡片区域|卡片|模块|区域|容器|列表|表格|图表)$'
            core_norm = re.sub(suffix_pattern, '', clean_norm).strip()

            # 检查 sanitized 中是否已有核心词一致的容器，若有则直接合并
            merged_into_existing = False
            if core_norm:
                for existing_k in list(sanitized.keys()):
                    clean_ex = re.sub(r'^[📁📄📋🪟🔲📝🔽☑️🗺️📊📦⚙️\s]+', '', existing_k).strip()
                    core_ex = re.sub(suffix_pattern, '', clean_ex).strip()
                    if core_ex and (core_norm == core_ex or (len(core_norm) >= 3 and core_norm in core_ex) or (len(core_ex) >= 3 and core_ex in core_norm)):
                        # 合并入现存的较精炼名称的节点
                        PageMapBuilder._deep_merge(sanitized[existing_k], cleaned_subtree)
                        merged_into_existing = True
                        break

            if not merged_into_existing:
                if norm_key in sanitized and isinstance(sanitized[norm_key], dict) and isinstance(cleaned_subtree, dict):
                    PageMapBuilder._deep_merge(sanitized[norm_key], cleaned_subtree)
                else:
                    sanitized[norm_key] = cleaned_subtree

        # 10. 检查当前层级内部各子树，解包其内部与自身同义的套娃子容器
        for parent_k, parent_subtree in list(sanitized.items()):
            if isinstance(parent_subtree, dict):
                clean_pk = re.sub(r'^[📁📄📋🪟🔲📝🔽☑️🗺️📊📦⚙️\s]+', '', parent_k).strip()
                core_pk = re.sub(suffix_pattern, '', clean_pk).strip()
                if core_pk:
                    for child_k in list(parent_subtree.keys()):
                        clean_ck = re.sub(r'^[📁📄📋🪟🔲📝🔽☑️🗺️📊📦⚙️\s]+', '', child_k).strip()
                        core_ck = re.sub(suffix_pattern, '', clean_ck).strip()
                        if core_ck and (core_pk == core_ck or (len(core_pk) >= 3 and core_pk in core_ck)):
                            # 解包该子节点
                            child_sub = parent_subtree.pop(child_k)
                            if isinstance(child_sub, dict):
                                PageMapBuilder._deep_merge(parent_subtree, child_sub)

        return sanitized

    @staticmethod
    def _deep_merge(target: dict, source: dict):
        """递归深度合并两棵架构树，自动过滤全局导航与过渡等待噪音"""
        noise_keywords = ["顶部导航栏", "导航栏", "下拉菜单", "菜单栏", "等待", "wait", "加载完成", "完全加载", "完全可见", "渲染完成"]
        for k, v in source.items():
            if any(noise in k for noise in noise_keywords):
                continue
            if k in target and isinstance(target[k], dict) and isinstance(v, dict):
                PageMapBuilder._deep_merge(target[k], v)
            else:
                target[k] = v

    @staticmethod
    def load_global_tree() -> dict:
        """从 artifacts/topology/global_page_tree.json 加载累积架构树，若无则从 docs/explore_rules.md 加载基准底座"""
        base_tree = PageMapBuilder.parse_base_rules()
        global_file = TOPOLOGY_DIR / "global_page_tree.json"
        
        # 兼容性回退检查：若新路径不存在则尝试读取 docs/ 下的历史数据
        if not global_file.exists():
            legacy_file = DOCS_DIR / "global_page_tree.json"
            if legacy_file.exists():
                global_file = legacy_file
                
        if global_file.exists():
            try:
                with open(global_file, "r", encoding="utf-8") as f:
                    history_tree = json.load(f)
                PageMapBuilder._deep_merge(base_tree, history_tree)
                logger.info(f"📚 成功继承历史全局架构树: {global_file}")
            except Exception as e:
                logger.warning(f"加载全局历史架构树失败: {e}")
        return base_tree

    @staticmethod
    def reset_module_subtree(tree: dict, module_name: str) -> bool:
        """
        在架构树中查找指定的一级或二级菜单模块，并清空其所有子节点（重置为空分支），
        同时实时同步清空持久化文件中的历史节点，确保全新重探。
        """
        clean_target = module_name.strip("【】'\" ")
        
        def _clear_in_dict(d: dict) -> bool:
            cleared = False
            for l1, l2_dict in d.items():
                if not isinstance(l2_dict, dict):
                    continue
                # 匹配一级主模块 (例如 "智控管理")
                if l1 == clean_target or (len(clean_target) >= 2 and (clean_target in l1 or l1 in clean_target)):
                    for l2 in list(l2_dict.keys()):
                        l2_dict[l2] = {}
                    logger.info(f"🧹 [PageMapBuilder] 已重置一级主模块【{l1}】下所有二级业务菜单的子节点！")
                    cleared = True
                    continue
                # 匹配二级业务菜单 (例如 "智能通风" 或 "采掘设备")
                for l2 in list(l2_dict.keys()):
                    if l2 == clean_target or (len(clean_target) >= 2 and (clean_target in l2 or l2 in clean_target)):
                        l2_dict[l2] = {}
                        logger.info(f"🧹 [PageMapBuilder] 已重置架构树中模块【{l1} -> {l2}】的子节点，准备全新重探！")
                        cleared = True
            return cleared

        reset_ok = _clear_in_dict(tree)

        # 同步清空持久化文件
        for target_file in [TOPOLOGY_DIR / "global_page_tree.json", DOCS_DIR / "global_page_tree.json"]:
            if target_file.exists():
                try:
                    with open(target_file, "r", encoding="utf-8") as f:
                        history_tree = json.load(f)
                    if _clear_in_dict(history_tree):
                        with open(target_file, "w", encoding="utf-8") as f:
                            json.dump(history_tree, f, ensure_ascii=False, indent=2)
                        reset_ok = True
                except Exception as e:
                    logger.warning(f"同步重置 {target_file.name} 失败: {e}")

        return reset_ok

    @staticmethod
    def _create_topology_snapshot(source_file: Path) -> None:
        """自动为全局架构树创建带时间戳的版本快照，防止模型幻觉或脏数据覆盖历史基线"""
        try:
            if not source_file.exists() or source_file.stat().st_size == 0:
                return
            TOPOLOGY_SNAPSHOTS_DIR.mkdir(parents=True, exist_ok=True)
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            snapshot_file = TOPOLOGY_SNAPSHOTS_DIR / f"page_tree_{ts}.json"
            shutil.copy2(source_file, snapshot_file)
            
            # 限制历史快照数量（最多保留 20 份），滚动清理旧快照
            snapshots = sorted(TOPOLOGY_SNAPSHOTS_DIR.glob("page_tree_*.json"), key=lambda p: p.stat().st_mtime)
            if len(snapshots) > 20:
                for old_snap in snapshots[:-20]:
                    try:
                        old_snap.unlink()
                    except Exception:
                        pass
        except Exception as e:
            logger.warning(f"创建拓扑快照备份失败 (非致命): {e}")

    @staticmethod
    def export_page_map(page_tree: dict):
        """
        统一导出页面架构地图：
        包含【纯 Markdown 结构化组件拓扑大纲】与【Mermaid 辅助图】
        自动与 artifacts/topology/global_page_tree.json 持久化合并，并自动留存历史快照，永不因清空日志丢失历史记录！
        同时镜像同步至 docs/auto_page_map.md 保证 IDE 即时预览。
        """
        try:
            TOPOLOGY_DIR.mkdir(parents=True, exist_ok=True)
            DOCS_DIR.mkdir(parents=True, exist_ok=True)
            
            artifacts_map_path = TOPOLOGY_DIR / "auto_page_map.md"
            artifacts_global_file = TOPOLOGY_DIR / "global_page_tree.json"
            docs_map_path = DOCS_DIR / "auto_page_map.md"
            docs_global_file = DOCS_DIR / "global_page_tree.json"

            # 1. 加载基准骨架并清洗导航噪音节点
            base_tree = PageMapBuilder.parse_base_rules()
            
            # 确保 6 个一级菜单与 33 个二级菜单底座绝对存在
            merged_tree = {}
            for l1, l2_dict in base_tree.items():
                merged_tree[l1] = dict(l2_dict)

            # 先合入全局历史持久化树（防止清空日志后丢失以往探索的模块）
            read_history_file = artifacts_global_file if artifacts_global_file.exists() else docs_global_file
            if read_history_file.exists():
                try:
                    with open(read_history_file, "r", encoding="utf-8") as f:
                        history_tree = json.load(f)
                    PageMapBuilder._deep_merge(merged_tree, history_tree)
                except Exception:
                    pass
                
            # 将本次探索到的数据合入全局树
            PageMapBuilder._deep_merge(merged_tree, page_tree)

            # 2. 深度清洗与去噪
            clean_tree = PageMapBuilder.sanitize_page_tree(merged_tree, base_rules=base_tree)

            # 3. 列表折叠与优化
            optimized_tree = PageMapBuilder.fold_duplicate_list_items(clean_tree)

            # 4. 自动创建版本快照 (防坏账备份)
            PageMapBuilder._create_topology_snapshot(artifacts_global_file)

            # 5. 实时持久化 global_page_tree.json (主存 artifacts/topology/，镜像 docs/)
            try:
                for target_json in [artifacts_global_file, docs_global_file]:
                    with open(target_json, "w", encoding="utf-8") as f:
                        json.dump(clean_tree, f, ensure_ascii=False, indent=2)
            except Exception as e:
                logger.warning(f"持久化 global_page_tree.json 失败: {e}")

            # 6. 渲染纯 Markdown 树与 Mermaid
            markdown_tree = PageMapBuilder.render_markdown_tree(optimized_tree)
            mermaid_str = PageMapBuilder.dict_to_mermaid_string(optimized_tree)

            lines = [
                "# 自动化产出：动态 UI 组件架构拓扑\n",
                "> 💡 **说明**：以 `docs/explore_rules.md` 为全局不变骨架，结合 **Post-Click Diff 双图差分** 与 **Component Awareness 组件感知** 动态延申业务页面内部的组件与弹窗拓扑。\n",
                "## 🌳 纯 Markdown 组件拓扑树\n",
                "```text",
                markdown_tree,
                "```\n",
                "## 🗺️ Mermaid 拓扑图 (辅助参考)\n",
                "```mermaid",
                mermaid_str,
                "```\n"
            ]
            content = "\n".join(lines)

            # 双写写入 artifacts/topology/ 与 docs/
            with open(artifacts_map_path, "w", encoding="utf-8") as f:
                f.write(content)
            with open(docs_map_path, "w", encoding="utf-8") as f:
                f.write(content)

            logger.info(f"🗺️ 已成功渲染动态 UI 架构树 (Markdown + Mermaid): {artifacts_map_path}")
        except Exception as e:
            logger.error(f"❌ 渲染架构图失败: {e}")

    @staticmethod
    def export_mermaid_map(page_tree: dict):
        """向后兼容接口，内部调用全功能 export_page_map"""
        PageMapBuilder.export_page_map(page_tree)
