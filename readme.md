# Electron AI Vision — 纯视觉驱动的 UI 自动化巡检框架

本项目是一个专门针对复杂 Electron 桌面端（大屏展示、图表渲染、高频接口）设计的**纯视觉驱动 AI 智能体（Agent）测试框架**。彻底抛弃传统的 DOM/XPath 定位逻辑，采用自然语言编写用例，通过大模型（如 Qwen-VL / GPT-4o）的视觉能力实现 UI 的“感知、决策与交互”。

---

## 🤖 System Context for LLMs (大模型阅读指南)
**[CRITICAL INSTRUCTION FOR AI AGENTS]** 
如果你是正在辅助开发本项目的 AI 助手，请严格遵守以下架构规约：
1. **No Hardcoded Selectors (Hybrid Architecture)**: 本项目彻底摒弃传统的 POM 模式与硬编码选择器。**测试脚本中绝对不能出现** `id`、`xpath` 或 `css`。在底层驱动上，框架采用 **DOM 节点实时抽取 + 纯视觉回退 (Hybrid DOM/Vision)** 机制，由 AI 在运行时动态将自然语言意图与提取到的 DOM 元素（如没有 DOM，则回退到视觉绝对坐标）进行对齐映射。
2. **Vision-First Execution**: 所有的页面交互（点击、输入）与断言，均需通过 `core/vision_agent.py` 将屏幕截图与底层数据包发送给多模态大模型，由大模型返回目标元素的 DOM 标识、绝对坐标 `(x, y)` 或是语义状态验证结果。
3. **Natural Language Cases**: 测试用例一律在 `test_cases/` 目录下以 `.yaml` 格式使用自然语言编写，Python 代码仅作为底层执行器。

---

## ✨ 核心特性

本项目打破了传统的“死板脚本”模式，采用了双 Agent（智能体）驱动机制，能够满足从核心流程回归到边缘缺陷挖掘的全方位自动化需求：

1. **双模式特化 Agent 驱动**：
   - **执行者 (ActionRunner)**：基于 YAML 脚本的“按部就班”测试。业务人员可通过纯自然语言零代码编写业务断言，由 AI 将语言精准转化为 DOM 节点点击或像素级物理动作。
   - **探索者 (ExplorerAgent)**：无脚本的“自主混沌探索”。输入一句话目标（如 `随意乱点找Bug`），采用 **Planner-Worker (规划者-执行者) 双层架构**。Planner 负责宏观分解任务，Worker 负责结合上下文规则（如 Hover 展开菜单等）精准执行微操，专门挖掘人类难以覆盖的深层缺陷。
2. **长短期记忆机制 (Action History)**：在探索模式下，内置短期防死循环记忆（规避局部无意义重复）与全局长效记忆（记录已访问的模块）。**全局记忆会实时持久化到本地 (`global_history.json`)**，彻底避免 AI 走回头路，并方便开发者随时审查探索轨迹。
3. **降维打击复杂大屏与黑盒渲染**：传统 API 拦截无法校验 Canvas/UE 图表渲染是否正确，传统 DOM 定位无法穿透黑盒。本框架通过 AI“看图”与底层数据双重校验，既能比对图表形态、重叠与白屏问题，又能严格核对渲染数值。
4. **超强自我容错与网络重试**：脱离底层 `class` 与 `id` 的绑定，不仅能应对前端组件重构，还具备底层大模型请求的防超时/断网自动重试恢复能力。
5. **智能视觉等待 (Intelligent Visual Wait)**：彻底抛弃低效的“死等(sleep)”，支持传入自然语言条件（如“等待左侧菜单树渲染完毕”），由 AI 轮询屏幕直到满足条件，将启动与跳转的空耗延迟降至最低，极大提升脚本稳定性。
6. **全自动零配置接口校验 (Auto-API Assertion)**：独创的底层静默抓包与大模型视觉双重比对机制。无需配置任何接口 URL 或抽取规则，框架会在后台自动维护滑动网络数据池。只需一句自然语言，大模型即可自主从底层 JSON 中提取数据，并与 UI 渲染的文字、图表进行深度交叉验证。附带热连接 (Attach) 模式下的 `Ctrl+R` 无伤重载保护，确保 3D/UE 场景下不掉线且不漏首屏初始网络包。
7. **动态组件拓扑树与双图状态跃迁 (Post-Click Diff & Component Awareness)**：
   - **Post-Click Diff 双图差分**：每次点击前后抓取屏幕快照与 DOM 状态，通过“DOM 模态监听 + PIL 图像差分”双擎，毫秒级判定当前是打开弹窗（压栈）、关闭弹窗（出栈）、页面跳转还是局部刷新，彻底解决浮层内组件与页面组件混淆的痛点。
   - **Component Awareness 组件感知**：自动识别控件类型（🔲 按钮、📝 输入框、🔽 下拉框、☑️ 勾选框、📋 列表、🗺️ 地图等）及其所属的父容器。
   - **不变骨架延伸基座**：严格基于 `docs/explore_rules.md` 中的 6 大一级模块与 33 个二级业务菜单作为全局不可变底座，定点延伸已探索页面的内部组件，未探索页面保持完整全景。
   - **列表项智能折叠去重**：自动将列表多行重复操作按钮泛化合并为“（操作列）”，并在 `docs/auto_page_map.md` 中实时沉淀出极度工整直观的**纯 Markdown 树形组件大纲**（同时附带 Mermaid 辅助拓扑图）。
8. **探索闭环与用例沉淀 (Auto-YAML Generation)**：探索者模式不仅能找 Bug，它走过的每一条有效链路都会被结构化记录，并在结束后自动翻译为框架可直接执行的原生 YAML 回归测试脚本。
9. **智能自愈与前置补救 (Semantic Self-Healing)**：内置“三层防线”自愈机制。当物理重试耗尽时，AI 调取案发现场截图分析失败根因，自动给出点击前置 Tab、收起遮挡层或滚动查找等补救动作，实现无人值守的自我修复。
10. **解耦式缺陷闭环与大模型查重 (Auto Bug Reporting & Deduplication)**：深度集成完全解耦的 `BugReporter` 模块。当执行或探索发现控制台异常或断言失败时，自动备份现场凭证，并利用大模型进行语义特征查重，杜绝重复上报，自动生成 JSON、Markdown、CSV 三维缺陷大盘。

---

## 🏗️ 核心架构

框架采用 **感知 -> 决策 -> 执行** 的 ReAct 闭环：
1. **底座层 (Playwright over CDP)**：负责通过远程调试端口直连 Electron 进程，执行全屏截图、**交互式 DOM 树特征抽取**、**网络 API 接口静默拦截**，并根据指令精准模拟鼠标物理动作。
2. **大脑层 (Vision Agent)**：底层中枢神经基建。接收上下文指令、当前截图、压缩版 DOM 树以及最近的 API JSON 包，利用多模态大模型强大的推理能力，精准映射目标 UI 元素或执行深度业务双重断言。
3. **编排层 (调度器)**：
   - **Yaml 调度器 (ActionRunner)**：串行解析 YAML 自然语言用例，执行步骤并处理异常自愈。
   - **探索引擎 (ExplorerAgent)**：基于 Planner-Worker 双层设计，通过 Post-Click Diff 维护容器调用栈与长短期记忆（`global_history.json`），动态渲染全景架构树并沉淀回归用例。

---

## 📂 目录结构

```text
electron_ai_vision/
├── config.yaml            # 全局环境基础配置
├── .env                   # 敏感环境变量 (如 API_KEY, 请勿提交 Git)
├── config/                # 框架配置模块
│   └── settings.py        # 环境变量与 YAML 配置文件的读取与合并
├── core/                  # 框架底层核心驱动
│   ├── action_runner.py   # 解析 YAML 步骤，控制底层执行流程，处理异常截图与自愈
│   ├── bug_reporter.py    # [缺陷闭环] 完全解耦的智能缺陷记录与大模型查重模块
│   ├── browser/           # [驱动层] 封装 Electron 启动、CDP 连接与底层数据抓取
│   │   ├── driver.py            # 核心生命周期与鼠标键盘动作模拟
│   │   ├── dom_extractor.py     # Hybrid DOM 元素提取器 (集成 Component Awareness)
│   │   ├── network_monitor.py   # 底层 API 静默抓包与控制台报错监控
│   │   └── screenshot.py        # 截图裁剪与 Base64 预处理
│   ├── explorer_agent/    # [探索层] 混沌探索者智能引擎
│   │   ├── agent.py             # ReAct Planner-Worker 循环调度引擎 (维护容器调用栈)
│   │   ├── post_click_diff.py   # [状态跃迁] 点击前后双图与 DOM 差分探测器
│   │   ├── page_map_builder.py  # 纯 Markdown 组件拓扑树生成与 Mermaid 渲染 (列表折叠+导航去噪)
│   │   └── trajectory_exporter.py # 操作轨迹记录与 YAML 用例自动生成
│   └── vision/            # [感知层] 视觉大模型连接层
│       ├── agent.py             # 封装多模态大模型的 API 请求与解析
│       └── prompts.py           # 集中管控所有 AI System Prompts (速查文档头管理)
├── utils/                 # 通用基础设施工具
│   ├── artifacts.py       # 测试产物管理（按批次生成独立的日志与截图目录）
│   ├── logger.py          # 框架级集中日志管理，支持多用例日志动态切分
│   └── electron_launcher.py # Electron 进程管理辅助工具
├── docs/                  # 文档与规则区
│   ├── explore_rules.md   # 探索模式基础骨架 (6大模块+33个业务菜单) 与交互规矩
│   └── auto_page_map.md   # [AI 自动生成] 动态组件架构拓扑 (纯 Markdown 树 + Mermaid 图)
├── test_cases/            # 纯自然语言用例区 (无需写代码)
│   ├── test_home_mine_intro.yaml # 手工编写的业务场景巡检
│   └── auto_generated_*.yaml     # [AI 自动生成] 探索闭环沉淀的回归用例
├── bugs/                  # 智能缺陷大盘存储区
│   ├── global_bugs.json   # 全局结构化 Bug 数据池 (供 LLM 去重比对)
│   ├── global_bugs.md     # 全局缺陷列表总览 (Markdown)
│   ├── global_bugs.csv    # 全局缺陷数据源 (供 Jira/Excel 导入)
│   └── [Run_ID]/          # 崩溃隔离区 (包含单次崩溃详细 JSON 与现场截图物理备份)
├── reports/               # 自动化产物存储区
├── logs/                  # 日志存储区
│   └── [Run_ID]/          # 按批次时间戳隔离存放启动、单一用例和汇总日志
├── requirements.txt       # Python 依赖清单
└── main.py                # 项目启动主入口，执行全量或单条测试
```

---

## 🚀 快速上手 (Quick Start)

### 1. 运行预设 YAML 业务巡检用例
```powershell
# 运行单一自然语言用例
python main.py --case test_cases/test_home_mine_intro.yaml

# 指定智能等待就绪条件 (AI 视觉轮询)
python main.py --case test_cases/test_home_mine_intro.yaml --wait-ready "主界面左侧菜单树和右侧面板渲染完成"
```

### 2. 启动自主探索与架构生成 (ExplorerAgent)
```powershell
# 在指定模块下自主探索 25 步，自动寻找 Bug 并生成架构拓扑
python main.py --explore "在一级菜单 生产管理 中，自己探索" \
  --explore-context docs/explore_rules.md \
  --wait-ready "主界面左侧菜单树和右侧面板渲染完成" \
  --max-steps 25
```

### 3. 查看产出物
- **组件拓扑树**：查看 [`docs/auto_page_map.md`](docs/auto_page_map.md)，即时查阅以项目骨架为基座延伸的纯 Markdown 组件大纲。
- **自动生成的回归用例**：查看 `test_cases/auto_generated_explore_*.yaml`，走通的有效链路已自动转为可回归 YAML 脚本。
- **缺陷大盘**：查看 [`bugs/global_bugs.md`](bugs/global_bugs.md)，实时追踪去重后的深层崩溃与异常快照。