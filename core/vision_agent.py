import json
import logging
import re
from typing import Any, Dict, Optional, Tuple

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

    # 针对动作类步骤（点击、输入）的系统提示词
    ACTION_SYSTEM_PROMPT = """
你是一个纯视觉驱动的 UI 自动化测试 Agent。你没有页面 DOM 结构，只能像人类一样依靠眼睛（截图）来操作。
用户的指令会在提示词中给出。你需要仔细观察提供的截图，找到用户指令中要求操作的目标元素，并返回该元素的坐标。

【坐标输出规范】
请给出目标元素中心点的百分比坐标：
- x_percent: 从屏幕最左侧 (0.0) 到最右侧 (1.0) 的横向比例
- y_percent: 从屏幕最顶部 (0.0) 到最底部 (1.0) 的纵向比例

【输出格式强制要求】
你必须且只能输出合法的 JSON 格式。禁止输出任何 Markdown 标记（如 ```json），禁止包含任何前后缀文本。
JSON 结构如下：
{
  "thought": "描述你观察画面的过程，找到目标元素的位置特征",
  "found": true,
  "x_percent": 0.50,
  "y_percent": 0.50
}
如果无法在截图中找到目标元素，请将 found 设置为 false，并在 thought 中说明原因。
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

    def _call_llm(self, system_prompt: str, user_prompt: str, base64_image: Optional[str] = None) -> Dict[str, Any]:
        """发起对大模型的 HTTP 请求"""
        if not self.api_key:
            raise VisionAgentException("LLM_API_KEY is not configured.")

        # 组装 OpenAI 兼容的消息格式
        messages = [
            {"role": "system", "content": system_prompt}
        ]

        user_content = [{"type": "text", "text": user_prompt}]
        
        if base64_image:
            # 根据截图格式构建 image_url
            prefix = "data:image/png;base64,"
            if not base64_image.startswith("data:image"):
                base64_image = prefix + base64_image
                
            user_content.append({
                "type": "image_url",
                "image_url": {
                    "url": base64_image
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

        except Timeout:
            logger.error("🧠 大模型请求超时！")
            raise VisionAgentException("Vision LLM Request Timeout")
        except json.JSONDecodeError as e:
            logger.error(f"🧠 大模型返回了非法的 JSON: {e}")
            raise VisionAgentException("Invalid JSON format from LLM")
        except RequestException as e:
            logger.error(f"🧠 大模型请求失败: {e}")
            if e.response is not None:
                logger.error(f"Response: {e.response.text}")
            raise VisionAgentException(f"LLM API Request Failed: {e}")

    def find_element(self, instruction: str, base64_image: str, viewport_width: int, viewport_height: int) -> Tuple[int, int]:
        """
        基于自然语言指令寻找目标元素的绝对坐标
        返回 (x, y) 物理像素坐标。如果找不到则抛出异常。
        """
        logger.info(f"🕵️‍♂️ 寻找元素指令: '{instruction}'")
        
        result = self._call_llm(
            system_prompt=self.ACTION_SYSTEM_PROMPT,
            user_prompt=f"当前页面截图如附图所示。指令：{instruction}",
            base64_image=base64_image
        )
        
        thought = result.get("thought", "")
        logger.info(f"💡 AI 思考链: {thought}")
        
        if not result.get("found", False):
            raise VisionAgentException(f"元素未找到，AI 解释: {thought}")
            
        x_pct = result.get("x_percent")
        y_pct = result.get("y_percent")
        
        if x_pct is None or y_pct is None:
            raise VisionAgentException("大模型返回的数据中缺少坐标字段。")
            
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
