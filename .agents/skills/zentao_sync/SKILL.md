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

### 2. 自动提交 Bug 到禅道
提交成功后会自动回填 `zentao_id` 并将本地状态置为 `已提单`：
```bash
python utils/zentao_sync.py --submit-bug "BUG-20261023-003" --product-id 10
```
- 标题将自动冠以 `【AI自动化·<矿山名称>】[BUG-ID]` 标识
- 内容附带富文本格式：业务路径、报错堆栈、复现频次、AI 根因分析笔记

### 3. 手动回填/绑定已有的禅道单号
若已在禅道网页端手动提交了 Bug，可将该单号回填至本地测试缺陷库与大盘：
```bash
python utils/zentao_sync.py --bind "BUG-20261023-003" --zentao-id 852
```

### 4. 网页大盘直接回填
在统一大盘门户 (`http://localhost:8080/`) 或各个单次运行报告的“Bug 详情”弹窗中，点击“✏️ 编辑 Bug 详情”，输入“关联禅道 Bug 编号 (ZenTao ID)”并保存，即可自动持久化保存并即时刷新大盘。
