---
name: zentao_sync
description: 同步本地测试缺陷库 (global_bugs.json) 到公司禅道项目管理系统
---

# 禅道同步助手 (Zentao Sync)

这是一个自定义 Antigravity Skill，用于自动将本地发现的缺陷（Bug）一键提交至公司禅道平台。

## 功能与用法

当用户要求“把最新的 Bug 同步到禅道”、“把指定的 Bug 提给禅道”或类似请求时，你应该调用位于本项目 `.agents/skills/zentao_sync/zentao_client.py` 的脚本。

### 1. 查询产品列表
如果还不确定该往禅道的哪个“产品 (Product ID)”下面提 Bug，你可以先运行：
```bash
python .agents/skills/zentao_sync/zentao_client.py --list-products
```
获取到 Product ID 列表后，通过用户的指示来决定提交到哪个产品。

### 2. 提单到禅道
如果你需要提单，运行以下命令（假设产品 ID 为 `10`，Bug ID 为 `BUG-20261001-001`）：
```bash
python .agents/skills/zentao_sync/zentao_client.py --submit-bug "BUG-20261001-001" --product-id 10
```

### 注意事项：
1. 提单成功后，`zentao_client.py` 脚本会自动修改本地 `artifacts/bugs/global_bugs.json` 中该条目的 `status` 为 `已提单`。
2. 提单时会自动附上本地捕获到的页面路径、异常堆栈或底层 API 报错等详细数据。
