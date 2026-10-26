# 📖 Electron AI Vision 纯视觉 UI 自动化巡检框架使用手册

本项目是一个专门针对复杂 Electron 桌面端（矿山大屏、3D/UE 数字孪生、高频业务看板、数字看板）设计的**多模态 AI 驱动 UI 自动化测试巡检框架**。

彻底告别传统的 Page Object Model (POM) 模式与脆弱易碎的 XPath/CSS/ID 硬编码选择器，用纯自然语言意图驱动，借助多模态视觉大模型（如 Qwen-VL / GPT-4o）实现桌面端大屏的**“感知、规划、物理操作与双向数据断言”**。

---

## 目录
- [1. 首次使用环境准备 (Getting Started)](#1-首次使用环境准备-getting-started)
- [2. 配置文件全项详解与默认配置 (Configuration)](#2-配置文件全项详解与默认配置-configuration)
- [3. 核心功能全景 (Core Capabilities)](#3-核心功能全景-core-capabilities)
- [4. 大屏双翼与 3D/UE 伴生防御防线 (Protection & Robustness)](#4-大屏双翼与-3due-伴生防御防线-protection--robustness)
- [5. 常用运行命令速查 (CLI Cheat Sheet)](#5-常用运行命令速查-cli-cheat-sheet)
- [6. 禅道缺陷双向同步与自动提单 (ZenTao Integration)](#6-禅道缺陷双向同步与自动提单-zentao-integration)
- [7. YAML 自然语言用例编写指南 (YAML Specification)](#7-yaml-自然语言用例编写指南-yaml-specification)
- [8. 测试资产与大盘门户查阅 (Reports & Dashboard)](#8-测试资产与大盘门户查阅-reports--dashboard)

---

## 1. 首次使用环境准备 (Getting Started)

### 1.1 系统要求
- **操作系统**：Windows 10 / Windows 11 (64-bit)
- **Python 版本**：Python 3.10 及以上（推荐 3.10 或 3.11）
- **显卡/网络**：能正常启动运行被测 Electron 客户端及 3D/UE 伴生引擎，且能正常访问视觉大模型 API 服务。

### 1.2 源码克隆与虚拟环境创建
建议在独立的虚拟环境中安装运行，以避免包依赖冲突：

```powershell
# 1. 进入项目根目录
cd d:\Auto\electron_ai_vision

# 2. 创建 Python 虚拟环境 (.venv)
python -m venv .venv

# 3. 激活虚拟环境 (Windows PowerShell)
.\.venv\Scripts\Activate.ps1
```

### 1.3 安装核心依赖
激活虚拟环境后，安装框架所需的基础依赖以及底座外设：

```powershell
# 1. 安装核心 Python 依赖包 (Playwright, PyAutoGUI, Pillow, PyYAML 等)
pip install -r requirements.txt

# 2. 安装 Playwright 底座外设依赖
playwright install chromium
```

---

## 2. 配置文件全项详解与默认配置 (Configuration)

### 2.1 首次运行必改项 Checklist（拉取代码后必须配置）
使用者拉取代码后，**仅需核对并修改以下 2 处配置**即可一键跑通：

1. **配置大模型密钥 (`.env`)**：
   在工程根目录创建或编辑 `.env` 文件，填入视觉大模型的 API Key：
   ```ini
   # 必填：用于调用多模态视觉大模型 (默认使用阿里百炼 DashScope 兼容接口)
   LLM_API_KEY=sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
   ```
2. **配置客户端本地可执行路径 (`config.yaml`)**：
   打开 `config.yaml`，确认对应项目的 `exe_path` 是否为您电脑上的真实绝对路径：
   ```yaml
   active_app: "zhaiwan"   # 激活的项目
   apps:
     zhaiwan:
       exe_path: "D:\\LargeScreen\\zhaiwan2\\project\\se-launcher-zhaiwan\\se-launcher-zhaiwan.exe"  # 👈 改为你本地的真实安装路径
   ```

---

### 2.2 默认配置速查表 (Default Settings)

框架开箱即附带针对大屏场景优化的高稳定性默认参数：

| 配置项 | 所在文件 | 默认值 | 作用与含义说明 |
| :--- | :--- | :--- | :--- |
| `active_app` | `config.yaml` | `"zhaiwan"` | 当前激活测试的应用方案（如 `zhaiwan` 寨湾 或 `liwutong` 里伍铜） |
| `debug_port` | `config.yaml` | `9223` | Electron 远程 CDP 调试通信端口（启动时通过 `--remote-debugging-port=9223` 挂载） |
| `viewport` | `config.yaml` | `2560 x 1440` | 默认渲染视口尺寸，专为 2K/4K 大屏高保真呈现设计 |
| `device_pixel_ratio` | `config.yaml` | `1.5` | 高分屏 DPI 缩放比，确保坐标换算与物理像素点 1:1 严格对齐 |
| `start_delay` | `config.yaml` | `15.0 秒` | 应用启动后的物理等待缓冲时间，确保三维引擎与前端数据完全加载 |
| `llm.provider` | `config.yaml` | `"openai"` | 大模型通信协议格式（使用通用 OpenAI 兼容协议） |
| `llm.model` | `config.yaml` | `"qwen3-vl-plus"` | 默认多模态视觉大模型（兼具高精度 OCR、图表数值抽取与低推理延迟） |
| `llm.base_url` | `config.yaml` | `阿里云百炼 DashScope` | 默认服务请求接口地址 |
| `llm.temperature` | `config.yaml` | `0.1` | 模型采样温度，采用极低温度以确保坐标预测和数据断言的稳定性 |
| `env_check.enabled` | `config.yaml` | `true` | 前置环境准入巡检，启动前自动核验目标后台接口环境（防测试环境串味） |

---

### 2.3 配置文件详细结构说明

#### `config.yaml` 核心结构
```yaml
active_app: "zhaiwan"   # 极简无感秒切：直接修改为 "zhaiwan" 或 "liwutong"

apps:
  zhaiwan:
    exe_path: "D:\\LargeScreen\\zhaiwan2\\project\\se-launcher-zhaiwan\\se-launcher-zhaiwan.exe"
    rules_file: "docs/explore_rules_zhaiwan.md"  # 业务菜单基准与探索规则
    debug_port: 9223                             # CDP 端口
    ue_process_name: "zhaiwan.exe"               # 伴生 UE 进程名 (监控其存活)
    expected_page_url: "main.html"               # 目标大屏 URL 关键字
    expected_page_title: "主界面"                 # 目标大屏标题关键字
    startup_timeout: 40.0                        # 启动跃迁超时(秒)
    start_delay: 15.0                            # 首屏稳定缓冲(秒)
    viewport:
      width: 2560
      height: 1440
      device_pixel_ratio: 1.5
    env_check:
      enabled: true                              # 启用前置环境准入校验
      expected_env: "prod"                       # 期望环境: "prod" 或 "test"
      strict: true                               # 环境不符时直接阻断退出
      environments:
        prod: "http://221.234.48.197:8808"
        test: "http://121.43.58.203:8783"

llm:
  provider: "openai"
  api_key: ""                                    # 留空，通过 .env 读取防泄露
  base_url: "https://dashscope.aliyuncs.com/compatible-mode/v1"
  model: "qwen3-vl-plus"
  timeout: 60                                    # 单次推理超时保障(秒)
  temperature: 0.1

reports:
  dir: "reports"
  feishu_webhook: "https://open.feishu.cn/..."   # 飞书群机器人推送地址 (可选)
  feishu_secret: "..."                           # 飞书机器人安全密钥 (可选)
  report_base_url: "http://192.168.1.156"        # 局域网访问基础地址 (如 IIS 服务)
```

---

## 3. 核心功能全景 (Core Capabilities)

框架突破传统自动化模式，构建了“确定性回归”与“自主黑客探索”双引擎：

1. **🎬 确定性用例回归 (ActionRunner)**：
   - 严格按照人类编写的自然语言 YAML 指令流逐步执行；
   - 支持纯视觉点击、文本输入、视觉语义断言与后台 API 双向交叉比对；
   - 内置**三层语义自愈机制**（遇到遮挡、未展开或微偏时，AI 自动进行前置补救与重试）。

2. **🚀 全量二级业务菜单冒烟巡检 (Smoke Tour)**：
   - 单次启动 Electron 客户端，流水线式自动化遍历当前激活项目规则库 (`rules_file`) 中定义的**全量主模块与二级业务菜单**（例如寨湾项目的 6 大主模块/33 个二级菜单，或里伍铜项目的全量专属菜单）；
   - 零重启、零误触，极速完成所有菜单的两级路由跃迁与页面核心业务组件宏观体检。

3. **🕵️ 自主混沌探索与深挖 (ExplorerAgent)**：
   - 采用 **Planner-Worker (规划统帅-执行单兵)** 双层架构；
   - Planner 纵览全局，基于历史记忆与业务骨架分解出短期战术子目标并分配预算步数；
   - Worker 负责单兵落地与连续交互，探索深层弹窗、抽屉面板与未测盲区；
   - **智能防死锁与双门限停止机制**：满足 `--max-steps`（最大步数）或 `--max-times`（最大时间）任一条件即停，若架构已 100% 覆盖则触发 **Smart Early Stop** 提前优雅收工。

4. **🔍 全自动零配置接口核验 (Auto-API Assertion)**：
   - 底层静默维护最新 25 个网络报文的滑动窗口；
   - 截图中肉眼看到的指标数值（如“当前出矿量 3200 吨”）自动与后台拦截到的真实 JSON 原文字段双向比对，防范前端数据张冠李戴。

5. **🧊 智能防假死检测 (Freeze Check)**：
   - 专为 3D 场景与动态大屏设计；
   - 毫秒级抓取时序双图进行差分运算，精准判定三维推流引擎是否冻结卡死、动画跑马灯是否停滞。

6. **🐞 智能缺陷闭环与语义查重 (BugReporter)**：
   - 当执行失败或捕获底层报错时，自动隔离现场大图并生成 JSON 档案；
   - 归档前调用大模型与全局缺陷库进行**语义查重**，同类本质问题自动合并并累加复现频次，从源头解决 Bug 泛滥去重难题。

7. **🗺️ 动态架构拓扑测绘与用例反哺**：
   - 探索过程中动态推断当前 UI 路径（如 `安全管理 -> 人员安全档案`）；
   - 自动生成结构化的 Markdown 架构树与 Mermaid 图；
   - 将走通的高价值探索路径自动编译输出为确定性的 `.yaml` 回归测试用例。

---

## 4. 大屏双翼与 3D/UE 伴生防御防线 (Protection & Robustness)

面对数字孪生矿山大屏“3D 引擎 WebRTC 像素流 + 2D 高频业务交互看板”的极端特殊架构，框架构建了三道物理级防线与一套高精证据溯源链：

### 4.1 物理级防线：严禁网页刷新，誓死捍卫 UE 像素流
- **背景痛点**：传统自动化工具在遇到未知卡顿时习惯执行 `page.reload()`。但在 WebRTC 像素流推流架构下，网页刷新会强行切断与 UE 伴生引擎的 WebRTC 信令握手通道，导致后台 UE 渲染服务直接断流甚至崩溃。
- **底层防御**：框架在 CDP 底层驱动层（`driver.py`）**物理抹除/拦截所有刷新调用**，即使测试指令误触 reload，也会自动安全降级为安全的页面回退或组件跳转，杜绝因刷新导致的伴生进程瓦解。

### 4.2 侧边栏常开防线：物理拦截“一键隐藏”
- **背景痛点**：大屏左右两侧常驻的 2D 业务数据面板是核心巡检载体。若 AI 误点击“一键隐藏/收起”按钮，界面将失去两翼看板，陷入纯 3D 画布的空转死循环。
- **底层防御**：在 `ExplorerAgent` 决策与执行单兵（`worker.py`）中注入硬编码物理拦截墙，一旦模型规划中出现“一键隐藏”、“收起面板”、“foldbar”等意图，底层机械臂直接拒绝执行，确保业务数据看板永久展开。

### 4.3 极端死锁自愈机制：启动器安全冷重启 (`restart_app`)
- **自愈逻辑**：若三维大屏因底层渲染异常或弹窗不可达造成 AI 连续 3 轮以上卡死停滞，框架自动触发**优雅冷重启**自愈：
  1. 通过 Windows 核心 API 向 Electron 进程发送 `WM_CLOSE` 信号，让主进程与伴生 UE5 进程有序安全退出（杜绝 `taskkill /F` 导致的 GPU 显卡驱动蓝屏）；
  2. 智能轮询等待 CDP 9223 端口安全释放；
  3. 重新拉起应用启动器并重新挂载 CDP 调试管道，恢复探索现场，实现真正意义上的无人值守。

### 4.4 4 级案发现场高精证据定位链
框架在记录 Bug 与上报缺陷时，遵循严谨的 4 级证据回溯链，杜绝因定时轮询造成的“延迟截图不对应”问题：
1. **Level 1 (首选)**：`_roi.png` —— 案发瞬间的高精局部裁剪切片（毫秒级锁定告警图表或异常数据）；
2. **Level 2**：`bugs/<id>.png` —— 案发现场全局大图；
3. **Level 3**：`bugs/<id>_HHMMSS.png` —— 缺陷复现时序抓拍图；
4. **Level 4**：`screenshots/hover_step_*.png` —— 鼠标悬浮气泡/Tooltip 触发瞬态图。

---

## 5. 常用运行命令速查 (CLI Cheat Sheet)

所有模式均通过项目主入口 `main.py` 及 `utils/` 工具集驱动：

### 5.1 全量二级菜单极速冒烟巡检 (Smoke Tour)
```powershell
# 单进程快速巡检当前项目定义的全部二级业务菜单（推荐日常版本发布前快速排查）
python main.py --tour
# 或使用别名
python main.py --smoke
```

### 5.2 运行确定性 YAML 业务回归用例
```powershell
# 1. 运行单一自然语言用例
python main.py --case test_cases/test_home_mine_intro.yaml

# 2. 批量运行 test_cases/ 目录下的所有正式回归用例
python main.py --all

# 3. 带全局报错忽略（即使中间某步失败也强制跑完全流程）
python main.py --case test_cases/test_home_mine_intro.yaml --ignore-errors

# 4. 指定智能视觉等待（AI 轮询等待画面特定自然语言特征出现，替代死等）
python main.py --case test_cases/test_home_mine_intro.yaml --wait-ready "主界面左侧菜单树和右侧面板完全渲染完成" --wait-timeout 60.0
```

### 5.3 开启自主黑客式探索 (ExplorerAgent)
```powershell
# 1. 发起地毯式探索（限定 20 步，默认快速试跑）
python main.py --explore "地毯式探索全系统，遍历所有一级与二级菜单，重点寻找白屏与崩溃" --max-steps 20

# 2. 无人值守长效深度探索（设定上限 2000 步或 840 分钟，挂载业务规则库）
python main.py --explore "开启全栈地毯式扫荡：深度遍历所有的顶级菜单与二级业务菜单，测试图表与深层弹窗" --max-steps 2000 --max-times 840 --ignore-errors --explore-context docs/explore_rules_zhaiwan.md

# 3. 继承历史记忆进行断点续跑 (避免走回头路)
python main.py --explore "继续深度探索设备管理模块" --resume-from reports/runs/explore_20261015_182652

# 4. 强制重新探索某个指定模块 (清空该模块子树重新深挖)
python main.py --explore "重新探索智能通风模块" --reexplore "智能通风"
```

### 5.4 禅道缺陷双向同步与管理 (ZenTao Sync)
```powershell
# 1. 查看本地 Bug 知识库待提单与已绑定状态
python utils/zentao_sync.py --status

# 2. 提交指定缺陷至禅道（自动提取高精快照并嵌入富文本，智能指派研发责任人）
python utils/zentao_sync.py --submit-bug BUG-20261025-005

# 3. 一键批量同步所有待提单缺陷
python utils/zentao_sync.py --sync-all

# 4. 重新同步并刷新指定缺陷的富文本内容与快照截图
python utils/zentao_sync.py --update-bug BUG-20261025-005

# 5. 手动双向绑定本地缺陷编号与已有禅道 Bug ID
python utils/zentao_sync.py --bind BUG-20261024-001 1157
```

### 5.5 启动统一测试大盘与缺陷知识库门户
```powershell
# 1. 仅重新构建静态大盘数据 (编译生成 index.html 与 runs_data.js)
python utils/report_hub.py --build

# 2. 启动常驻 Web 服务 (默认监听 8080 端口，局域网与外网均可实时访问)
python utils/report_hub.py --serve --port 8080
```

### 5.6 磁盘空间诊断与安全清理瘦身 (Cleaner)
长期进行高频截图测试会占用较多磁盘，工具提供**100% 保护 Bug 现场证据**的安全瘦身：
```powershell
# 1. 诊断查看当前工程磁盘分布（核心资产、运行产物、临时大图占用）
python utils/cleaner.py --info

# 2. 安全瘦身：清理 7 天前的临时过渡截图（永久保留所有 Bug 案发现场大图与检查点）
python utils/cleaner.py --retain-days 7
```

---

## 6. 禅道缺陷双向同步与自动提单 (ZenTao Integration)

框架内置了完全解耦的企业级禅道敏捷协同工具 (`utils/zentao_sync.py`)，打通本地 AI 缺陷库与团队研发管理看板之间的最后一公里：

### 6.1 核心黑科技特性
1. **📸 富文本案发现场高精快照内嵌 (Base64 Inline)**：
   - 提取案发瞬间的局部高精切片 (`_roi.png`) 或现场截图，自动完成保真压缩并转为 Base64 编码，直接以 `<img src="data:image/jpeg;base64,..."/>` 形式嵌入禅道复现步骤的富文本正文中；
   - 禅道服务端自动将其无缝解析为正文图片，研发人员打开禅道缺陷单即可直观看到红框告警或数据切片，**无须手动下载外部附件**，大幅提升协作排查效率。
2. **🎯 智能研发分派路由 (Smart Routing)**：
   - 基于缺陷分类与业务场景特征，自动精准指派对应的研发工程师：
     - **前端大屏与 UI 交互类缺陷**（如卡死、白屏、错位、样式崩溃）：自动分配给前端负责人（如 `chenyixiong` 陈贻雄）；
     - **后端接口与数据计算类缺陷**（如指标偏差、双向断言失败、物理数值违背）：自动分配给后端负责人（如 `meibenxia` 梅本霞）。
3. **🔗 智能双向绑定与自动去重**：
   - 每次提交成功后，禅道系统生成的官方编号（如 `#1160`）会自动反向回写至本地全局 Bug 库（`artifacts/bugs/global_bugs_<app>.json`）的 `zentao_id` 字段中；
   - 本地状态自动跃迁为 `submitted`（已提单），防止多轮探索时重复向禅道提单，实现资产闭环。
4. **🛡️ 局域网代理穿透**：
   - 客户端底层自动禁用系统/全局代理环境（`trust_env=False`），杜绝开发人员开启科学上网工具时局域网禅道服务器请求超时的痛点。

---

## 7. YAML 自然语言用例编写指南 (YAML Specification)

用例统一存放在 `test_cases/` 目录下，文件格式为 `.yaml`。框架支持以下 13 种核心交互与校验指令：

### 7.1 标准动作词汇表
| 动作指令 (`type`) | 适用场景 | 常用参数示例 | 行为说明 |
| :--- | :--- | :--- | :--- |
| `action` | 点击与定位 | `prompt: "点击左侧企业简介"` | AI 视觉定位元素物理中心并触发真实鼠标点击 |
| `input` | 键盘文本输入 | `prompt: "在搜索框输入", text: "一号风机"` | 聚焦目标输入框并输入指定字符 |
| `zoom` | 3D视界滚轮缩放 | `direction: "in"`, `steps: 3` | 在三维场景中心连续滚动鼠标滚轮放大/缩小视口 |
| `rotate_3d` | 3D视界漫游旋转 | `direction: "left"`, `distance: 250` | 按住鼠标右键平滑旋转三维场景镜头视角 |
| `scroll` | 容器/列表翻页滚动 | `direction: "down"`, `delta: 300` | 对长表格、告警列表、侧边栏进行局部滚动 |
| `slide` | 时间轴与阈值滑块 | `direction: "right"`, `distance: 120` | 按住滑块进行连续平滑拖拽调节 |
| `drag` | 视口平移与拖拽 | `prompt: "拖动视口"` | 鼠标按下并平移指定位移 |
| `assert` | 纯视觉语义断言 | `prompt: "确认弹窗是否显示"` | 多模态大模型判定画面语义是否符合预期 |
| `api_assert` | 数据双向交叉校验 | `prompt: "核对风机效率与接口数据"` | 将截图 OCR 数值与拦截到的后台 JSON 原文双向比对 |
| `wait_for` | 智能视觉轮询等待 | `prompt: "等待三维模型加载完毕"`, `timeout: 30` | 持续轮询画面特征直至达标或超时 |
| `wait` | 物理强制等待 | `seconds: 5.0` | 强制休眠指定秒数 |
| `freeze_check` | 动态防假死检测 | `prompt: "检查三维场景是否卡死"` | 双图时序毫秒差分比对，检测画面流动画质 |
| `back` | 路由历史回退 | - | 执行浏览器后退或返回上一级看板 |
| `reload` | **【已废弃/严禁使用】** | - | 严禁调用！会导致 WebRTC 断流及 UE5 崩溃 |

### 7.2 完整范例用例 (`test_sample.yaml`)
```yaml
name: "矿山简介与核心指标巡检"
description: "验证矿山简介基础面板切换、3D 漫游启动以及最新核实资源量接口数据一致性"

steps:
  # 1. 初始物理等待或视觉等待
  - type: wait
    seconds: 5

  # 2. 模拟物理点击操作 (纯自然语言描述意图，禁用 CSS/XPath)
  - type: action
    prompt: "在画面左侧信息面板顶部，点击紧挨着'企业简介'右侧的'平台介绍'文本标签。"

  # 3. 纯视觉断言
  - type: assert
    prompt: "检查左侧面板顶部的标签文本，确认原本的'平台介绍'是否已经成功切换为'入井须知'。"

  # 4. 全自动接口数据交叉比对 (Auto-API)
  - type: api_assert
    prompt: "在画面右侧寻找'最新核实资源量'面板，提取其中各项指标数值，核对这些数值是否与底层接口 'getFdaConfigByKey' 响应的 JSON 原始数据完全一致。"

  # 5. 3D 动态防假死校验
  - type: freeze_check
    prompt: "检测当前 3D 漫游画面是否处于流动播放状态，严禁出现三维场景卡死或静止白屏。"
```

---

## 8. 测试资产与大盘门户查阅 (Reports & Dashboard)

框架实行严格的**“长期核心资产”与“单次运行产物”分层治理**架构：

```text
electron_ai_vision/
├── artifacts/             # 💎 【长期持久资产区】（体积极小，永久保护）
│   ├── bugs/
│   │   └── global_bugs_<app>.json   # 应用专属全局缺陷知识库（去重后合并的权威 Bug 库，含禅道 ID 映射）
│   └── topology/
│       ├── snapshots/               # 带项目前缀的版本快照库 (page_tree_<app>_*.json)
│       └── global_page_tree_<app>.json # 应用专属全局架构拓扑底座 (单一真理源)
│
├── reports/
│   └── runs/              # 📦 【单次运行工作区】
│       ├── index.html         # 统一自动化测试全景大盘
│       ├── runs_data.js       # 全局大盘数据源
│       └── <run_id>/          # 单次运行目录 (如 explore_20261015_182652)
│           ├── report.html        # 该次运行专属的高颜值交互式离线报告
│           ├── bugs/              # 该次运行捕获的 Bug 现场大图与元数据
│           ├── checkpoint/        # 该次运行的长短期记忆检查点
│           └── generated_cases/   # 该次运行自动闭环沉淀的 YAML 用例
│
└── utils/                 # 🛠️ 【配套工程效能工具箱】
    ├── cleaner.py             # 磁盘空间诊断与安全瘦身工具（100% 保护 Bug 现场证据）
    ├── report_hub.py          # 统一测试大盘构建器与本地/局域网 Web 服务器
    └── zentao_sync.py         # 禅道缺陷双向同步、现场截图内嵌与自动提单工具
```

### 8.1 查看可视化全景大盘
启动服务后访问 `http://localhost:8080`：
1. **历史巡检记录模块**：查看历次探索与回归的耗时、实际执行步数、缺陷发现数及各页面覆盖率；
2. **全局缺陷知识库模块**：
   - **模式筛选**：自主探索 / 冒烟测试 / 回归测试；
   - **状态筛选**：激活 / 已解决 / 已提单 / 已关闭 / 误报；
   - **全字段模糊检索**：毫秒级支持按缺陷单号 (`BUG-xxx`)、RUN ID、业务路径 (`安全管理 -> xxx`)、目标描述、异常详情模糊搜索；
   - **弹窗详情与原地编辑**：点击查看现场对比大图，支持直接原地保存复盘分析结论与关闭原因。

### 8.2 用例晋升机制 (Case Promotion)
当在 `reports/runs/<run_id>/generated_cases/` 中发现某次探索自动生成的 YAML 用例业务价值极高且稳定走通时，只需将该文件复制至 `test_cases/` 目录下，即可直接纳为日常 CI/CD 的正式回归用例！