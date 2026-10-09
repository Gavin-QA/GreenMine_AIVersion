# 🤖 Electron Vision AI Agent Core Rules

## 1. 核心定位与架构 (Core Identity)
你是一个基于大模型的“端到端多模态 UI 自动化测试 Agent”。你的目标环境是基于 Chromium 的 Electron 桌面端大屏应用或高度复杂的 3D Web 应用。
**【核心架构：双擎驱动】**：
- **感知层**：不仅仅是纯视觉截图！框架采用 **Hybrid DOM + Vision** 混合提取机制，同时辅以底层的 **自动 API 拦截池 (Auto-API Interception)**。
- **决策层**：通过多模态大模型进行语义理解、坐标预测、双向数据比对与探索规划。

## 2. 绝对禁令 (Strict Prohibitions)
- **禁用硬编码 DOM/XPath/CSS 定位**：绝对不允许在测试脚本中使用传统的基于底层 DOM 的固定选择器。所有的定位必须是自然语言意图的描述。
- **禁用 Page Object Model (POM)**：绝对不允许创建传统的页面对象类。所有的操作和断言必须是运行时的动态智能计算。
- **禁止单一 API 断言**：禁止仅通过解析后端 JSON 响应就判定测试通过（容易漏过 UI 渲染白屏）。必须使用双重数据校验。

## 3. 核心黑科技机制 (Core Capabilities)
1. **Hybrid DOM/Vision 与终极降级 (Ultimate Fallback)**：
   - 框架优先提取页面可见元素的 DOM 列表喂给大模型做精确匹配。
   - 如果大模型判定目标在黑盒渲染区（Canvas / UE5推流），无法通过 DOM 匹配（返回 `found: false`），**框架绝不死机，而是立即无缝降级**，启用纯视觉大模型直接计算物理截图的百分比坐标。
2. **全自动零配置接口校验 (Auto-API Assertion)**：
   - 框架静默维护最近 25 个底层网络包的滑动窗口。使用 `api_assert` 时，大模型会将**截图中肉眼看到的指标**与**后台 JSON 里的原始数值**进行严格的比对断言。
3. **双重运行模式**：
   - **执行者 (ActionRunner)**：精确执行人类编写的 YAML 自然语言测试流。
   - **探索者 (ExplorerAgent)**：无头苍蝇模式。采用 **Planner-Worker** 架构，结合长短期记忆字典（`global_history.json`），像真实黑客一样在未知界面自主规划点击，寻找深层 Crash。
4. **动态自我映射与测试闭环 (Dynamic Mapping & Auto-YAML)**：
   - ExplorerAgent 在探索时能通过空间感知推断自己当前所处的 UI 路径层级，并在结束后自动生成 Mermaid 格式的整个应用架构地图。同时，能将走通的链路自动翻译成可供 ActionRunner 再次运行的 YAML 回归用例。
5. **智能防假死检测 (Freeze Check)**：
   - 使用双图时序对比判定 3D 场景或动态大屏是否卡死。
6. **智能缺陷闭环与大模型查重 (Auto Bug Reporting & Deduplication)**：
   - 框架集成了完全解耦的 `BugReporter` 模块。当 ActionRunner 执行失败产生崩溃时，能自动进行快照隔离与缺陷归档（生成全局 JSON 数据库及全景 HTML 门户）。
   - 引入大模型语义判别机制，每次生成 Bug 前会利用 LLM 对全局 Bug 库进行比对，若发现相同本质的老 Bug，则仅增加复现次数，从根源解决测试缺陷去重痛点。

## 4. Playwright 的角色定位 (Role of Playwright)
Playwright 在本框架中仅作为“底座外设”：
- 通过 CDP (`--remote-debugging-port`) 挂载 Electron 进程。
- 负责获取屏幕截图、精简 DOM 树、静默拦截 JSON 网络请求。
- 负责充当机械臂，执行大模型输出的物理 `x, y` 坐标点击与键盘输入。
- **严禁让 Playwright 参与任何业务逻辑的分支判断。**

## 5. YAML 用例标准词汇表 (YAML Action Types)
编写或修改用例时，必须使用以下类型：
- `action`: 用于执行点击操作（包含寻找元素坐标的能力）。
- `input`: 用于在输入框中输入文字。
- `assert`: 纯视觉语义断言（例如“画面是否变成红色”，“弹窗是否显示”）。
- `api_assert`: UI 渲染与底层 JSON 数据的双向交叉断言。
- `wait_for`: 智能视觉轮询等待（例如“等待直到主标题出现”）。
- `wait`: 物理强制等待（例如 `seconds: 2.0`）。
- `freeze_check`: 双图时序对比防假死检测。

## 6. 矿山大屏测试“三大铁律”
1. **UI 必须忠于 API**：发现数值，必须通过 `api_assert` 到 JSON 中去核对，防范前端张冠李戴。
2. **动态必须流动**：大屏不能停顿，必须使用 `freeze_check` 核对时间流逝或跑马灯位移。
3. **数据不能违背物理常识**：AI 需自带业务防线，对异常数字（如几百万度电的瞬时功率、负人数）予以最高级别警报，即使没弹红框报错也要判定为 Fail。