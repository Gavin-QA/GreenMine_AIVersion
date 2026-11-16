# 🌐 Web 前端大盘与报告模板规范 (Frontend & Report Template Rules)

## 1. 核心定位与结构 (Directory Structure)
`web/` 负责承载巡检中枢的可视化控制台与自动化测试产物全景大盘，实行**“平台工程化 + 报告纯静态”**双轨架构：
- **`web/platform/`**：主流 **Vite + Vue 3 (`<script setup>`) + Element Plus + ECharts** 工程化前端控制台中枢（`src/views/`、`src/styles/`），提供免敲命令任务调度、全局缺陷资产看板、实时终端日志流与双擎性能监控大屏。开发态支持 `npm run dev` 热更新（自动代理 `/api`、`/ws`、`/reports` 至 FastAPI）；上线通过 `npm run build` 输出离线自闭环的 `dist/` 构建产物，由 Python FastAPI 服务优先挂载托管。
- **`web/templates/`**：单次运行报告 (`report.html`)、全量历史运行大盘 (`hub.html`) 与组件模板，**严格保持零构建、纯静态离线自闭环**，由报告生成器动态渲染，确保脱离平台或打包至飞书网页托管后仍可直接双击打开。

## 2. 绝对禁令 (Strict Prohibitions)
- **禁止硬编码协议与后端网络地址**：绝对不允许在前端 JS/TS/Vue 代码中使用 `http://localhost:8000` 或固定 IP。所有 API 请求必须使用相对路径（如 `/api/tasks`），所有 WebSocket 连接必须动态推导 `location.host`（如 `${location.protocol === 'https:' ? 'wss:' : 'ws:'}//${location.host}/ws/...`），确保在内网穿透、Vite 代理、Nginx 反代与各种端口转发下开箱即用。
- **禁止无限重连与 WebSocket 惊群风暴**：长连接断开后，重连机制必须采用指数退避算法（Exponential Backoff，如 1s、2s、4s... 上限 10s），严禁高频死循环重连打爆后端服务。
- **禁止页面长列表全量 DOM 渲染**：对于数百步探索截图、海量性能时序点与超长控制台终端日志，必须启用分页、虚拟滚动、等间距抽样或限制渲染条数，杜绝大屏因 DOM 节点过多发生内存溢出（OOM）白屏崩溃。
- **禁止在 `web/templates/` 中引入构建依赖**：`report.html` 与 `hub.html` 必须保持纯原生 HTML/JS/CSS 离线可用，严禁依赖外部 CDN 或 Vite 打包产物。

## 3. UI 交互与体验规范 (UI & DX Standards)
- **工程化组件复用与 Element Plus 统一规范**：`web/platform/` 中的日期区间选择器（`<el-date-picker>`）、表单、筛选器等优先使用 Element Plus 组件并统一挂载中文语言包与暗黑模式（`html.dark`），保持代码模块化拆分，严禁再次将数千行模板与逻辑堆砌在单一文件中。
- **零配置与防呆机制**：所有表单选项（应用选择、运行模式、预设模板）必须优先从后端 `/api/config/options` 动态拉取，提供直观的默认推荐项与微标提示。
- **自适应暗黑/工业大屏视觉规范**：大屏色彩必须保持统一的工业深色调风格（深蓝/暗灰底色搭配科技蓝/翠绿指示灯），关键告警使用明亮琥珀黄与高亮红进行醒目标记。
- **跨环境静态托管兼容**：`web/platform/dist/` 与 `web/templates/` 的最终产出均必须具备离线自闭环能力，严禁在运行态依赖外网 CDN。
