import logging
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger("core.browser")

class ChartProbeMixin:
    """
    针对 Canvas / ECharts 折线图、柱状图等图表的全量节点批量嗅探器
    
    架构设计：
    1. 首选引擎 (ECharts DOM 探针): 0ms / 0 Token 直读 ECharts 内部数据模型与配置
    2. 兜底引擎 (Canvas 物理光标等分横扫): 兼容任意纯 Canvas / WebGL 渲染的大屏图表，
       模拟真实鼠标步进移动横扫，动态嗅探 Tooltip 悬浮卡片 DOM
    """

    def probe_chart_all_points(self, x: int, y: int, chart_name: str = "") -> Dict[str, Any]:
        """
        全量提取坐标 (x, y) 对应或附近的图表全部数据节点
        
        :param x: 图表区域内任意点击/悬停的 X 绝对像素坐标
        :param y: 图表区域内任意点击/悬停的 Y 绝对像素坐标
        :param chart_name: 图表业务名称 (例如 "近七天风量数据")
        :return: 包含全量点位数据列表、提取方式、包围盒等的字典
        """
        self.get_active_page()
        if not self.page or self.page.is_closed():
            return {"success": False, "reason": "Page not ready", "points": []}

        logger.info(f"📊 [ChartProbe] 开始对目标图表 '{chart_name}' ({x}, {y}) 启动全量节点批量嗅探...")

        # =========================================================================
        # 引擎 A: ECharts DOM 实例探针 (首选引擎，耗时 < 10ms，零 Token 损耗)
        # =========================================================================
        js_probe_echarts = """
        (pos) => {
            const { x, y } = pos;
            
            // 1. 寻找位于 (x, y) 下或附近的 canvas
            let el = document.elementFromPoint(x, y);
            let canvas = null;
            if (el) {
                if (el.tagName === 'CANVAS') {
                    canvas = el;
                } else {
                    canvas = el.querySelector('canvas') || el.closest('div')?.querySelector('canvas');
                }
            }
            
            // 若直接定位不到，在周边 350px 范围内寻找最近的有效 Canvas
            if (!canvas) {
                const allCanvases = Array.from(document.querySelectorAll('canvas'));
                let minDist = Infinity;
                for (const c of allCanvases) {
                    const r = c.getBoundingClientRect();
                    if (r.width > 60 && r.height > 60) {
                        const cx = r.left + r.width / 2;
                        const cy = r.top + r.height / 2;
                        const d = Math.hypot(cx - x, cy - y);
                        if (d < minDist && d < 350) {
                            minDist = d;
                            canvas = c;
                        }
                    }
                }
            }
            
            if (!canvas) {
                return { found_canvas: false };
            }
            
            const canvasRect = canvas.getBoundingClientRect();
            const rectInfo = {
                left: Math.round(canvasRect.left),
                top: Math.round(canvasRect.top),
                width: Math.round(canvasRect.width),
                height: Math.round(canvasRect.height)
            };
            
            // 2. 尝试从 canvas 或其各级父容器探测 ECharts 实例
            let instance = null;
            if (window.echarts && typeof window.echarts.getInstanceByDom === 'function') {
                instance = window.echarts.getInstanceByDom(canvas) || 
                           window.echarts.getInstanceByDom(canvas.parentElement) ||
                           (canvas.parentElement?.parentElement ? window.echarts.getInstanceByDom(canvas.parentElement.parentElement) : null);
            }
            
            // 深度遍历检查是否有 __echarts_instance__ 关联
            if (!instance) {
                let curr = canvas;
                for (let i = 0; i < 4 && curr; i++) {
                    if (curr.__echarts_instance__) {
                        instance = curr.__echarts_instance__;
                        break;
                    }
                    if (curr.getAttribute && curr.getAttribute('_echarts_instance_') && window.echarts) {
                        instance = window.echarts.getInstanceByDom(curr);
                        if (instance) break;
                    }
                    curr = curr.parentElement;
                }
            }
            
            if (instance && typeof instance.getOption === 'function') {
                try {
                    const opt = instance.getOption();
                    if (!opt) return { found_canvas: true, canvas_rect: rectInfo, has_instance: false };
                    
                    // 提取 X 轴类目 (如 日期列表)
                    let xData = [];
                    if (opt.xAxis) {
                        const xAxisObj = Array.isArray(opt.xAxis) ? opt.xAxis[0] : opt.xAxis;
                        if (xAxisObj && Array.isArray(xAxisObj.data)) {
                            xData = xAxisObj.data.map(item => {
                                if (typeof item === 'object' && item !== null) {
                                    return item.value || item.text || JSON.stringify(item);
                                }
                                return String(item);
                            });
                        }
                    }
                    
                    // 提取 Series 数值序列
                    const seriesList = opt.series || [];
                    const points = [];
                    
                    // 若有明确的 X 轴类目列表
                    if (xData.length > 0) {
                        for (let i = 0; i < xData.length; i++) {
                            const entry = { label: xData[i] };
                            for (let sIdx = 0; sIdx < seriesList.length; sIdx++) {
                                const s = seriesList[sIdx];
                                const sName = s.name || `指标_${sIdx + 1}`;
                                const rawVal = s.data ? s.data[i] : null;
                                let cleanVal = rawVal;
                                if (typeof rawVal === 'object' && rawVal !== null) {
                                    cleanVal = rawVal.value !== undefined ? rawVal.value : rawVal;
                                }
                                entry[sName] = cleanVal;
                            }
                            points.push(entry);
                        }
                    } else if (seriesList.length > 0) {
                        // 针对没有显式 xAxis.data (例如坐标轴类型为 time/value，数据直接在 series.data 中以 [x, y] 形式呈现)
                        for (let sIdx = 0; sIdx < seriesList.length; sIdx++) {
                            const s = seriesList[sIdx];
                            const sName = s.name || `指标_${sIdx + 1}`;
                            if (Array.isArray(s.data)) {
                                s.data.forEach((d, idx) => {
                                    let label = `第${idx + 1}点`;
                                    let val = d;
                                    if (Array.isArray(d)) {
                                        label = String(d[0]);
                                        val = d[1];
                                    } else if (typeof d === 'object' && d !== null) {
                                        label = String(d.name || d.label || `第${idx + 1}点`);
                                        val = d.value !== undefined ? d.value : d;
                                    }
                                    let existing = points.find(p => p.label === label);
                                    if (!existing) {
                                        existing = { label: label };
                                        points.push(existing);
                                    }
                                    existing[sName] = val;
                                });
                            }
                        }
                    }
                    
                    const titleText = opt.title ? (Array.isArray(opt.title) ? opt.title[0]?.text : opt.title?.text) : "";
                    
                    return {
                        found_canvas: true,
                        canvas_rect: rectInfo,
                        has_instance: true,
                        chart_title: titleText,
                        points: points,
                        series_count: seriesList.length
                    };
                } catch (e) {
                    return { found_canvas: true, canvas_rect: rectInfo, has_instance: false, error: String(e) };
                }
            }
            
            return {
                found_canvas: true,
                canvas_rect: rectInfo,
                has_instance: false
            };
        }
        """

        try:
            res_a = self.page.evaluate(js_probe_echarts, {"x": x, "y": y})
            if res_a.get("has_instance") and res_a.get("points"):
                points = res_a["points"]
                title = res_a.get("chart_title") or chart_name
                logger.info(f"⚡ [ChartProbe:引擎A] ECharts DOM 探针秒级命中！成功直读全量 {len(points)} 个数据节点！图表标题: '{title}'")
                return {
                    "success": True,
                    "method": "echarts_dom",
                    "chart_title": title,
                    "points": points,
                    "canvas_rect": res_a.get("canvas_rect")
                }
            
            canvas_rect = res_a.get("canvas_rect")
        except Exception as e_dom:
            logger.warning(f"⚠️ [ChartProbe:引擎A] ECharts DOM 直读异常 ({e_dom})，准备启用引擎 B 物理横扫...")
            canvas_rect = None

        # =========================================================================
        # 引擎 B: Canvas 物理光标等分横扫 (通用兜底引擎，支持任意纯 Canvas/WebGL)
        # =========================================================================
        logger.info(f"🔍 [ChartProbe:引擎B] 启动物理光标横扫探针 (Canvas Sweep)...")
        
        # 确定扫描包围盒
        if not canvas_rect or canvas_rect.get("width", 0) < 50:
            # 以传入的 (x, y) 为基准推算一个合理的图表交互窗口 (宽 320, 高 180)
            rect_left = max(0, x - 150)
            rect_top = max(0, y - 80)
            rect_width = 300
            rect_height = 160
        else:
            rect_left = canvas_rect["left"]
            rect_top = canvas_rect["top"]
            rect_width = canvas_rect["width"]
            rect_height = canvas_rect["height"]

        # 横扫采样点数 (折线图通常 7~10 个周期点)
        sweep_steps = 9
        # 避开左侧 Y 轴刻度标签和右侧边缘空白，有效宽度取 12% ~ 88%
        x_start = rect_left + int(rect_width * 0.12)
        x_end = rect_left + int(rect_width * 0.88)
        y_sweep = rect_top + int(rect_height * 0.50)
        
        step_delta = (x_end - x_start) / max(1, sweep_steps - 1)
        
        js_read_active_tooltip = """
        () => {
            // 扫描 DOM 中活跃展示且包含文本的浮动 Tooltip
            const selectors = [
                '.echarts-tooltip',
                'div[style*="z-index"][style*="pointer-events: none"]',
                'div[style*="position: absolute"][style*="z-index"]',
                '.el-tooltip__popper',
                '.ant-tooltip'
            ];
            
            for (const sel of selectors) {
                const nodes = document.querySelectorAll(sel);
                for (const node of nodes) {
                    const style = window.getComputedStyle(node);
                    if (style.display !== 'none' && style.visibility !== 'hidden' && parseFloat(style.opacity || '1') > 0.1) {
                        const txt = (node.innerText || '').trim();
                        if (txt && txt.length >= 2 && txt.length < 300) {
                            return txt;
                        }
                    }
                }
            }
            return null;
        }
        """

        collected_points = []
        seen_texts = set()

        for step_idx in range(sweep_steps):
            sweep_x = int(x_start + step_idx * step_delta)
            
            # 使用 steps=5 真实移动鼠标触发 Canvas 内部的 mousemove 命中计算
            try:
                self.page.mouse.move(sweep_x, y_sweep, steps=5)
                time.sleep(0.12)  # 等待大屏前端渲染 Tooltip
                
                tooltip_text = self.page.evaluate(js_read_active_tooltip)
                if tooltip_text and tooltip_text not in seen_texts:
                    seen_texts.add(tooltip_text)
                    
                    # 格式化 Tooltip 文本行
                    lines = [line.strip() for line in tooltip_text.split('\n') if line.strip()]
                    point_entry = {"raw": tooltip_text}
                    if lines:
                        point_entry["label"] = lines[0]
                        # 尝试提取指标键值对 (如 "风量 : 50.2 m³/s")
                        for sub_line in lines[1:]:
                            if ":" in sub_line or "：" in sub_line:
                                sep = ":" if ":" in sub_line else "："
                                parts = sub_line.split(sep, 1)
                                point_entry[parts[0].strip()] = parts[1].strip()
                            else:
                                point_entry[f"detail_{len(point_entry)}"] = sub_line
                    
                    collected_points.append(point_entry)
                    logger.debug(f"🎯 [ChartProbe:引擎B] 捕获第 {len(collected_points)} 个 Tooltip 节点: {point_entry.get('label')}")
            except Exception as e_sweep:
                logger.warning(f"⚠️ [ChartProbe:引擎B] 光标扫描步进异常 ({e_sweep})")

        if collected_points:
            logger.info(f"✨ [ChartProbe:引擎B] 光标物理横扫完成！成功汇聚 {len(collected_points)} 个数据节点！")
            return {
                "success": True,
                "method": "canvas_sweep",
                "chart_title": chart_name,
                "points": collected_points,
                "canvas_rect": canvas_rect
            }

        logger.warning(f"⚠️ [ChartProbe] 未能从目标图表嗅探到有效数据节点。")
        return {
            "success": False,
            "method": "none",
            "chart_title": chart_name,
            "points": [],
            "canvas_rect": canvas_rect,
            "reason": "未能通过 DOM 实例或光标横扫捕获到 Tooltip 数据"
        }
