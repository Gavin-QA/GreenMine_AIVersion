# ⚡ Server 后端架构与工程防腐守则 (Backend Architecture Rules)

## 1. 架构定位与核心分层 (Architecture Hierarchy)
`server/` 是整个自动化测试平台的后端中枢与 Web API 控制塔，基于 FastAPI + SQLAlchemy 构建。必须严格遵守以下分层职责：
- **`server/main.py`**：应用总装入口。仅负责 FastAPI 实例配置、全局中间件 (CORS)、启动/退出生命周期钩子 (`on_startup` / `on_shutdown`)、静态资源挂载以及统一挂载各领域 Router。**绝对禁止在此文件中直接编写具体业务 API**。
- **`server/routers/`**：领域路由层 (Controller)。按业务领域拆分（如 `tasks.py`、`bugs.py`、`performance.py` 等），负责 HTTP/WebSocket 请求参数解析、状态码控制与响应序列化。
- **`server/schemas.py`**：数据契约层 (DTO / Pydantic)。所有输入输出数据结构必须在此统一声明，供 Swagger 文档与接口校验使用。
- **`server/models.py` & `server/database.py`**：数据持久化层 (ORM / DAO)。负责 SQLite 表结构定义与数据库会话管理。
- **`server/task_manager.py` / `performance_monitor.py` / `sync_service.py`**：底层服务层 (Service Engine)。负责任务执行子进程、探针采样守护与文件热同步。

## 2. 绝对禁令 (Strict Prohibitions)
- **禁止单文件过度膨胀**：单个 Python 代码文件原则上严禁超过 450 行，一旦逼近阈值必须按业务子领域或辅助函数进行横向拆分。
- **禁止在路由中堆砌同步阻塞 I/O**：严禁在 HTTP 路由主线程中执行耗时的磁盘目录递归遍历、小文件树删除或大盘重构。必须使用 `BackgroundTasks` 或放入工作线程异步执行，确保所有 HTTP 接口在 50ms 内极速响应。
- **禁止无契约裸写 Dict 响应**：所有外部暴露的路由必须显式指定 `response_model`，并使用 Pydantic 模型进行类型守卫。
- **禁止未受控的 WebSocket 连接泄漏**：所有新建立的 WebSocket 连接必须登记到 `server.routers.websockets.active_websockets` 全局连接池，并在连接断开或服务关闭时优雅释放，严禁残留僵尸连接阻塞 uvicorn reload。
- **禁止破坏受控单据完整性**：删除任务或缺陷时，必须校验其业务约束（例如已同步至禅道的缺陷单据禁止物理删除，只能标记解绑或归档）。

## 3. 新增业务路由标准工作流 (Route Authoring Standard)
当需要新增或扩展后端功能时，必须严格遵循以下四步规范：
1. **契约先行**：在 `server/schemas.py` 中定义好请求体与响应体的 Pydantic 模型。
2. **归类挂载**：
   - 若属于已有领域（如任务、缺陷、性能），直接在对应的 `server/routers/<domain>.py` 中添加 `@router.xxx`；
   - 若属于全新的业务域，在 `server/routers/` 下新建 `<new_domain>.py`，并在 `server/routers/__init__.py` 中集中导出。
3. **主入口装配**：在 `server/main.py` 中通过 `app.include_router(...)` 引入。
4. **测试验证**：编写或更新 `tests/test_unified_platform.py`，确保接口状态码与数据契约 100% 校验通过。
