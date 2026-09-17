# Release Checklist

- [ ] `.env` 和 API Key 未进入提交内容
- [ ] `.venv/bin/pytest` 全部通过
- [ ] `macpilot-evals --output data/evals/latest.json` 全部通过
- [ ] 检查真实任务报告中的完成率、恢复率、延迟和成本
- [ ] 检查安全指标：未授权操作为 0，高风险动作均有审批
- [ ] 在干净环境安装 Python 依赖并启动 FastAPI
- [ ] 安装 Node/Rust/Tauri 后构建桌面端安装包
- [ ] 录制 `docs/demo-script.md` 对应的 Demo
- [ ] 创建 GitHub Release，并附上评测报告和 macOS 安装包

当前工作区没有 Git remote 或发布凭据，因此最后一项需要在目标仓库中由项目维护者执行。
