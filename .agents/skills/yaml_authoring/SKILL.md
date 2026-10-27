---
name: yaml_authoring
description: 矿山大屏自然语言 YAML 测试用例智能编写、规范注入与静态合规校验
---

# 矿山大屏自然语言用例专家 (YAML Authoring)

专为基于 Chromium + WebRTC 像素流的 Electron 矿山大屏应用打造的自动化测试用例编写与校验 Skill。本框架摒弃传统的 Page Object Model (POM) 与固定 DOM/XPath 选择器，采用自然语言意图驱动双擎（Hybrid DOM + 纯视觉降级）执行。

## 适用场景
- 用户提出：“*帮我写一个寨湾【智能通风】巡检的 YAML 用例*”
- 用户提出：“*将这段测试链路整理为正式回归用例*”
- 用户提出：“*帮我检查这个 test_xxx.yaml 用例写得合不合规*”

---

## 核心业务三大铁律（必须在用例中严格践行）

1. **UI 必须忠于 API (`api_assert`)**：
   - 界面上凡是展示关键指标（如带班领导人名、下井人数、瓦斯浓度、风机转速、供电负荷等），**必须使用 `api_assert`** 到底层拦截的 JSON 接口中核对，防范前端渲染张冠李戴。
2. **动态必须流动 (`freeze_check`)**：
   - 3D 视界、监控画面或动态跑马灯不能假死，必须在关键节点加入 `freeze_check` 进行双图时序对比防假死检测。
3. **数据不能违背物理常识**：
   - AI 自带业务防线，对异常数字（如几百万度电的瞬时功率、负下井人数）予以最高级别警报。

---

## 绝对红线禁令
- ❌ **严禁使用 `reload` / `refresh`**：在 WebRTC 像素流架构下，网页刷新会强行切断与 UE 信号服务器握手导致 UE 崩溃断流。
- ❌ **严禁点击“一键隐藏/收起”**：两翼 2D 业务面板必须保持展开，严禁点击折叠按钮导致界面陷入三维空转。
- ❌ **严禁写硬编码 DOM/XPath/CSS 选择器**：必须全部使用自然语言意图描述。

---

## 动作词汇表 (Action Types Reference)

| 动作类型 (`type`) | 必填参数 | 可选参数 | 场景说明 |
| :--- | :--- | :--- | :--- |
| `wait_for` | `prompt` | `timeout: 60`, `interval: 3` | 智能视觉轮询等待（通常用于首屏加载，如等待主标题出现） |
| `action` | `prompt` | - | 点击操作（优先提取 DOM，若 Canvas/三维黑盒无 DOM 则自动降级纯视觉点击） |
| `input` | `prompt` | `text`, `fuzz: false`, `clear_first: true`, `press_enter: false` | 文本输入框定位与键入（支持 fuzz 模糊测试） |
| `assert` | `prompt` | - | 纯视觉语义断言（如“确认弹窗是否出现”、“确认播放按钮是否变为暂停”） |
| `api_assert` | `prompt` | `target_api: "url_keyword"` | UI 渲染与底层 JSON 数据的双向交叉断言 |
| `freeze_check` | `prompt` | `wait_seconds: 5.0` | 双图时序对比防假死检测（检查时间变化或三维粒子） |
| `zoom` | `prompt` | `direction: "in"/"out"`, `steps: 3` | 三维场景/地图滚轮缩放 |
| `rotate_3d` | `prompt` | `direction: "left"/"right"/"up"/"down"`, `distance: 250`, `button: "right"` | 三维孪生视界漫游旋转 |
| `scroll` | `prompt` | `direction: "down"/"up"`, `delta: 300` | 告警列表、长表格容器的内部物理滚轮翻页 |
| `slide` | `prompt` | `start`, `end`, `start_x`, `start_y`, `end_x`, `end_y` | 时间轴（Timeline Slider）、阈值调节滑块拖拽 |
| `drag` | `from_x, from_y, to_x, to_y` | `button: "left"` | 物理坐标拖拽平移 |
| `wait` | `seconds: 2.0` | - | 物理强制缓冲等待 |
| `back` | - | - | 路由历史回退或返回上一级视图 |

---

## 编写范例

```yaml
name: "寨湾大屏【智能通风】深度巡检"
description: "覆盖通风系统主界面加载、风机启停状态断言、风速监测API双向比对及假死检测"

steps:
  # 1. 智能等待首屏加载
  - type: wait_for
    prompt: "画面正上方显示出'智能通风'二级标题，左侧树状结构已渲染完毕"
    timeout: 30

  # 2. 点击目标风机卡片（兼顾 DOM 与三维降级）
  - type: action
    prompt: "在画面左侧的风机设备列表中，点击'#1主通风机'选项卡。若列表中无对应 DOM，请降级视觉点击。"

  # 3. 缓冲并检测状态
  - type: wait
    seconds: 2
  - type: assert
    prompt: "检查中间设备看板，确认#1主通风机的运行状态是否显示为绿色'运行中'。"

  # 4. 接口数据一致性断言（铁律一）
  - type: api_assert
    prompt: "在画面右侧通风参数面板中，提取当前'实时风速'与'静压值'。前往最新拦截的 API 接口中核对底层数值与 UI 显示是否完全一致。"

  # 5. 防假死时序检测（铁律二）
  - type: freeze_check
    prompt: "观察风速波形图或右侧时间戳，确认 5 秒内数据流是否有动态更新"
    wait_seconds: 5.0
```

---

## 验证与落地流程
1. 用例编写完成后，必须保存在 `test_cases/` 目录下（如 `test_cases/test_ventilation.yaml`）。
2. 立即运行静态校验命令：
   ```bash
   python .agents/skills/yaml_authoring/scripts/validate_case.py test_cases/<your_case>.yaml
   ```
3. 校验通过后，告知用户可用以下命令直接执行单用例验证：
   ```bash
   python main.py --case test_cases/<your_case>.yaml
   ```
