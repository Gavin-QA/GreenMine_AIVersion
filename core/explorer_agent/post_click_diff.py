import logging
from pathlib import Path
from typing import Dict, Any, Optional, List
from PIL import Image, ImageChops, ImageStat

logger = logging.getLogger("explorer_agent.post_click_diff")

class PostClickDetector:
    """
    点击前后双图与 DOM 状态差分检测器 (Post-Click Diff)
    用于自动推断点击动作带来的 UI 状态跃迁：
    - modal_open: 触发了新的模态弹窗/抽屉
    - modal_close: 关闭了当前模态弹窗
    - page_navigate: 页面发生了全量路由跳转
    - in_place: 原地局部刷新或状态变动
    """

    @staticmethod
    def get_current_modals(driver) -> List[Dict[str, Any]]:
        """获取当前 DOM 中所有可见的模态弹窗"""
        try:
            return driver.detect_visible_modals()
        except Exception as e:
            logger.debug(f"获取当前模态失败: {e}")
            return []

    @staticmethod
    def detect_transition(
        driver,
        before_img_path: str,
        after_img_path: str,
        before_modals: Optional[List[Dict[str, Any]]] = None,
        action_desc: str = ""
    ) -> Dict[str, Any]:
        """
        综合分析点击前后的 DOM 与视觉变化，返回状态跃迁类型。
        """
        # 1. 优先使用 DOM 级零成本精确检测
        try:
            after_modals = driver.detect_visible_modals()
            before_cnt = len(before_modals) if before_modals else 0
            after_cnt = len(after_modals) if after_modals else 0

            # 场景 A: 新打开了弹窗
            if before_cnt == 0 and after_cnt > 0:
                modal_title = after_modals[0].get("title", "").strip() or "新建弹窗"
                clean_name = modal_title if "弹窗" in modal_title or "抽屉" in modal_title else f"“{modal_title}”弹窗"
                logger.info(f"✨ [Post-Click Diff] DOM 探测到新增模态层: {clean_name}")
                return {
                    "transition": "modal_open",
                    "container_name": clean_name,
                    "container_type": "modal",
                    "source": "dom"
                }

            # 场景 B: 弹窗被关闭
            if before_cnt > 0 and after_cnt == 0:
                closed_title = before_modals[0].get("title", "").strip() or "弹窗"
                clean_name = closed_title if "弹窗" in closed_title or "抽屉" in closed_title else f"“{closed_title}”弹窗"
                logger.info(f"🔙 [Post-Click Diff] DOM 探测到模态层已关闭: {clean_name}")
                return {
                    "transition": "modal_close",
                    "container_name": clean_name,
                    "container_type": "modal",
                    "source": "dom"
                }

            # 场景 C: 连续弹窗或嵌套弹窗切换
            if before_cnt > 0 and after_cnt > 0:
                before_title = before_modals[0].get("title", "")
                after_title = after_modals[0].get("title", "")
                if before_title != after_title and after_title:
                    clean_name = after_title if "弹窗" in after_title else f"“{after_title}”弹窗"
                    logger.info(f"🔀 [Post-Click Diff] DOM 探测到弹窗内容切换: {clean_name}")
                    return {
                        "transition": "modal_switch",
                        "container_name": clean_name,
                        "container_type": "modal",
                        "source": "dom"
                    }
        except Exception as e:
            logger.warning(f"DOM 模态差分检测异常: {e}")

        # 2. 纯视觉 PIL 图像差分 (Fallback / 补充检测)
        try:
            if not Path(before_img_path).exists() or not Path(after_img_path).exists():
                return {"transition": "in_place", "container_name": None, "source": "none"}

            img_before = Image.open(before_img_path).convert("RGB")
            img_after = Image.open(after_img_path).convert("RGB")

            # 尺寸确保一致
            if img_before.size != img_after.size:
                return {"transition": "page_navigate", "container_name": None, "source": "size_diff"}

            diff = ImageChops.difference(img_before, img_after)
            bbox = diff.getbbox()
            if not bbox:
                # 完全无像素变化
                return {"transition": "in_place", "container_name": None, "source": "pixel_zero"}

            # 统计变化像素比例（忽略微小抗锯齿色差）
            gray_diff = diff.convert("L")
            hist = gray_diff.histogram()
            # 阈值大于 25 判定为真正有效变化的像素
            changed_pixels = sum(hist[25:])
            total_pixels = img_before.width * img_before.height
            change_ratio = changed_pixels / total_pixels

            # 亮度对比（检测遮罩 Dimming）
            stat_before = ImageStat.Stat(img_before)
            stat_after = ImageStat.Stat(img_after)
            brightness_before = sum(stat_before.mean) / 3.0
            brightness_after = sum(stat_after.mean) / 3.0
            brightness_drop = brightness_before - brightness_after

            # 场景 D: 大面积整屏刷新 (页面路由切换)
            if change_ratio > 0.60:
                logger.info(f"🌐 [Post-Click Diff] 视觉检测到大面积整屏刷新 ({change_ratio:.1%}) -> 判定为页面跳转")
                return {
                    "transition": "page_navigate",
                    "container_name": None,
                    "change_ratio": change_ratio,
                    "source": "vision_navigate"
                }

            # 场景 E: 遮罩压暗出现 (视觉判定模态框打开)
            # 背景变暗幅度超过 14 且产生局部对比，同时排除正常的 Tab 切换与 3D 光影变化
            nav_tab_keywords = ["标签", "tab", "菜单", "导航", "视角", "切换", "总览"]
            is_tab_or_nav = any(k in action_desc.lower() for k in nav_tab_keywords) if action_desc else False
            
            if not is_tab_or_nav and brightness_drop > 15.0 and 0.05 <= change_ratio <= 0.60:
                suggested_name = f"“{action_desc}”弹窗" if action_desc else "业务弹窗"
                logger.info(f"🪟 [Post-Click Diff] 视觉检测到背景遮罩变暗 ({brightness_drop:.1f}) -> 判定为浮层打开: {suggested_name}")
                return {
                    "transition": "modal_open",
                    "container_name": suggested_name,
                    "container_type": "modal",
                    "source": "vision_dimming"
                }

            # 场景 F: 原地局部刷新
            return {
                "transition": "in_place",
                "container_name": None,
                "change_ratio": change_ratio,
                "source": "vision_in_place"
            }

        except Exception as e:
            logger.warning(f"PIL 视觉差分检测异常: {e}")
            return {"transition": "in_place", "container_name": None, "source": "fallback"}
