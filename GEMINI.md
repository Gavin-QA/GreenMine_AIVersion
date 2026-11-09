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
- **禁止在运行时调用页面刷新 (Reload)**：在 WebRTC 像素流架构下，网页刷新会强行切断与 UE 信号服务器的 WebRTC 握手导致 UE 崩溃断流。若遇极端卡死，底层支持关闭启动器并冷重启。
- **禁止点击“一键隐藏/收起”**：大屏两翼 2D 业务面板必须永久保持展开状态，严禁点击折叠按钮导致界面失去业务面板陷入三维空转。
- **禁止在环境未通过准入校验时盲跑**：启动测试前必须保证目标 Launcher 环境与配置的基线一致（通过 `env_check` 校验后端接口基地址与前端包版本），严禁在过期前端包或错误环境中盲目测试。

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
6. **智能缺陷闭环、大模型查重与责任人分流 (Auto Bug Reporting & Triage)**：
   - 框架集成了完全解耦的 `BugReporter` 模块。当 ActionRunner 执行失败产生崩溃时，能自动进行快照隔离与缺陷归档（生成全局 JSON 数据库及全景 HTML 门户）。
   - 引入大模型语义判别机制，每次生成 Bug 前会利用 LLM 对全局 Bug 库进行比对，若发现相同本质的老 Bug，则仅增加复现次数，从根源解决测试缺陷去重痛点。
   - **责任人自动分流标准**：
     - **前端问题**（JS报错堆栈、样式崩塌、组件未渲染、白屏）➔ 自动指派 **陈贻雄** (`chenyixiong`)
     - **后端问题**（5xx错误、网络超时、接口数据结构异常）➔ 自动指派 **梅本霞** (`meibenxia`)
     - **数据接入问题**（物联网通信、物模型映射、机器人与测点数据接入）➔ 自动指派 **李云骢** (`liyuncong`) / **靳正武**

## 4. Playwright 的角色定位 (Role of Playwright)
Playwright 在本框架中仅作为“底座外设”：
- 通过 CDP (`--remote-debugging-port`) 挂载 Electron 进程。
- 负责获取屏幕截图、精简 DOM 树、静默拦截 JSON 网络请求。
- 负责充当机械臂，执行大模型输出的物理 `x, y` 坐标点击与键盘输入。
- **严禁让 Playwright 参与任何业务逻辑的分支判断。**

## 5. YAML 用例标准词汇表 (YAML Action Types)
编写或修改用例时，必须使用以下类型：
- `action`: 用于执行点击操作（包含寻找元素坐标的能力）。
- `input`: 用于在输入框中输入文字（支持 `fuzz: true` 自动注入边界畸形字符、`clear_first`、`press_enter`）。
- `zoom`: 用于三维场景/地图的滚轮缩放（如 `direction: in/out`, `steps: 3`）。
- `rotate_3d`: 用于三维孪生视界漫游旋转（如 `direction: left/right/up/down`, `distance: 250`, `button: right`）。
- `canvas_stress_drag`: 用于 3D 场景暴力晃动抗压测试（安全中央视口围栏内执行高频 8 字螺旋甩动与突发滚轮推拉风暴，如 `mode: hybrid`, `rounds: 3`, `radius: 300`，检验 UE5 像素流断流、模型破面与 WebGL 崩溃）。
- `scroll`: 用于长列表、告警列表、长表格容器的内部物理滚轮翻页（如 `direction: down/up`, `delta: 300`）。
- `slide`: 用于时间轴（Timeline Slider）、阈值调节滑块等组件的连续平滑拖拽。
- `drag`: 用于物理拖拽交互（如拖动视口、元素平移）。
- `assert`: 纯视觉语义断言（例如“画面是否变成红色”，“弹窗是否显示”）。
- `api_assert`: UI 渲染与底层 JSON 数据的双向交叉断言。
- `physics_sanity_check`: 矿山物理常识与合理性断言（零 Token 静态脏值预筛 + 多模态视觉巡检，精准拦截 `NaN`/`undefined`、负人数、越界比率与 ERP 1000倍量纲灾难）。
- `assert_no_console_errors`: 无声崩溃嗅探断言（高强度过滤无关前端告警噪音，精准拦截 `Uncaught TypeError`、Vue 渲染期崩溃、`ChunkLoadError` 与 WebGL 上下文丢失）。
- `memory_leak_check`: 显存/内存探针（通过 CDP 强制 Full GC 后采集对比 V8 JSHeap、DOM 节点数、事件监听器与 ECharts/Canvas 实例水位，支持 `mode: baseline/assert`、`max_heap_mb`、`max_growth_mb`）。
- `wait_for`: 智能视觉轮询等待（例如“等待直到主标题出现”）。
- `wait`: 物理强制等待（例如 `seconds: 2.0`）。
- `freeze_check`: 双图时序对比防假死检测。
- `back`: 用于路由历史回退或返回上一级视图。
- `reload`: 【已废弃】严禁网页 reload。若界面严重卡死，底层自动通过优雅关闭并冷重启启动器恢复，杜绝在浏览器内单方面刷新导致 UE 像素流断裂。

## 6. 矿山大屏测试“三大铁律”
1. **UI 必须忠于 API**：发现数值，必须通过 `api_assert` 到 JSON 中去核对，防范前端张冠李戴。
2. **动态必须流动**：大屏不能停顿，必须使用 `freeze_check` 核对时间流逝或跑马灯位移。
3. **数据不能违背物理常识**：AI 需自带业务防线，对异常数字（如几百万度电的瞬时功率、负人数）予以最高级别警报，即使没弹红框报错也要判定为 Fail。

## 7. 专属技能协同矩阵 (Skills Ecosystem)
在涉及特定领域任务时，必须优先调度对应的标准 Skill 确保流程确定性与资产闭环：
- **`feishu_pack`**：当需要对外分享或向飞书团队工坊发布测试成果时，严禁直接发送数 GB 原始运行目录。必须通过该 Skill 进行多线程 WebP 激进压缩（GB 级 ➔ 30~50MB）并保全双现场证据。
- **`yaml_authoring`**：编写新测试用例时必须遵循该 Skill 的 Prompt 范式与三大铁律，写完后必须自主调用 `validate_case.py` 静态合规校验。
- **`zentao_sync`**：缺陷提单或回填时，严格遵循前置 AI 智能初诊守卫，并按前端（陈贻雄）与后端（梅本霞）标准自动分流与推单。

## 8. 人机协作工作流规范 (Two-Stage Interaction Protocol)
- **阶段一（诊断、回答与方案确认）**：
  当用户提出问题或新需求时，AI 应先深入分析根因，提供清晰的技术方案或解答，**等待用户确认**。严禁在未经用户确认方案前贸然大动干戈。
- **阶段二（确认后全自动闭环，严禁频繁打扰）**：
  一旦用户确认（例如回复“是”、“行”、“可以”、“来吧”、“按这个方案做”等），AI 必须**自主闭环完成后续全部实施工作**：
  包括修改文件、语法检查、运行必须的终端验证命令、以及 Git 提交保存。
  **在此执行阶段中，绝对不需要、也严禁在对话中反复询问“我是否可以运行某命令”**，所有相关命令直接放行执行，一气呵成直接向用户汇报最终成果！