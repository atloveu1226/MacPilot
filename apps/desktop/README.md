# MacPilot Desktop

Phase 4 的 Tauri + React 桌面端骨架。

功能：

- 本地任务输入
- 任务状态和执行时间线
- Planner / Researcher / Critic / Finalizer 状态
- 高风险审批弹窗
- 结果预览
- 任务终止
- macOS 菜单栏托盘入口和通知

前端默认连接 `http://127.0.0.1:8000` 的 FastAPI 服务。

当前机器如果没有 Node.js、Rust 和 Tauri CLI，需要先安装这些开发依赖，之后在本目录执行：

```bash
npm install
npm run tauri dev
```
