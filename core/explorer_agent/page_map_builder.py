import logging
from pathlib import Path

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
                    if "|" in line and "一级菜单" not in line and "---" not in line:
                        parts = [p.strip() for p in line.split("|")]
                        if len(parts) >= 4:
                            # 提取 1、2 级菜单（去掉加粗的 **）
                            lvl1 = parts[2].replace("**", "").strip()
                            lvl2 = parts[3].replace("**", "").strip()
                            if lvl1:
                                if lvl1 not in base_tree:
                                    base_tree[lvl1] = {}
                                if lvl2:
                                    if lvl2 not in base_tree[lvl1]:
                                        base_tree[lvl1][lvl2] = {}
                logger.info("🌳 成功加载基准架构底座！")
        except Exception as e:
            logger.warning(f"加载基准架构底座失败: {e}")
        return base_tree

    @staticmethod
    def export_mermaid_map(page_tree: dict):
        """将架构树渲染为 Mermaid 格式并保存为 Markdown"""
        try:
            docs_dir = Path("docs").resolve()
            docs_dir.mkdir(parents=True, exist_ok=True)
            map_path = docs_dir / "auto_page_map.md"
            
            lines = ["# 自动化产出：动态 UI 页面架构拓扑\n"]
            lines.append("这是由 ExplorerAgent 在自主探索过程中，基于视觉推断自动动态构建与补全的页面层级与功能架构图。\n")
            lines.append("```mermaid")
            lines.append("graph TD")
            
            node_id_counter = [0]
            node_id_map = {}
            
            def get_node_id(name):
                if name not in node_id_map:
                    node_id_map[name] = f"N{node_id_counter[0]}"
                    node_id_counter[0] += 1
                return node_id_map[name]
                
            def traverse(tree, parent_name=None):
                for child_name, child_tree in tree.items():
                    # 清理可能破坏 mermaid 语法的字符
                    clean_child = child_name.replace('"', '').replace('[', '').replace(']', '').replace('(', '').replace(')', '')
                    c_id = get_node_id(clean_child)
                    
                    if parent_name:
                        clean_parent = parent_name.replace('"', '').replace('[', '').replace(']', '').replace('(', '').replace(')', '')
                        p_id = get_node_id(clean_parent)
                        lines.append(f'    {p_id}["{clean_parent}"] --> {c_id}["{clean_child}"]')
                    
                    traverse(child_tree, clean_child)
                    
            traverse(page_tree)
            lines.append("```\n")
            
            with open(map_path, "w", encoding="utf-8") as f:
                f.write("\n".join(lines))
                
            logger.info(f"🗺️ 已成功渲染动态 UI 页面架构图 (Mermaid): {map_path}")
        except Exception as e:
            logger.error(f"❌ 渲染架构图失败: {e}")
