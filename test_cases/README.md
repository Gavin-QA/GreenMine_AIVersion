# 测试用例目录规范 (Test Cases Specification)

本目录为 **正式回归测试用例库 (Golden Baseline Cases)**，原则上仅存放经过人工确认的稳定、可重复执行的 YAML 测试场景。

---

## 📁 目录规范说明

1. **人工基线用例 (手工编写)**：
   - 直接存放在 `test_cases/` 根目录下，如：
     - `test_home_cert.yaml`（证照管理回归用例）
     - `test_home_mine_intro.yaml`（矿山简介回归用例）
     - `test_roam_only.yaml`（3D 漫游专项用例）

2. **AI 探索闭环生成的用例 (Exploration Isolated Cases)**：
   - 系统运行 `--explore` 模式时，探索闭环生成的 YAML 用例会自动收纳在每次运行的专属目录中：
     - 路径：`reports/runs/<run_id>/generated_cases/auto_generated_<run_id>.yaml`
   - **用例晋升机制 (Promotion)**：
     - 若你在单次探索报告中发现某个自动生成的链路非常稳定且覆盖了关键业务，可将该 YAML 复制并重命名移动至 `test_cases/` 成为正式回归用例；
     - 避免未经人工校验的大量探索中间脚本直接塞爆 `test_cases/`，防止执行 `python main.py --all` 时误跑失效链路。
