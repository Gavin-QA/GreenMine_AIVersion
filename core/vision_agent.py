import json
import logging
import re
from typing import Any, Dict, List, Optional, Tuple

import requests
from requests.exceptions import Timeout, RequestException

from config.settings import settings

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

    # 针对自主探索步骤的系统提示词 (Planner)
    PLANNER_SYSTEM_PROMPT = """你是一个高层规划者 (Planner Agent)，负责在一个未知的 UI 系统中进行自主探索的宏观规划。
基于用户的宏观探索目标、当前的屏幕截图，以及历史已交互过的元素，你的任务是制定下一个短期子目标 (Sub-Objective)。

你必须输出且仅输出一个合法的 JSON 对象，不要包含任何 markdown 代码块标识。

JSON 结构如下:
{
  "thought": "你的详细推理过程。分析当前画面状态，结合历史，决定下一步的大致方向",
  "sub_objective": "下一步的短期子目标，例如：'测试左侧菜单中的报表功能' 或 '在当前页面寻找所有的点击元素并测试'",
  "allocated_steps": 8 // 为这个子目标分配的探索步数预算 (整数，建议 5~15 之间)
}
"""

    # 针对自主探索步骤的系统提示词 (Worker)
    WORKER_SYSTEM_PROMPT = """你是一个高度智能的执行者 (Worker Agent)。
你的目标是根据 Planner 设定的短期子目标 (Sub-Objective)，以及当前的屏幕快照和短期历史操作记录，自主决定下一步的精准操作。
绝对不允许点击任何具有破坏性的按钮（删除、重置等）。

你必须输出且仅输出一个合法的 JSON 对象，不要包含任何 markdown 代码块标识。

JSON 结构如下:
{
  "thought": "结合子目标和历史记录，分析你为什么要执行这个动作",
  "action": "click", // 必须是 "click", "hover", "wait", "finish" 之一。如果子任务完成或无法继续，选择 finish
  "element_desc": "准备交互的元素名称或描述（用于记录历史）",
  "x_percent": 0.5, // 仅在 click/hover 时需要。水平坐标百分比 (0.0 到 1.0)
  "y_percent": 0.5  // 仅在 click/hover 时需要。垂直坐标百分比 (0.0 到 1.0)
}
"""

    # 针对动作类步骤（点击、输入）的系统提示词
    ACTION_SYSTEM_PROMPT = """你是一个高精度的 UI 自动化操作助手，专门用于视觉驱动的屏幕坐标定位。
基于用户给出的指令和提供的屏幕截图，你的任务是在画面中找到对应的 UI 元素，并返回其精确的中心点坐标。
坐标应该被归一化到 0.0 到 1.0 的百分比之间（左上角为 0,0，右下角为 1,1）。
你必须输出且仅输出一个合法的 JSON 对象，不要包含任何 markdown 代码块标识。

JSON 结构如下:
{
  "found": true,
  "thought": "你的思考和推理过程，解释你是在屏幕哪个区域找到该元素的",
  "x_percent": 0.152,
  "y_percent": 0.853
}
如果元素确实在屏幕上不存在，请将 found 设为 false。
"""

    # 针对 Hybrid 模式的 DOM 匹配提示词
    DOM_MATCH_SYSTEM_PROMPT = """你是一个高精度的 UI 自动化操作助手。
当前系统提供了一份从浏览器 DOM 抓取的部分可交互元素的列表（JSON 数组格式，包含元素的文本与ID）。
你的任务是：结合用户给出的指令，以及当前屏幕的截图，从给定的元素列表中选出最匹配目标的元素 ID。

【极度重要警告】
由于当前系统包含 UE 虚幻引擎 / WebRTC / Canvas 等复杂的 3D 渲染区域，你要找的目标元素极有可能**根本不在**给定的 DOM 列表中！
如果目标元素在截图中清晰存在，但在 JSON 列表中找不到完全吻合的条目，**你绝对不能强行瞎猜一个 ID（如随便选个 icon_or_empty）**。你必须果断将 `found` 设为 `false`，我们的系统会自动降级到纯视觉坐标模式进行处理。

你必须输出且仅输出一个合法的 JSON 对象，不要包含任何 markdown 代码块标识。
JSON 结构如下:
{
  "found": true,
  "thought": "你的思考和推理过程。重点分析目标是否真正存在于给定的列表中。",
  "target_id": 2 // 仅在 found 为 true 时需要
}
如果列表中没有完全符合的元素，请务必将 found 设为 false。
"""

    # 针对断言类步骤的系统提示词
    ASSERT_SYSTEM_PROMPT = """
你是一个纯视觉驱动的 UI 自动化测试断言 Agent。
你需要仔细观察提供的截图，根据用户的断言指令，判断当前的页面画面是否符合预期。

【断言铁律】
- 不要猜测接口数据。只断言画面上肉眼可见的内容（例如图表曲线形状、文字内容、颜色、弹窗状态）。
- 如果画面内容违背物理常识或业务边界（例如瞬时功率为负数），即使没有系统报错，也必须判定为失败。

【输出格式强制要求】
你必须且只能输出合法的 JSON 格式。禁止输出任何 Markdown 标记（如 ```json），禁止包含任何前后缀文本。
JSON 结构如下：
{
  "thought": "描述你观察画面的过程，说明你看到了什么，没有看到什么",
  "passed": true,
  "assert_reason": "详细说明为什么判定为通过或失败"
}
}
"""

    API_ASSERT_SYSTEM_PROMPT = """
你是一个高级 UI 自动化测试断言 Agent，拥有“透视”底层网络数据的能力。
你将同时收到一张“前端页面截图”和一段“底层接口响应 JSON 数组”。
你的任务是根据用户的指令，从 JSON 数组中找出关键业务数据，并验证屏幕上的 UI 是否正确渲染了这些数据。

【断言铁律】
- 仔细阅读 JSON，找到最贴近用户意图的字段。
- 容错性：前端可能会对数字进行格式化（如 14200 变成 14,200 或 1.42w），只要数值逻辑一致即算通过。
- 只要发现 UI 漏渲、渲染成 NaN/undefined，或者数据不匹配，立刻判定为失败。

【输出格式强制要求】
你必须且只能输出合法的 JSON 格式。禁止输出任何 Markdown 标记（如 ```json），禁止包含任何前后缀文本。
JSON 结构如下：
{
  "thought": "描述你从 JSON 中提取了什么字段（值为多少），并在截图中哪个位置找到了对应渲染，比对过程是什么",
  "passed": true,
  "assert_reason": "详细说明为什么判定为通过或失败"
}
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
                system_prompt=self.API_ASSERT_SYSTEM_PROMPT,
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
                system_prompt=self.DOM_MATCH_SYSTEM_PROMPT,
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
            system_prompt=self.ACTION_SYSTEM_PROMPT,
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
            system_prompt=self.ASSERT_SYSTEM_PROMPT,
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
            system_prompt=self.ASSERT_SYSTEM_PROMPT,
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

    def plan_sub_objective(self, macro_objective: str, base64_image: str, global_history: list, context: str = "") -> dict:
        """
        为探索生成短期子目标 (Planner)
        """
        logger.info(f"🕵️‍♂️ [Planner] 思考宏观目标: '{macro_objective}'")
        user_prompt = f"宏观目标：{macro_objective}\n"
        if context:
            user_prompt += f"【背景知识】:\n{context}\n"
        if global_history:
            user_prompt += f"【全局已探索过的元素】: {', '.join(global_history)}\n请尽量避开已探索过的区域。\n"
            
        user_prompt += "请分析截图，并生成下一个短期子目标及步数预算。"
        
        return self._call_llm(
            system_prompt=self.PLANNER_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            base64_image=base64_image
        )

    def execute_sub_objective(self, sub_objective: str, base64_image: str, context: str = "", history: list = None, global_history: list = None) -> dict:
        """
        执行短期子目标的具体动作 (Worker)
        """
        logger.info(f"🤖 [Worker] 执行子目标: '{sub_objective}'")
        user_prompt = f"当前子目标：{sub_objective}\n"
        if context:
            user_prompt += f"【背景知识】:\n{context}\n"
        if global_history:
            user_prompt += f"【全局已探索过的元素】: {', '.join(global_history[-10:])}\n"
        if history:
            user_prompt += "【最近的动作历史】:\n" + "\n".join(history) + "\n⚠️ 警告：请分析历史记录，不要死循环执行刚做过的动作！\n"
            
        user_prompt += "请结合截图决定下一步的精准操作。"
        
        return self._call_llm(
            system_prompt=self.WORKER_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            base64_image=base64_image
        )
