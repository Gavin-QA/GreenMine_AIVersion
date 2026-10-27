---
name: feishu_pack
description: 一键将测试报告与缺陷证据轻量化打包为飞书网页托管静态发布包（从几GB激进压缩至30~50MB）
---

# 飞书测试报告轻量化打包助手 (Feishu Pack)

专为飞书团队工坊“网页托管”定制的一键打包工具，将数 GB 带有大量过程截图的自动化测试运行记录（`reports/runs/<run_id>`），自动瘦身、转码并组装为符合规范的纯静态 ZIP 发布包。

## 适用场景
- 用户要求“把最新的测试报告打包发给飞书 / 领导”
- 用户需要将某个指定运行批次（如 `explore_20261026_182259`）分享给研发团队
- 测试运行完成后快速生成本地轻量化静态 HTML 预览

## 核心特性
1. **激进瘦身（GB 级 ➔ 30~60MB）**：
   - 过滤上千张无故障普通过程帧；
   - 100% 完整保留所有缺陷（Bug）的【操作前】与【案发现场】高清双图对比；
   - 采用多线程并发 + LANCZOS 重采样 + WebP 格式智能转码。
2. **零污染保证**：
   - 仅在内存和临时归档中工作，完全不修改、不删除本地磁盘上的任何原始测试数据。
3. **自动就绪预览**：
   - 打包完成后自动同步解压至 `reports/feishu_preview/`，一键点击即可在本地浏览器审查最终效果。

## 使用方法

脚本路径：`utils/pack_feishu.py`

### 1. 打包最新一次测试运行（默认仅缺陷证据，体积最小约 35MB）
```bash
python utils/pack_feishu.py
```

### 2. 打包指定运行批次
```bash
python utils/pack_feishu.py --run explore_20261026_182259
```

### 3. 保留 Planner 宏观关键帧（适合探索类报告，体积约 60~80MB）
```bash
python utils/pack_feishu.py --mode keyframes
```

### 4. 自定义压缩质量与输出路径
```bash
python utils/pack_feishu.py --quality 75 --output "reports/weekly_report.zip"
```

## 执行流程与输出规范
当调用本 Skill 后：
1. 运行 `python utils/pack_feishu.py`（根据用户意图补充 `--run` 或 `--mode`）。
2. 解析终端输出，向用户汇报：
   - **打包源目录**与**运行 ID**；
   - **压缩前 vs 压缩后体积**（展示瘦身比例）；
   - **缺陷截图数量**；
   - **本地预览链接**（`file:///d:/Auto/electron_ai_vision/reports/feishu_preview/index.html`）；
   - **ZIP 发布包物理路径**，提示用户可直接上传至飞书网页托管后台。
