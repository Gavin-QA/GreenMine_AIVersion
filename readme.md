# Electron AI Vision — 纯视觉驱动的 UI 自动化巡检框架

本项目是一个专门针对复杂 Electron 桌面端（大屏展示、图表渲染、高频接口、3D/UE 数字孪生）设计的**纯视觉驱动 AI 智能体（Agent）测试框架**。彻底抛弃传统的 DOM/XPath 定位逻辑，采用自然语言编写用例，通过大模型（如 Qwen-VL / GPT-4o）的多模态视觉能力实现 UI 的“感知、决策与交互”。

---

## 🤖 System Context for LLMs (大模型阅读指南)
**[CRITICAL INSTRUCTION FOR AI AGENTS]** 
如果你是正在辅助开发本项目的 AI 助手，请严格遵守以下架构规约：
1. **No Hardcoded Selectors (Hybrid Architecture)**: 本项目彻底摒弃传统的 POM 模式与硬编码选择器。**测试脚本中绝对不能出现** `id`、`xpath` 或 `css`。在底层驱动上，框架采用 **DOM 节点实时抽取 + 纯视觉回退 (Hybrid DOM/Vision)** 机制，由 AI 在运行时动态将自然语言意图与提取到的 DOM 元素（如没有 DOM，则回退到视觉绝对坐标）进行对齐映射。
2. **Vision-First Execution**: 所有的页面交互（点击、输入）与断言，均需通过 `core/vision_agent.py` 将屏幕截图与底层数据包发送给多模态大模型，由大模型返回目标元素的 DOM 标识、绝对坐标 `(x, y)` 或是语义状态验证结果。
3. **Natural Language Cases**: 正式回归用例一律在 `test_cases/` 目录下以 `.yaml` 格式使用自然语言编写，Python 代码仅作为底层执行器。
4. **Tiered Artifacts Lifecycle**: 框架严格区分**长期持久资产 (`artifacts/`)** 与 **单次运行工作区 (`reports/runs/<run_id>/`)**。所有单次运行过程产物必须严格收敛在对应的 `run_id` 目录下，严禁在工程根目录下随意新增散落文件夹。

---

## ✨ 核心特性

本项目打破了传统的“死板脚本”模式，采用了双 Agent（智能体）驱动机制，能够满足从核心流程回归到边缘缺陷挖掘的全方位自动化需求：

1. **双 Agent（执行者 ActionRunner / 探索者 ExplorerAgent）支持 3 种工作流**：
   - **实体一：执行者 (ActionRunner)**
     - 对应工作流 ① **【确定性用例回归】**：严格根据人类编写的 YAML 自然语言指令流，由 AI 动态解析并执行点击、输入与双向数据断言，自带三层递进式语义自愈机制。
   - **实体二：探索者 (ExplorerAgent)**
     - 对应工作流 ② **【自主混沌探索 (Exploration)】**：输入一句话宏观目标，采用 **Planner-Worker (规划者-执行者) 双层架构**自主游走找深层 Bug，动态绘制拓扑树并沉淀回归用例。
     - 对应工作流 ③ **【全量二级菜单冒烟巡检 (Smoke Tour)】**：单次启动 Electron 进程，由 ExplorerAgent 驱动流水线式依次遍历 6 大一级模块下的全部 **33 个二级业务菜单**，完成两级跳转验证与页面宏观视觉健康度体检，零重启极速巡检全屏。
2. **长短期记忆机制与断点续跑 (Checkpoint Memory)**：在探索模式下，内置短期防死循环记忆（规避局部无意义重复）与全局长效记忆（记录已访问的模块与熔断目标）。记忆实时持久化在 `reports/runs/<run_id>/checkpoint/` 中，支持通过 `--resume-from` 跨批次断点续跑，彻底避免 AI 走回头路。
3. **降维打击复杂大屏与黑盒渲染**：传统 API 拦截无法校验 Canvas/UE 图表渲染是否正确，传统 DOM 定位无法穿透黑盒。本框架通过 AI“看图”与底层数据双重校验，既能比对图表形态、重叠与白屏问题，又能严格核对渲染数值。
4. **超强自我容错与网络重试**：脱离底层 `class` 与 `id` 的绑定，不仅能应对前端组件重构，还具备底层大模型请求的防超时/断网自动重试恢复能力。
5. **智能视觉等待 (Intelligent Visual Wait)**：彻底抛弃低效的“死等(sleep)”，支持传入自然语言条件（如“等待左侧菜单树渲染完毕”），由 AI 轮询屏幕直到满足条件，将启动与跳转的空耗延迟降至最低。
6. **全自动零配置接口校验 (Auto-API Assertion)**：独创的底层静默抓包与大模型视觉双重比对机制。无需配置任何接口 URL 或抽取规则，框架在后台维护滑动网络数据池。只需一句自然语言，大模型即可自主从底层 JSON 中提取数据，并与 UI 渲染的文字、图表进行深度交叉验证。
7. **动态组件拓扑树与双图状态跃迁 (Post-Click Diff & Component Awareness)**：
   - **Post-Click Diff 双图差分**：每次点击前后抓取屏幕快照与 DOM 状态，通过“DOM 模态监听 + PIL 图像差分”双擎，毫秒级判定当前是打开弹窗（压栈）、关闭弹窗（出栈）、页面跳转还是局部刷新。
   - **Component Awareness 组件感知**：自动识别控件类型（🔲 按钮、📝 输入框、🔽 下拉框、☑️ 勾选框、📋 列表、🗺️ 地图等）及其所属的父容器。
   - **不变骨架延伸基座**：严格基于 `docs/explore_rules.md` 中的 6 大一级模块与 33 个二级业务菜单作为全局不可变底座，定点延伸已探索页面的内部组件。
   - **纯 Markdown 拓扑树大纲**：实时生成结构化的大纲树并附带 Mermaid 图，同步更新至 `docs/auto_page_map.md`。
   - **自动版本快照机制**：每次持久化前自动在 `artifacts/topology/snapshots/` 备份快照，彻底防止大模型幻觉污染历史基线，支持随时回滚。
8. **用例隔离与晋升机制 (Case Isolation & Promotion)**：探索模式沉淀的 YAML 测试脚本自动保存在每次运行专属的 `reports/runs/<run_id>/generated_cases/` 目录下，彻底杜绝未经人工核验的探索脚本污染正式回归用例库 `test_cases/`；确认高质量后可人工晋升（Promote）。
9. **智能自愈与前置补救 (Semantic Self-Healing)**：内置“三层防线”自愈机制。当物理重试耗尽时，AI 调取案发现场截图分析失败根因，自动给出点击前置 Tab、收起遮挡层或滚动查找等补救动作，实现无人值守的自我修复。
10. **解耦式缺陷闭环与大模型查重 (Auto Bug Reporting & Deduplication)**：深度集成完全解耦的 `BugReporter` 模块。当执行或探索发现控制台异常或断言失败时，案发现场大图与报错 JSON 物理收敛至本次运行目录，并调用大模型进行语义特征查重，在 `artifacts/bugs/` 下自动生成全局去重 JSON 数据库，并可一键生成全量交互式 Web 门户。
11. **资产与产物分层治理 (Tiered Lifecycle Architecture)**：
    - **长期核心资产 (`artifacts/`)**：仅包含全局 Bug 知识库、拓扑基线与用例归档，体积不足 1 MB，绝不因清理日志误删。
    - **单次运行工作区 (`reports/runs/<run_id>/`)**：一次运行对应一个唯一文件夹，包含专属日志、检查点记忆、缺陷证据与探索用例。
12. **安全瘦身与磁盘生命周期管理工具 (`utils/cleaner.py`)**：内置专业的磁盘大盘诊断与清理工具，可一键释放数十 GB 的临时过程截图，同时**100% 绝对保护**所有的 Bug 现场截图、记忆检查点与日志。

---

## 🏗️ 核心架构

框架采用 **感知 -> 决策 -> 执行** 的 ReAct 闭环：
1. **底座层 (Playwright over CDP)**：负责通过远程调试端口直连 Electron 进程，执行全屏截图、**交互式 DOM 树特征抽取**、**网络 API 接口静默拦截**，并根据指令精准模拟鼠标物理动作。
2. **大脑层 (Vision Agent)**：底层中枢神经基建。接收上下文指令、当前截图、压缩版 DOM 树以及最近的 API JSON 包，利用多模态大模型强大的推理能力，精准映射目标 UI 元素或执行深度业务双重断言。
3. **编排层 (两大业务智能体实体)**：
   - **执行者 (ActionRunner)**：串行解析 YAML 自然语言用例，调度大模型精准执行步骤并处理三层异常自愈（对应工作流 ① 确定性回归）。
   - **探索者 (ExplorerAgent)**：基于 Planner-Worker 双层设计，自主分解目标游走挖掘深层 Bug，动态渲染全景架构树并沉淀回归用例（对应工作流 ② 自主探索 与 工作流 ③ 全量二级菜单冒烟巡检）。

---

## 📂 规范目录结构

```text
electron_ai_vision/
├── config.yaml            # 全局环境基础配置 (应用路径、LLM配置、视口尺寸等)
├── .env                   # 敏感环境变量 (如 LLM_API_KEY, 严防泄露)
├── config/                # 框架配置模块
│   └── settings.py        # 环境变量与 YAML 配置文件的读取与合并
├── core/                  # 框架底层核心驱动
│   ├── action_runner.py   # [用例引擎] 解析 YAML 自然语言步骤，调度底层执行与三层自愈
│   ├── bug_reporter.py    # [缺陷闭环] 完全解耦的智能缺陷记录与大模型语义查重模块
│   ├── browser/           # [驱动层] 封装 Electron 启动、CDP 连接与底层数据抓取
│   │   ├── driver.py            # 核心生命周期管理与鼠标键盘物理动作模拟
│   │   ├── dom_extractor.py     # Hybrid DOM 元素提取器 (集成 Component Awareness)
│   │   ├── network_monitor.py   # 底层 API 静默抓包池与网络/控制台报错监控
│   │   └── screenshot.py        # 截图裁剪与 Base64 预处理
│   ├── explorer_agent/    # [探索层] 混沌探索者智能引擎
│   │   ├── agent.py             # ReAct Planner-Worker 循环调度引擎 (维护容器调用栈与记忆)
│   │   ├── post_click_diff.py   # [状态跃迁] 点击前后双图与 DOM 差分探测器
│   │   ├── page_map_builder.py  # 纯 Markdown 组件拓扑树生成、Mermaid 渲染与版本快照
│   │   └── trajectory_exporter.py # 操作轨迹结构化记录与 YAML 用例自动生成
│   └── vision/            # [感知层] 视觉大模型连接层
│       ├── agent.py             # 封装多模态大模型 API 请求与 JSON 结果解析
│       └── prompts.py           # 集中管控所有 AI System Prompts (速查文档头管理)
│
├── artifacts/             # 💎 【长期持久资产区】轻量核心数据 (~200KB)，永久保留防误删
│   ├── bugs/                    # 全局去重缺陷大盘总库 (global_bugs.json)
│   ├── topology/                # 全局架构树基线 (global_page_tree.json, auto_page_map.md)
│   │   └── snapshots/           # 拓扑历史版本快照备份 (带时间戳，防模型幻觉改坏)
│   └── archived_cases/          # 历史探索闭环自动生成的测试用例归档
│
├── reports/               # 📦 【运行时产物收敛区】一次运行 = 一个独立完整目录
│   └── runs/<run_id>/           # 单次运行工作区
│       ├── run.log              # 本次运行完整日志
│       ├── checkpoint/          # 检查点记忆 (global_history.json, failed_counts.json)
│       ├── bugs/                # 本次捕获的缺陷凭证 (现场大图 + 报错 JSON)
│       ├── screenshots/         # 过程临时大图 (背景熄灯图、过渡图，可通过 cleaner 安全清理)
│       └── generated_cases/     # 本次探索闭环生成的 YAML 脚本 (隔离保存，避免污染用例库)
│
├── docs/                  # 文档与只读规范区
│   ├── explore_rules.md   # 探索模式基础骨架 (6大模块+33个业务菜单) 与业务规矩
│   └── auto_page_map.md   # 动态组件架构拓扑实时预览镜像 (纯 Markdown 树 + Mermaid 图)
│
├── test_cases/            # 📝 【正式回归用例库】原则上仅存放人工确认的基线用例
│   ├── README.md                # 用例编写与晋升规范
│   ├── test_home_cert.yaml      # 证照管理回归用例
│   ├── test_home_mine_intro.yaml# 矿山简介回归用例
│   └── test_roam_only.yaml      # 3D 漫游巡检用例
│
├── utils/                 # 通用基础设施工具
│   ├── paths.py           # 统一产物路径与生命周期管理器
│   ├── report_generator.py# 离线交互式测试报告(HTML)单次运行生成器
│   ├── report_hub.py      # 全量巡检与大盘门户服务引擎
│   ├── cleaner.py         # 磁盘存储大盘诊断与安全瘦身维护工具
│   ├── logger.py          # 框架集中日志管理，支持 Unicode 防乱码与彩色输出
│   └── electron_launcher.py # Electron 进程管理辅助工具
│
├── requirements.txt       # Python 依赖清单
└── main.py                # 项目启动主入口，执行全量巡检、单条测试或自主探索
```

---

## 🚀 快速上手 (Quick Start)

### 1. 运行 33 个二级菜单全量冒烟巡检 (Smoke Tour)
单次启动客户端，零重启极速巡检全屏 33 个二级菜单：
```powershell
python main.py --smoke
```

### 2. 运行预设 YAML 业务巡检用例
```powershell
# 运行单一自然语言用例
python main.py --case test_cases/test_home_mine_intro.yaml

# 运行 test_cases/ 下的所有正式回归用例
python main.py --all

# 指定智能视觉等待就绪条件 (AI 轮询截屏直至就绪)
python main.py --case test_cases/test_home_mine_intro.yaml --wait-ready "主界面左侧菜单树和右侧面板渲染完成"
```

### 3. 启动自主探索与架构生成 (ExplorerAgent)
```powershell
# 在指定模块下自主探索 20 步，自动寻找深层 Bug 并更新架构拓扑树
python main.py --explore "在智控管理模块下自主探索智能通风与供配电" --max-steps 20

# 继承历史记忆进行断点续跑
python main.py --explore "继续探索设备管理" --resume-from explore_20260924_175815

# 强制重新探索某个业务模块 (清空该模块历史子树，展开全新探索)
python main.py --explore "重新探索智能通风" --reexplore
```

### 4. 磁盘大盘诊断与安全瘦身工具
```powershell
# 查看当前工程产物存储分布大盘 (全局资产、运行产物、临时截图占比)
python utils/cleaner.py --info

# 安全瘦身：清理 7 天前的临时过程大图 (永久保留 Bug 崩溃现场大图与记忆检查点)
python utils/cleaner.py --retain-days 7

# 清理旧版历史残余目录 (释放数十 GB 冗余磁盘)
python utils/cleaner.py --clean-legacy
```

### 5. 启动测试全景大盘门户
```powershell
# 自动合并所有历史运行数据并启动本地 Web 门户 (默认端口 8080)
python utils/report_hub.py --serve
```

---

## 📊 产出物查阅指南

- **动态全景 UI 架构树**：直接在编辑器中预览打开 [`docs/auto_page_map.md`](docs/auto_page_map.md)（或资产主库 [`artifacts/topology/auto_page_map.md`](artifacts/topology/auto_page_map.md)），查看层级分明的组件拓扑大纲与 Mermaid 图。
- **全局缺陷与测试大盘**：执行 `python utils/report_hub.py --serve`，并在浏览器中访问 `http://localhost:8080`，查看经过大模型语义查重后的全局缺陷总览、按运行批次划分的完整步骤快照、以及交互式的全景图表报告。
- **单次运行工作区**：在 `reports/runs/<run_id>/` 中可查阅当前次运行的完整控制台日志 (`run.log`)、案发现场证据 (`bugs/`)、交互式离线报告 (`report.html`)、续跑检查点 (`checkpoint/`) 以及本次闭环生成的 YAML 用例 (`generated_cases/`)。
- **用例晋升**：若某次探索闭环生成的 YAML 用例业务价值高且运行稳定，可将其从 `reports/runs/<run_id>/generated_cases/` 复制并重命名至 `test_cases/`，正式纳入自动化回归体系。