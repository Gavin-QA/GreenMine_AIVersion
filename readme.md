# Electron AI Vision — 纯视觉驱动的 UI 自动化巡检框架

本项目是一个专门针对复杂 Electron 桌面端（大屏展示、图表渲染、高频接口）设计的**纯视觉驱动 AI 智能体（Agent）测试框架**。彻底抛弃传统的 DOM/XPath 定位逻辑，采用自然语言编写用例，通过大模型（如 Qwen-VL / GPT-4o）的视觉能力实现 UI 的“感知、决策与交互”。

---

## 🤖 System Context for LLMs (大模型阅读指南)
**[CRITICAL INSTRUCTION FOR AI AGENTS]** 
如果你是正在辅助开发本项目的 AI 助手，请严格遵守以下架构规约：
1. **No Page Objects & No Selectors**: 本项目彻底摒弃 POM 模式。**绝对不要**生成基于 `id`, `xpath`, `css` 等底层 DOM 的定位代码。
2. **Vision-First Execution**: 所有的页面交互（点击、输入）与断言，均需通过 `core/vision_agent.py` 将屏幕截图发送给多模态大模型，由大模型返回目标元素的绝对坐标 `(x, y)` 或语义状态验证结果。
3. **Natural Language Cases**: 测试用例一律在 `test_cases/` 目录下以 `.yaml` 格式使用自然语言编写，Python 代码仅作为底层执行器。

---

## ✨ 核心特性

- **0 代码编写用例**：通过 YAML 文件使用自然语言描述测试步骤（如：`点击首页的固定式空气压缩机面板`），业务人员与产品经理可零成本接入。
- **降维打击复杂大屏**：传统 API 拦截无法准确校验 Canvas 图表渲染是否正确。本框架通过 AI“看图”直接比对图表形态、重叠问题及前端白屏，还原最真实的用户视角。
- **超强自我容错**：由于不依赖前端元素属性，即使研发对组件库进行重构、修改了所有的 `class` 或 `id`，只要页面视觉呈现无大变动，巡检依然可以稳定通过。

---

## 🏗️ 核心架构

框架采用 **感知 -> 决策 -> 执行** 的 ReAct 闭环：
1. **底座层 (Playwright over CDP)**：仅负责通过远程调试端口直连 Electron 进程，执行全屏截图，以及根据接收到的 `(x, y)` 坐标模拟鼠标物理点击。
2. **大脑层 (Vision Agent)**：接收 YAML 指令与当前截图，利用多模态大模型识别 UI 元素，转换为具体坐标或执行业务断言。
3. **编排层 (调度器)**：串行或并行解析 YAML 用例，记录每一步的截图凭证与 AI 推理日志，最终生成可视化巡检报告。

---

## 📂 目录结构

```text
electron_ai_vision/
├── config.yaml            # 全局环境配置 (模型 API Key, Electron 路径, 调试端口)
├── core/                  # 框架底层驱动 (Python)
│   ├── browser.py         # Playwright 启动与 CDP 连接底层封装
│   ├── vision_agent.py    # 封装与视觉大模型 (如 Qwen/GPT) 的多模态交互请求与坐标解析
│   └── action_runner.py   # 将 AI 返回的坐标转化为鼠标/键盘动作，并负责流程编排
├── test_cases/            # 纯自然语言用例区 (无需写代码)
│   ├── check_production.yaml # 生产管理大屏等业务场景巡检
│   └── check_equipment.yaml  # 矿山主通风机等设备状态校验
├── reports/               # 自动生成的可视化报告与案发现场截图存储区
├── .env                   # 敏感环境变量 (如 API_KEY, 请勿提交 Git)
├── requirements.txt       # Python 依赖清单
└── main.py                # 项目启动主入口