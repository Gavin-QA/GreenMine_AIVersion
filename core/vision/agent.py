import json
import logging
import re
import time
from typing import Any, Dict, List, Optional, Tuple

import requests
from requests.exceptions import Timeout, RequestException

from config.settings import settings

from .prompts import (
    PLANNER_SYSTEM_PROMPT,
    WORKER_SYSTEM_PROMPT,
    ACTION_SYSTEM_PROMPT,
    DOM_MATCH_SYSTEM_PROMPT,
    ASSERT_SYSTEM_PROMPT,
    API_ASSERT_SYSTEM_PROMPT,
    BATCH_CHART_ASSERT_SYSTEM_PROMPT,
    SELF_HEAL_SYSTEM_PROMPT
)

logger = logging.getLogger("core.vision_agent")

class VisionAgentException(Exception):
    pass


class VisionAgent:
    """
    视觉多模态大模型对接大脑
    职责：
    1. 组装符合 OpenAI Vision API 规范的请求体（含 Base64 截图）。
    2. 定义严格的 System Prompt，要求输出标准化 JSON（包含思维链与百分比坐标）。
    3. 解析大模型响应，将百分比坐标转换为当前物理视口的绝对像素坐标 (x, y)。
    """


    def __init__(self):
        self.api_key = settings.llm_api_key
        self.base_url = settings.llm_base_url.rstrip("/")
        self.model = settings.llm_model
        self.provider = settings.llm_provider
        self.temperature = float(getattr(settings, "llm_temperature", 0.1))
        self.timeout = float(getattr(settings, "llm_timeout", 60.0))
        self.max_tokens = int(getattr(settings, "llm_max_tokens", 1024))
        self.max_retries = int(getattr(settings, "llm_max_retries", 3))
        self.session = requests.Session()

        if not self.api_key:
            logger.warning("未配置 LLM_API_KEY！请在 .env 文件中设置。")

    def _clean_json_response(self, text: str) -> str:
        """清理大模型可能返回的 Markdown 标记，确保是纯 JSON"""
        text = text.strip()
        if text.startswith("```"):
            # 移除最外层的 ```json 和 ```
            text = re.sub(r"^```(?:json)?\n?(.*?)\n?```$", r"\1", text, flags=re.DOTALL)
        return text.strip()

    def _call_llm(self, system_prompt: str, user_prompt: str, base64_image: Optional[str] = None, base64_images: Optional[List[str]] = None) -> Dict[str, Any]:
        """发起对大模型的 HTTP 请求"""
        if not self.api_key:
            raise VisionAgentException("LLM_API_KEY is not configured.")

        # 组装 OpenAI 兼容的消息格式
        messages = [
            {"role": "system", "content": system_prompt}
        ]

        user_content: List[Dict[str, Any]] = [{"type": "text", "text": user_prompt}]
        
        images_to_send = []
        if base64_image:
            images_to_send.append(base64_image)
        if base64_images:
            images_to_send.extend(base64_images)
            
        for img_b64 in images_to_send:
            # 根据截图格式构建 image_url
            prefix = "data:image/png;base64,"
            if not img_b64.startswith("data:image"):
                img_b64 = prefix + img_b64
                
            user_content.append({
                "type": "image_url",
                "image_url": {
                    "url": img_b64
                }
            })

        messages.append({"role": "user", "content": user_content})

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "Connection": "close"
        }
        
        # 针对 Gemini / AI Studio 的 API 兼容路径调整（如果 base_url 没以 chat/completions 结尾）
        endpoint = self.base_url
        if "generativelanguage.googleapis.com" in endpoint and not endpoint.endswith("chat/completions"):
            endpoint = f"{endpoint}/chat/completions"
        elif not endpoint.endswith("chat/completions"):
            # 标准 OpenAI 路径
            endpoint = f"{endpoint}/v1/chat/completions" if not endpoint.endswith("/v1") else f"{endpoint}/chat/completions"

        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "response_format": {"type": "json_object"} if self.provider == "openai" else None
        }

        max_retries = self.max_retries
        last_exception = None

        for attempt in range(1, max_retries + 1):
            try:
                if attempt == 1:
                    logger.info(f"🧠 [VisionAgent] 请求大模型: {self.model} ...")
                else:
                    logger.info(f"🧠 [VisionAgent] 请求大模型重试 ({attempt}/{max_retries}): {self.model} ...")

                resp = self.session.post(endpoint, json=payload, headers=headers, timeout=self.timeout)
                resp.raise_for_status()
                
                data = resp.json()
                content = data["choices"][0]["message"]["content"]
                
                # 解析并清理返回的 JSON
                clean_content = self._clean_json_response(content)
                logger.debug(f"[VisionAgent] 原始响应:\n{clean_content}")
                return json.loads(clean_content)

            except requests.exceptions.RequestException as e:
                last_exception = e
                # Check for 400/401/403 which are usually not retryable
                if isinstance(e, requests.exceptions.HTTPError) and e.response is not None:
                    status = e.response.status_code
                    if status in (400, 401, 403):
                        logger.error(f"🧠 大模型请求遇到致命错误 ({status}): {e}")
                        raise VisionAgentException(f"LLM API Fatal Error: {e}")
                
                logger.warning(f"⚠️ [VisionAgent] 大模型通信异常 ({type(e).__name__}): {e}")
                
                # 重置 session 防连接池污染
                self.session.close()
                self.session = requests.Session()
                
                # 若遇到本地代理异常，自动降级切换为直连模式重试
                if self.session.trust_env and isinstance(e, requests.exceptions.ProxyError):
                    logger.info("🔄 [VisionAgent] 检测到系统代理可能中断，自动降级为直连模式 (trust_env=False) 重试...")
                    self.session.trust_env = False
                    
                if attempt < max_retries:
                    time.sleep(1.5 * attempt)
            except Exception as e:
                logger.error(f"🧠 大模型请求过程发生未知异常: {e}")
                raise VisionAgentException(f"LLM API Unexpected Error: {e}")

        logger.error(f"🧠 大模型请求重试 {max_retries} 次后仍失败: {last_exception}")
        raise VisionAgentException(f"LLM API Unexpected Error: {last_exception}")

    def check_api_assertion(self, instruction: str, base64_image: str, api_data_json: str) -> Tuple[bool, str]:
        """
        基于视觉截图和截获的接口 JSON 数据，进行双向比对断言
        返回 (passed, reason)
        """
        logger.info(f"⚖️ 执行 API 双重断言指令: '{instruction}'")
        
        user_prompt = f"当前页面截图如附图所示。断言指令：{instruction}\n\n【最新拦截到的 API JSON 响应数据】：\n{api_data_json}\n\n请比对截图与 JSON 数据是否一致。"
        
        try:
            result = self._call_llm(
                system_prompt=API_ASSERT_SYSTEM_PROMPT,
                user_prompt=user_prompt,
                base64_image=base64_image
            )
            
            thought = result.get("thought", "")
            match_status = str(result.get("match_status", "")).upper().strip()
            passed = result.get("passed", False)
            reason = result.get("assert_reason", "未提供理由")
            
            logger.info(f"💡 AI 思考链: {thought}")

            # 通用三态拆分：如果候选接口与当前组件非同源业务，属于跳过非Bug，严禁误报
            if match_status == "UNRELATED" or "非同源" in reason or "跳过数据校验" in reason:
                passed = True
                logger.info(f"ℹ️ API 状态: UNRELATED (接口非当前组件数据源，跳过比对，非Bug) | 理由: {reason}")
            elif passed or match_status == "MATCHED":
                passed = True
                logger.info(f"✅ API 断言结果: True (MATCHED 同源且数据一致) | 理由: {reason}")
            else:
                passed = False
                logger.info(f"❌ API 断言结果: False (MISMATCH 同源真实数据冲突) | 理由: {reason}")
                
            return passed, reason
            
        except Exception as e:
            logger.error(f"🧠 大模型执行 API 双重断言发生异常: {e}")
            raise VisionAgentException(f"LLM API Unexpected Error: {e}")

    def check_batch_chart_assertion(self, chart_name: str, points: list, base64_image: str, api_data_json: str) -> Tuple[bool, str]:
        """
        基于图表嗅探到的全量时序/类目数据点与截获的接口 JSON，进行集中批量双向断言
        返回 (passed, reason)
        """
        logger.info(f"📊 [BatchChartAssert] 正在对图表 '{chart_name}' (共 {len(points)} 个数据点) 发起集中接口断言...")
        
        points_summary = json.dumps(points, ensure_ascii=False, indent=2)
        user_prompt = (
            f"【目标图表名称】: {chart_name}\n\n"
            f"【探针捕获到的全量图表数据点 (共 {len(points)} 项)】:\n{points_summary}\n\n"
            f"【最新倒排检索到的 API 接口响应报文】:\n{api_data_json}\n\n"
            f"请核验上述图表数据是否全部在后台接口中正确存在，数值是否一致，是否存在断流全0或业务异常。"
        )
        
        try:
            result = self._call_llm(
                system_prompt=BATCH_CHART_ASSERT_SYSTEM_PROMPT,
                user_prompt=user_prompt,
                base64_image=base64_image
            )
            
            thought = result.get("thought", "")
            match_status = result.get("match_status", "MATCHED")
            passed = result.get("passed", False)
            if match_status in ("UNRELATED", "SKIPPED"):
                passed = True
            reason = result.get("assert_reason", "未提供理由")
            
            logger.info(f"💡 [BatchChartAssert] AI 思考链: {thought} | 状态: {match_status}")
            if passed:
                logger.info(f"✅ [BatchChartAssert] 图表批量断言结果: True ({match_status}) | 理由: {reason}")
            else:
                logger.warning(f"❌ [BatchChartAssert] 图表批量断言结果: False ({match_status}) | 理由: {reason}")
                
            return passed, reason
            
        except Exception as e:
            logger.error(f"🧠 大模型执行图表批量断言发生异常: {e}")
            raise VisionAgentException(f"LLM API Unexpected Error: {e}")

    def find_element(self, instruction: str, base64_image: str, viewport_width: int, viewport_height: int, dom_elements: Optional[List[Dict[str, Any]]] = None) -> Tuple[int, int]:
        """
        基于自然语言指令寻找目标元素的绝对坐标
        返回 (x, y) 物理像素坐标。如果找不到则抛出异常。
        如果提供了 dom_elements，则优先走精确的 Midscene 风格选择题模式；如果 DOM 模式找不到目标，则自动降级为纯视觉坐标模式。
        """
        logger.info(f"🕵️‍♂️ 寻找元素指令: '{instruction}'")
        
        if dom_elements and len(dom_elements) > 0:
            logger.info("⚡ 启用 Hybrid DOM 匹配模式")
            # 将元素列表精简以节约 Token，同时附带空间位置 pos: [x, y] 协助大模型区分同名元素（如顶部下拉菜单项 vs 内容区卡片）
            simplified_elements = []
            for el in dom_elements:
                item = {
                    "id": el["id"],
                    "tag": el["tag"],
                    "text": el["text"],
                    "pos": [int(el["rect"]["x"]), int(el["rect"]["y"])]
                }
                if el.get("container_name"):
                    item["container"] = el["container_name"]
                simplified_elements.append(item)
            elements_json = json.dumps(simplified_elements, ensure_ascii=False, indent=2)
            
            user_prompt = f"当前页面截图如附图所示。指令：{instruction}\n\n候选元素列表：\n{elements_json}"
            
            result = self._call_llm(
                system_prompt=DOM_MATCH_SYSTEM_PROMPT,
                user_prompt=user_prompt,
                base64_image=base64_image
            )
            
            thought = result.get("thought", "")
            logger.info(f"💡 AI 思考链: {thought}")
            
            if result.get("found", False):
                target_id = result.get("target_id")
                if target_id is not None:
                    # 找到对应的元素
                    target_el = next((el for el in dom_elements if el["id"] == target_id), None)
                    if target_el:
                        rect = target_el["rect"]
                        x = int(rect["x"] + rect["width"] / 2)
                        y = int(rect["y"] + rect["height"] / 2)
                        logger.info(f"🎯 精确命中 DOM 元素 ID: {target_id} [{target_el['tag']}] '{target_el['text']}', 计算中心物理坐标({x}, {y})")
                        return x, y
                    else:
                        logger.warning(f"⚠️ AI 返回了无效的 target_id: {target_id}，准备降级到纯视觉模式...")
                else:
                    logger.warning("⚠️ 大模型返回的数据中缺少 target_id 字段，准备降级到纯视觉模式...")
            else:
                logger.warning(f"⚠️ Hybrid DOM 未找到目标 (AI 解释: {thought})，准备降级到纯视觉模式...")
                
        # Fallback: 纯视觉预测模式
        logger.info("👀 启用纯视觉坐标预测模式 (Fallback)")
        result = self._call_llm(
            system_prompt=ACTION_SYSTEM_PROMPT,
            user_prompt=f"当前页面截图如附图所示。指令：{instruction}",
            base64_image=base64_image
        )
        
        thought = result.get("thought", "")
        logger.info(f"💡 AI 思考链 (纯视觉): {thought}")
        
        if not result.get("found", False):
            raise VisionAgentException(f"元素完全未找到，AI 纯视觉判定解释: {thought}")
            
        x_pct = result.get("x_percent")
        y_pct = result.get("y_percent")
        
        if x_pct is None or y_pct is None:
            raise VisionAgentException("大模型纯视觉预测返回的数据中缺少坐标字段。")
            
        # 归一化百分比坐标 -> 绝对物理像素
        # 坐标需被约束在合法的屏幕范围内
        x = int(max(0, min(1, float(x_pct))) * viewport_width)
        y = int(max(0, min(1, float(y_pct))) * viewport_height)
        
        logger.info(f"🎯 换算坐标: 屏幕比例({x_pct:.2f}, {y_pct:.2f}) -> 物理坐标({x}, {y})")
        return x, y

    def check_assertion(self, instruction: str, base64_image: str) -> Tuple[bool, str]:
        """
        基于视觉进行页面断言
        返回 (是否通过, 详细原因说明)
        """
        logger.info(f"⚖️ 执行断言指令: '{instruction}'")
        
        result = self._call_llm(
            system_prompt=ASSERT_SYSTEM_PROMPT,
            user_prompt=f"请对附带的截图执行以下断言：{instruction}",
            base64_image=base64_image
        )
        
        thought = result.get("thought", "")
        logger.info(f"💡 AI 思考链: {thought}")
        
        passed = result.get("passed", False)
        reason = result.get("assert_reason", "")
        
        status_icon = "✅" if passed else "❌"
        logger.info(f"{status_icon} 断言结果: {passed} | 理由: {reason}")
        
        return passed, reason

    def compare_images_for_freeze(self, instruction: str, base64_image_a: str, base64_image_b: str) -> Tuple[bool, str]:
        """
        防假死检测特供：发送前后两张时序截图给大模型，判断是否有动态变化。
        返回 (是否通过防假死检测, 详细理由)
        """
        logger.info(f"⚖️ 执行双图防假死断言指令: '{instruction}'")
        
        result = self._call_llm(
            system_prompt=ASSERT_SYSTEM_PROMPT,
            user_prompt=f"请对附带的两张时序截图执行以下断言：{instruction}",
            base64_images=[base64_image_a, base64_image_b]
        )
        
        thought = result.get("thought", "")
        logger.info(f"💡 AI 思考链: {thought}")
        
        passed = result.get("passed", False)
        reason = result.get("assert_reason", "")
        
        status_icon = "✅" if passed else "❌"
        logger.info(f"{status_icon} 防假死比对结果: {passed} | 理由: {reason}")
        
        return passed, reason

    def plan_sub_objective(self, macro_objective: str, base64_image: str, global_history: list, context: str = "", current_page_tree: dict = None, reexplore_module: str = None, recent_sub_objectives: list = None, container_stack: list = None) -> dict:
        """
        为探索生成短期子目标 (Planner)
        """
        logger.info(f"🕵️‍♂️ [Planner] 思考宏观目标: '{macro_objective}'")
        user_prompt = f"宏观目标：{macro_objective}\n"
        if reexplore_module:
            user_prompt += f"【🎯 强制重新探索模式】当前指令明确要求重新深度探索模块【{reexplore_module}】！请无视该模块的历史状态，将其作为全新对象进行地毯式探索，全面覆盖其内部所有Tab标签、折线图拐点、数据卡片与表格！\n"
        if context:
            user_prompt += f"【背景知识】:\n{context}\n"
        if container_stack:
            user_prompt += f"【当前打开的模态弹窗/浮层栈】: {container_stack}\n⚠️ 极度重要：当前有模态弹窗/文件预览窗口处于打开状态！本系统绝对不支持键盘 ESC 键，必须物理点击右上角的【❌】关闭按钮！如果你打算前往其他主模块或结束当前页面测试，必须优先规划：sub_objective: '点击弹窗右上角关闭按钮【❌】以关闭当前窗口'！严禁在未关闭弹窗时直接操作顶部导航栏！\n"
        if recent_sub_objectives:
            user_prompt += f"【最近已执行过的子目标历史】:\n" + "\n".join([f"- {obj}" for obj in recent_sub_objectives[-5:]]) + "\n⚠️ 铁律：严禁重复派发最近已执行过的相同子目标！如果该目标已尝试过，请推进到下一步或切换目标！\n"
        if current_page_tree:
            from core.explorer_agent.page_map_builder import PageMapBuilder
            mermaid_str = PageMapBuilder.dict_to_mermaid_string(current_page_tree)
            user_prompt += f"【当前已探索的应用架构图 (Mermaid)】:\n```mermaid\n{mermaid_str}\n```\n"
        if global_history:
            defective_items = [h for h in global_history if "熔断跳过" in h or "已发现缺陷" in h]
            normal_items = [h for h in global_history if h not in defective_items]
            user_prompt += f"【全局已探索过的元素】: {', '.join(normal_items[-20:])}\n请尽量避开已探索过的区域。\n"
            if defective_items:
                user_prompt += f"【已发现缺陷并熔断的目标 (绝对严禁再次规划重试)】: {', '.join(defective_items[-10:])}\n"

        user_prompt += "请分析截图，并生成下一个短期子目标及步数预算。"

        return self._call_llm(
            system_prompt=PLANNER_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            base64_image=base64_image
        )

    def execute_sub_objective(self, sub_objective: str, base64_image: str, context: str = "", history: list = None, global_history: list = None, current_page_tree: dict = None, reexplore_module: str = None, container_stack: list = None) -> dict:
        """
        执行短期子目标的具体动作 (Worker)
        """
        logger.info(f"🤖 [Worker] 执行子目标: '{sub_objective}'")
        user_prompt = f"当前子目标：{sub_objective}\n"
        if reexplore_module:
            user_prompt += f"【🎯 提示】：当前处于重探模块【{reexplore_module}】流程中，请深入该模块内各控件进行充分测试与验证。\n"
        if context:
            user_prompt += f"【背景知识】:\n{context}\n"
        if container_stack:
            user_prompt += f"【当前活跃模态弹窗栈】: {container_stack}\n"
        if current_page_tree:
            from core.explorer_agent.page_map_builder import PageMapBuilder
            mermaid_str = PageMapBuilder.dict_to_mermaid_string(current_page_tree)
            user_prompt += f"【当前已探索的应用架构图 (Mermaid)】:\n```mermaid\n{mermaid_str}\n```\n"
        if global_history:
            user_prompt += f"【全局已探索过的元素】: {', '.join(global_history[-10:])}\n"
        if history:
            user_prompt += "【最近的动作历史】:\n" + "\n".join(history) + "\n⚠️ 警告：请分析历史记录，不要死循环执行刚做过的动作！\n"

        user_prompt += "请结合截图决定下一步的精准操作。"

        return self._call_llm(
            system_prompt=WORKER_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            base64_image=base64_image
        )

    def analyze_failure_and_suggest_fix(self, failed_prompt: str, error_msg: str, base64_image: str) -> dict:
        """
        语义失败分析器 (Semantic Self-Healer)
        当某个步骤物理重试耗尽后，让 AI 看一眼案发现场截图，
        推断失败原因，并给出一个"前置补救动作"建议，
        以便 ActionRunner 执行该补救后再次尝试原步骤。

        返回 JSON 格式:
        {
            "can_fix": true/false,
            "reason": "AI 对失败原因的分析",
            "fix_action": "补救动作的自然语言描述，例如：点击触发弹窗的按钮",
            "fix_type": "click" | "scroll_down" | "scroll_up" | "press_escape" | "wait"
        }
        """
        system_prompt = SELF_HEAL_SYSTEM_PROMPT

        user_prompt = (
            f"【失败的操作指令】: {failed_prompt}\n"
            f"【报错原因】: {error_msg}\n\n"
            "请结合截图，分析失败原因，并给出前置补救动作。"
        )

        logger.info("🔬 [语义自愈] 启动失败分析器，请 AI 诊断失败根因并推荐补救方案...")
        return self._call_llm(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            base64_image=base64_image
        )
