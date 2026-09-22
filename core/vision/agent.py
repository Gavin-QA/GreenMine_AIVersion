import json
import logging
import re
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
            "Content-Type": "application/json"
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
            "temperature": 0.1,  # 视觉识别需要低温度以保证稳定性
            "max_tokens": 1024,
            "response_format": {"type": "json_object"} if self.provider == "openai" else None
        }

        try:
            logger.info(f"🧠 [VisionAgent] 请求大模型: {self.model} ...")
            resp = requests.post(endpoint, json=payload, headers=headers, timeout=60)
            resp.raise_for_status()
            
            data = resp.json()
            content = data["choices"][0]["message"]["content"]
            
            # 解析并清理返回的 JSON
            clean_content = self._clean_json_response(content)
            logger.debug(f"[VisionAgent] 原始响应:\n{clean_content}")
            return json.loads(clean_content)

        except Exception as e:
            logger.error(f"🧠 大模型请求过程发生未知异常: {e}")
            raise VisionAgentException(f"LLM API Unexpected Error: {e}")

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
            passed = result.get("passed", False)
            reason = result.get("assert_reason", "未提供理由")
            
            logger.info(f"💡 AI 思考链: {thought}")
            
            if passed:
                logger.info(f"✅ API 断言结果: True | 理由: {reason}")
            else:
                logger.info(f"❌ API 断言结果: False | 理由: {reason}")
                
            return passed, reason
            
        except Exception as e:
            logger.error(f"🧠 大模型执行 API 双重断言发生异常: {e}")
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
            # 将元素列表精简以节约 Token
            simplified_elements = [{"id": el["id"], "tag": el["tag"], "text": el["text"]} for el in dom_elements]
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

    def plan_sub_objective(self, macro_objective: str, base64_image: str, global_history: list, context: str = "", current_page_tree: dict = None) -> dict:
        """
        为探索生成短期子目标 (Planner)
        """
        logger.info(f"🕵️‍♂️ [Planner] 思考宏观目标: '{macro_objective}'")
        user_prompt = f"宏观目标：{macro_objective}\n"
        if context:
            user_prompt += f"【背景知识】:\n{context}\n"
        if current_page_tree:
            from core.explorer_agent.page_map_builder import PageMapBuilder
            mermaid_str = PageMapBuilder.dict_to_mermaid_string(current_page_tree)
            user_prompt += f"【当前已探索的应用架构图 (Mermaid)】:\n```mermaid\n{mermaid_str}\n```\n"
        if global_history:
            user_prompt += f"【全局已探索过的元素】: {', '.join(global_history)}\n请尽量避开已探索过的区域。\n"

        user_prompt += "请分析截图，并生成下一个短期子目标及步数预算。"

        return self._call_llm(
            system_prompt=PLANNER_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            base64_image=base64_image
        )

    def execute_sub_objective(self, sub_objective: str, base64_image: str, context: str = "", history: list = None, global_history: list = None, current_page_tree: dict = None) -> dict:
        """
        执行短期子目标的具体动作 (Worker)
        """
        logger.info(f"🤖 [Worker] 执行子目标: '{sub_objective}'")
        user_prompt = f"当前子目标：{sub_objective}\n"
        if context:
            user_prompt += f"【背景知识】:\n{context}\n"
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
