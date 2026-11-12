# 🌐 Web 前端大盘与报告模板规范 (Frontend & Report Template Rules)

## 1. 核心定位与结构 (Directory Structure)
`web/` 负责承载巡检中枢的可视化控制台与自动化测试产物全景大盘：
- **`web/platform/`**：前后端分离的纯静态控制台中枢（`index.html`、`js/`、`css/`），提供免敲命令任务调度、全局缺陷资产看板、实时终端日志流与双擎性能监控 ECharts 大屏。
- **`web/templates/`**：单次运行报告 (`report.html`)、全量历史运行大盘 (`hub.html`) 与组件模板，由报告生成器动态渲染。

## 2. 绝对禁令 (Strict Prohibitions)
- **禁止硬编码协议与后端网络地址**：绝对不允许在前端 JS 脚本中使用 `http://localhost:8000` 或固定 IP。所有 API 请求必须使用相对路径（如 `/api/tasks`），所有 WebSocket 连接必须动态推导 `location.host`（如 `${location.protocol === 'https:' ? 'wss:' : 'ws:'}//${location.host}/ws/...`），确保在内网穿透、Nginx 反代与各种端口转发下开箱即用。
- **禁止无限重连与 WebSocket 惊群风暴**：长连接断开后，重连机制必须采用指数退避算法（Exponential Backoff，如 1s、2s、4s... 上限 10s），严禁高频死循环重连打爆后端服务。
- **禁止页面长列表全量 DOM 渲染**：对于数百步探索截图、海量性能时序点与超长控制台终端日志，必须启用虚拟滚动、等间距抽样或限制渲染条数，杜绝大屏因 DOM 节点过多发生内存溢出（OOM）白屏崩溃。

## 3. UI 交互与体验规范 (UI & DX Standards)
- **零配置与防呆机制**：所有表单选项（应用选择、运行模式、预设模板）必须优先从后端 `/api/config/options` 动态拉取，提供直观的默认推荐项与微标提示。
- **自适应暗黑/工业大屏视觉规范**：大屏色彩必须保持统一的工业深色调风格（深蓝/暗灰底色搭配科技蓝/翠绿指示灯），关键告警使用明亮琥珀黄与高亮红进行醒目标记。
- **跨环境静态托管兼容**：静态 HTML/JS 产物必须具备离线自闭环能力，第三方依赖（ECharts、FontAwesome、Axios 等）优先本地化或配置稳定内网/CDN 降级源，严禁因外网阻断导致大屏白屏。
