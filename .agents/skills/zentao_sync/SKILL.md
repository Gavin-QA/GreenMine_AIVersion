---
name: zentao_sync
description: 同步本地测试缺陷库到公司禅道项目管理系统并实现提单前预览微调与双向编号绑定
---

# 禅道同步助手 (ZenTao Sync)

用于将本地多模态 AI 自动化测试发现的缺陷（Bug）提报至公司禅道平台，支持 **Web 控制台提单前交互式预览与微调弹窗**、动态禅道字典级联拉取、最近构建版本自动匹配，以及双向追溯闭环。

## 架构说明：产品、项目、执行与版本映射
在禅道体系中：
- **产品 (Product)**：Bug 的归属产品（如 `数字孪生系统` ID: `11`）
- **所属模块 (Module)**：产品下的功能模块（默认 `/` 即 `0`，通过禅道 `/api.php/v1/modules` 动态拉取）
- **项目 (Project)**：具体的项目空间（如 `神农架寨湾二期` ID: `26`、`四川里伍铜` ID: `120`、`马边天瑞` ID: `134`）
- **执行/迭代 (Execution)**：项目下的执行阶段（如 `测试` ID: `30`、`开发` ID: `29`，切换项目时动态刷新）
- **影响版本 (openedBuild)**：项目关联的构建版本列表（切换项目/产品时动态拉取，**默认自动匹配最近 2 条：1 条 `web` + 1 条 `ue`**，无版本时回退 `trunk`）

### 配置来源
凭据与各应用的默认产品/项目/执行绑定已在统一配置中枢集中管理：
- `config.yaml` -> `apps.<app>.zentao_product_id`, `zentao_project_id`, `zentao_execution_id`
- `config.yaml` -> `zentao.url`, `zentao.account`, `zentao.default_product_id`, `default_project_id`, `default_execution_id`
- `.env` -> `ZENTAO_PASSWORD`

---

## 核心功能与用法

### 1. Web 控制台：提单前预览与微调弹窗（推荐）
在统一大盘门户的**缺陷治理中枢**或**缺陷详情弹窗**中点击 **“推禅道” / “提交至禅道”**，系统不再直接盲推，而是打开**禅道提单预览与微调弹窗**：

1. **实时动态拉取禅道字典** (`GET /api/bugs/{bug_id}/zentao_preview`)：
   - 自动计算默认归属：产品、项目、执行、模块（默认 `/`）、Bug 类型（默认 `codeerror` 代码错误）、严重程度 & 优先级（默认 `3`）、Bug 状态（`激活`）、截止日期（**提单时间 + 7 天**）。
   - 自动匹配 **影响版本**：从禅道实时拉取当前项目所有构建版本，智能选中**最近的 2 条**（优先 1 条 `web` + 1 条 `ue`），支持勾选调整或选 `主干 (trunk)`。
   - 自动分流 **指派给**：结合 AI 诊断结论自动分流（前端 `陈贻雄` / 后端 `梅本霞` / 数据接入 `李云骢` 等），同时提供实时拉取的禅道全员列表供人工改派。
2. **级联动态切换** (`GET /api/zentao/metadata?project_id=...&product_id=...`)：
   - 在弹窗中切换**所属项目**或**所属产品**时，自动重新拉取对应的执行阶段、产品模块、构建版本并刷新推荐的最近 2 条影响版本。
3. **重现步骤双模式预览**：
   - 支持 **👁️ 禅道效果预览**（所见即所得，含案发现场截图）与 **📝 HTML 源码微调**。
4. **确认提交** (`POST /api/bugs/{bug_id}/sync_zentao`)：
   - 携带预览确认后的完整 `ZentaoSubmitRequest` 参数提单，自动预上传案发现场截图至禅道附件并替换富文本图片 URL，成功后回填 `zentao_id` 并流转状态为 `已提单`。

---

### 2. 后端 REST API 契约清单
- `GET /api/bugs/{bug_id}/zentao_preview`：获取指定缺陷的禅道提单预览默认值与实时动态字典（产品、项目、执行、模块、版本、成员、Bug 类型）。
- `GET /api/zentao/metadata?project_id=&product_id=`：级联查询项目/产品关联的执行、模块、构建版本及推荐的最近 2 条影响版本。
- `POST /api/bugs/{bug_id}/sync_zentao`：提交缺陷至禅道（支持空 Body 走智能默认，也支持传入 `ZentaoSubmitRequest` 覆盖 `title`、`product_id`、`project_id`、`execution_id`、`module_id`、`type`、`severity`、`pri`、`assigned_to`、`deadline`、`opened_build`、`os`、`browser`、`steps_html`）。

---

### 3. CLI 命令行与 Python 客户端 (`utils/zentao_sync.py`)
`ZenTaoClient` 已内置动态元数据查询与完整提单能力：
- `get_products()` / `get_projects()` / `get_executions(project_id)`
- `get_modules(product_id)` / `get_builds(project_id)` / `get_users(limit=200)`
- `pick_default_opened_builds(builds, product_id)`：自动挑选最近 1 条 `web` + 1 条 `ue` 构建版本
- `submit_bug(..., module_id=0, deadline=..., opened_build=..., os_name="windows", browser_name="electron")`

常用 CLI 命令：
```bash
# 查询可用产品与项目列表
python utils/zentao_sync.py --list-products
python utils/zentao_sync.py --list-projects

# 智能自动研判并提交至默认项目
python utils/zentao_sync.py --submit-bug "BUG-20261026-003"

# 人工显式指定指派人或项目/执行
python utils/zentao_sync.py --submit-bug "BUG-20261026-003" --assignee "李云骢" --project-id 26 --execution-id 30

# 同步刷新已在禅道创建的缺陷内容
python utils/zentao_sync.py --update-bug "BUG-20261030-001"

# 手动回填/绑定已有的禅道单号
python utils/zentao_sync.py --bind "BUG-20261023-003" --zentao-id 852 --assignee "陈贻雄"
```
