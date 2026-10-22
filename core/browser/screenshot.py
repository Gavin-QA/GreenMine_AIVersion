import base64
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Generator, Optional, Tuple
from playwright.sync_api import BrowserContext, Page

logger = logging.getLogger("core.browser")

class ScreenshotMixin:
    def capture_screenshot(self, save_path: Optional[str] = None, crop_box: Optional[Dict[str, int]] = None, dim_background: bool = False) -> bytes:
        """
        截取当前窗口页面全屏截图或局部截图
        
        :param save_path: 可选，保存截图的文件路径（自动创建目录）
        :param crop_box: 可选，局部截图的像素边界范围，字典格式：{"x": int, "y": int, "width": int, "height": int}
        :param dim_background: 可选，是否执行 Visual Dimming，将弹窗背后的蒙版涂黑
        :return: 截图的二进制 PNG 字节流
        """
        self.get_active_page()
        if not self.page or self.page.is_closed():
            raise RuntimeError("页面尚未初始化或已关闭，无法截图！")

        if dim_background:
            dim_script = """
            () => {
                const masks = Array.from(document.querySelectorAll('*')).filter(el => {
                    const style = window.getComputedStyle(el);
                    const rect = el.getBoundingClientRect();
                    const coversScreen = rect.width >= window.innerWidth * 0.9 && rect.height >= window.innerHeight * 0.9;
                    const isFixedOrAbs = style.position === 'fixed' || style.position === 'absolute';
                    const hasZIndex = parseInt(style.zIndex || 0) > 0;
                    const hasAlphaBg = style.backgroundColor.includes('rgba') && !style.backgroundColor.includes('rgba(0, 0, 0, 0)');
                    const hasOpacity = parseFloat(style.opacity) < 1.0;
                    const isNotRoot = el.tagName.toLowerCase() !== 'body' && el.tagName.toLowerCase() !== 'html';
                    return coversScreen && isFixedOrAbs && hasZIndex && isNotRoot && (hasAlphaBg || hasOpacity);
                });
                window.__vision_masks = [];
                masks.forEach(m => {
                    window.__vision_masks.push({
                        el: m,
                        oldBg: m.style.backgroundColor,
                        oldOpacity: m.style.opacity
                    });
                    m.style.backgroundColor = 'rgba(0, 0, 0, 0.95)';
                    m.style.opacity = '1';
                });
                return masks.length;
            }
            """
            try:
                masked_count = self.page.evaluate(dim_script)
                if masked_count > 0:
                    logger.info(f"🌑 已启用视觉熄灯 (Visual Dimming)，屏蔽了 {masked_count} 个背景蒙版，强制 AI 聚焦当前弹窗！")
                    self.page.wait_for_timeout(50)
            except Exception as e:
                logger.warning(f"视觉熄灯处理失败: {e}")

        # Electron 桌面应用通常为固定大屏尺寸，抓取当前 viewport
        # 【极致优化】从 type="png" 改为 type="jpeg", quality=60，使体积从 6MB 暴降至 300KB
        if crop_box:
            png_bytes = self.page.screenshot(type="jpeg", quality=60, full_page=False, clip=crop_box)
        else:
            png_bytes = self.page.screenshot(type="jpeg", quality=60, full_page=False)

        if dim_background:
            restore_script = """
            () => {
                if (window.__vision_masks) {
                    window.__vision_masks.forEach(item => {
                        if (item.el) {
                            item.el.style.backgroundColor = item.oldBg;
                            item.el.style.opacity = item.oldOpacity;
                        }
                    });
                    delete window.__vision_masks;
                }
            }
            """
            try:
                self.page.evaluate(restore_script)
            except:
                pass

        if save_path:
            out_file = Path(save_path)
            out_file.parent.mkdir(parents=True, exist_ok=True)
            with open(out_file, "wb") as f:
                f.write(png_bytes)
            logger.info(f"截图已保存至: {out_file.resolve()}")

        return png_bytes

    @staticmethod
    def draw_cursor_on_image(image_path: str, x: int, y: int, dpr: float = 1.0):
        """
        在已有的截图文件上绘制红色准星，用于直观展示 AI 的点击/悬停目标位置。
        """
        try:
            from PIL import Image, ImageDraw
            
            out_file = Path(image_path)
            if not out_file.exists():
                return
                
            image = Image.open(out_file)
            draw = ImageDraw.Draw(image, "RGBA")
            
            px = int(x * dpr)
            py = int(y * dpr)
            
            r1 = int(6 * dpr)
            r2 = int(20 * dpr)
            draw.ellipse((px - r1, py - r1, px + r1, py + r1), fill=(255, 0, 85, 255))
            draw.ellipse((px - r2, py - r2, px + r2, py + r2), outline=(0, 255, 204, 200), width=int(2*dpr))
            
            image.save(out_file, format="PNG")
            logger.info(f"🖌️ 已将目标准星 ({x}, {y}) 绘制到当前截图: {out_file.name}")
        except Exception as e:
            logger.warning(f"在截图上绘制模拟光标失败: {e}")

    def capture_screenshot_base64(self, save_path: Optional[str] = None, crop_box: Optional[Dict[str, int]] = None, dim_background: bool = False) -> str:
        """
        截取屏幕并直接返回 Base64 编码字符串，便于多模态大模型 (Qwen-VL / GPT-4o) 组装 API 请求
        由于高 DPI 下全屏 PNG 极大（可能超过 10MB），容易导致 API 返回 400 Bad Request Payload Too Large，
        因此在发送给大模型前，将其在内存中压缩为 1080P 级别的 JPEG，保留给人类的硬盘归档依然是原画质 PNG。
        """
        png_bytes = self.capture_screenshot(save_path=save_path, crop_box=crop_box, dim_background=dim_background)
        
        try:
            from PIL import Image
            import io
            
            image = Image.open(io.BytesIO(png_bytes))
            
            # 根据官方参数限制：长边单边最大长度不超过 2048 像素，文件大小 ≤ 5MB
            # thumbnail() 方法会保持原图长宽比，限制这里设为 (2048, 2048) 确保最长边不超过 2048
            image.thumbnail((2048, 2048), Image.Resampling.LANCZOS)
            
            # 必须转为 RGB 才能保存为 JPEG
            if image.mode in ("RGBA", "P"):
                image = image.convert("RGB")
                
            buffer = io.BytesIO()
            # 提升画质到 90，确保即使是细小的菜单栏也能被 AI 精准计算出坐标
            image.save(buffer, format="JPEG", quality=90)
            compressed_bytes = buffer.getvalue()
            
            return base64.b64encode(compressed_bytes).decode("utf-8")
            
        except ImportError:
            logger.warning("未安装 Pillow，无法在内存中压缩截图，可能会导致大模型 API 报 400 错误！")
            return base64.b64encode(png_bytes).decode("utf-8")
        except Exception as e:
            logger.error(f"截图压缩失败，降级回传原始截图: {e}")
            return base64.b64encode(png_bytes).decode("utf-8")

    @staticmethod
    def crop_roi_base64(
        image_path: str,
        center_x: int,
        center_y: int,
        dpr: float = 1.0,
        roi_width: int = 920,
        roi_height: int = 460,
        save_path: Optional[str] = None
    ) -> Optional[str]:
        """
        从已有全屏截图中截取目标元素局部 ROI (如 Tooltip、卡片浮层) 并返回 Base64 编码。
        专为 API 双向核验设计，提供充分视野避免截偏，并防止大模型受远端异物干扰。
        """
        try:
            from PIL import Image
            import io

            img_file = Path(image_path)
            if not img_file.exists():
                return None

            im = Image.open(img_file)
            w, h = im.size

            px = int(center_x * dpr)
            py = int(center_y * dpr)

            crop_w = int(roi_width * dpr)
            crop_h = int(roi_height * dpr)

            # 智能偏置：若目标在右半屏，卡片文字通常向右延展；若在左半屏向右延展；居中则居中
            if px > w * 0.55:
                x1 = max(0, min(w - crop_w, px - int(80 * dpr)))
            elif px < w * 0.45:
                x1 = max(0, min(w - crop_w, px - int(60 * dpr)))
            else:
                x1 = max(0, min(w - crop_w, px - crop_w // 2))

            y1 = max(0, min(h - crop_h, py - crop_h // 3))
            x2 = min(w, x1 + crop_w)
            y2 = min(h, y1 + crop_h)

            cropped = im.crop((x1, y1, x2, y2))

            if save_path:
                try:
                    out_p = Path(save_path)
                    out_p.parent.mkdir(parents=True, exist_ok=True)
                    cropped.save(out_p)
                except Exception:
                    pass

            if cropped.mode in ("RGBA", "P"):
                cropped = cropped.convert("RGB")

            buffer = io.BytesIO()
            cropped.save(buffer, format="JPEG", quality=92)
            return base64.b64encode(buffer.getvalue()).decode("utf-8")
        except Exception as e:
            logger.warning(f"ROI 局部裁剪失败，回退使用全屏原图: {e}")
            return None


