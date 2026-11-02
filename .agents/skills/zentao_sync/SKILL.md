---
name: zentao_sync
description: 同步本地测试缺陷库到公司禅道项目管理系统并实现双向编号绑定
---

# 禅道同步助手 (ZenTao Sync)

用于将本地多模态 AI 自动化测试发现的缺陷（Bug）一键提交至公司禅道平台，或在人工于禅道建单后回填绑定禅道 ID，形成双向追溯闭环。

## 架构说明：产品、项目与执行三层映射
在禅道体系中：
- **产品 (Product)**：Bug 的归属产品（如数字孪生系统 ID: 11）
- **项目 (Project)**：具体的项目空间（如神农架寨湾二期 ID: 26、四川里伍铜 ID: 120），只有关联了项目，才能在【项目视图】及项目看板中展示。
- **执行/迭代 (Execution)**：项目下的执行阶段（如测试 ID: 30、开发 ID: 29）。

### 配置来源
凭据与各应用的项目/执行绑定已在统一配置中枢集中管理：
- `config.yaml` -> `apps.<app>.zentao_product_id`, `zentao_project_id`, `zentao_execution_id`
- `config.yaml` -> `zentao.url`, `zentao.account`, `zentao.default_product_id`, `default_project_id`, `default_execution_id`
- `.env` -> `ZENTAO_PASSWORD`

## 功能与用法

可直接运行 `python utils/zentao_sync.py` 或 `.agents/skills/zentao_sync/zentao_client.py`。

### 1. 查询可用产品与项目列表
```bash
# 查询可用产品列表
python utils/zentao_sync.py --list-products

# 查询可用项目与执行迭代列表
python utils/zentao_sync.py --list-projects
```

### 2. 自动提交 Bug 到禅道 (自动打入项目与执行 + 前置 AI 守卫 + 智能责任人分流)
系统会自动根据当前运行的应用（寨湾或里伍铜）提取对应的项目与执行 ID 一并提交，提单后**立即在对应项目的 Bug 列表与看板中可见**。

```bash
# 智能自动研判并提交至默认项目（寨湾自动打入【神农架寨湾二期/测试】）
python utils/zentao_sync.py --submit-bug "BUG-20261026-003"

# 人工显式指定指派人 (支持：陈贻雄 / 梅本霞 / 前端 / 后端)
python utils/zentao_sync.py --submit-bug "BUG-20261026-003" --assignee "梅本霞"

# 显式覆盖目标项目或执行迭代
python utils/zentao_sync.py --submit-bug "BUG-20261026-003" --project-id 26 --execution-id 30
```
提交成功后会自动回填 `zentao_id`，将责任人锁定写入本地单据，并将状态流转为 `已提单`。

### 3. 同步刷新已在禅道创建的缺陷内容 (--update-bug)
若本地补全了具体接口 URL、报错堆栈、AI 研判结论，或需补全关联项目与执行，可一键将最新富文本与项目归属推送到禅道现有工单上：
```bash
python utils/zentao_sync.py --update-bug "BUG-20261030-001"
```

### 4. 手动回填/绑定已有的禅道单号
若已在禅道网页端手动提交了 Bug，可将该单号回填至本地测试缺陷库与大盘，亦可同时绑定指派人：
```bash
python utils/zentao_sync.py --bind "BUG-20261023-003" --zentao-id 852 --assignee "陈贻雄"
```

### 5. 网页大盘直接回填与一键分派
在统一大盘门户 (`http://localhost:8080/`) 或单次运行报告的“Bug 详情”弹窗中：
- 责任人显示徽标：`👨‍💻 陈贻雄 (前端)` 或 `👩‍💻 梅本霞 (后端)`
- 点击“✏️ 编辑 Bug 详情”后，提供快捷一键点选按钮（前端/后端）以及禅道 ID 输入框，保存后自动持久化。
