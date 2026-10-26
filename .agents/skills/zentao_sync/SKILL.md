---
name: zentao_sync
description: 同步本地测试缺陷库到公司禅道项目管理系统并实现双向编号绑定
---

# 禅道同步助手 (ZenTao Sync)

用于将本地多模态 AI 自动化测试发现的缺陷（Bug）一键提交至公司禅道平台，或在人工于禅道建单后回填绑定禅道 ID，形成双向追溯闭环。

## 配置来源
禅道连接凭据与默认产品已由统一配置中枢管理：
- `config.yaml` -> `zentao.url`, `zentao.account`, `zentao.default_product_id`
- `.env` -> `ZENTAO_PASSWORD`

## 功能与用法

可直接运行 `python utils/zentao_sync.py` 或 `.agents/skills/zentao_sync/zentao_client.py`。

### 1. 查询可用产品列表
```bash
python utils/zentao_sync.py --list-products
```

### 2. 自动提交 Bug 到禅道 (前置 AI 守卫 + 智能责任人分流)
- **前置 AI 智能守卫**：提单前系统会自动检测，若该缺陷尚未有 AI 归因研判，**自动在后台立即调用大模型生成初诊与排查指引并回填**，确保推上禅道的每一张单据都包含详尽的排查思路和接口/前端线索。
- **责任人自动分流**：根据 AI 智能归因、报错堆栈、5xx/网络或前端JS渲染等特征**全自动判定指派责任人**，也支持人工显式指定：
  - **前端问题** -> 自动指派 **陈贻雄** (`chenyixiong`)
  - **后端问题** -> 自动指派 **梅本霞** (`meibenxia`)

```bash
# 智能自动研判并提交指派 (若无AI备注将自动补齐)
python utils/zentao_sync.py --submit-bug "BUG-20261026-003"

# 人工显式指定指派人 (支持：陈贻雄 / 梅本霞 / 前端 / 后端)
python utils/zentao_sync.py --submit-bug "BUG-20261026-003" --assignee "梅本霞"
```
提交成功后会自动回填 `zentao_id`，将责任人锁定写入本地单据，并将状态流转为 `已提单`。

### 3. 同步刷新已在禅道创建的缺陷内容 (--update-bug)
若本地补全了具体接口 URL、报错堆栈或 AI 研判结论，可一键将最新富文本与责任人同步推送到禅道现有工单上：
```bash
python utils/zentao_sync.py --update-bug "BUG-20261023-004"
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
