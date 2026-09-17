# MacPilot

一个使用 LangChain 和 LangGraph 构建的本地优先 Computer-Use Agent 原型。

Phase 2 工作流代码位于 `src/macpilot/phase2/workflow.py`。

## 代码分层

实现代码按开发阶段拆分，避免所有功能堆在同一个目录：

```text
src/macpilot/
├── core/                 # 共享基础设施
│   ├── config.py         # 环境变量和运行配置
│   ├── models.py         # Task / Step / Approval / Event 类型
│   ├── storage.py        # SQLite 任务和审计记录
│   └── checkpoint.py     # LangGraph 持久化 checkpoint
├── phase1/
│   └── filesystem.py     # 文件读取、写入和路径白名单
├── phase2/
│   └── workflow.py       # Planner / Researcher / Critic / Finalizer
├── phase3/
│   ├── browser.py        # Playwright 和网页内容安全处理
│   ├── documents.py      # PDF / Word / Excel 解析
│   ├── resume_profile.py # ResumeProfile 和证据模型
│   └── security.py       # 浏览器域名白名单
├── phase5/
│   ├── metrics.py         # 完成率、恢复率、延迟、成本等指标
│   └── runner.py          # 50 个离线回归任务和报告生成
├── core/context.py        # 上下文预算和裁剪
├── core/cache.py          # SQLite 本地响应缓存
├── core/usage.py          # Token 使用量和成本估算
├── api.py                # FastAPI 入口
└── cli.py                # 命令行入口
```

顶层的 `config.py`、`storage.py`、`agent_workflow.py` 等只是兼容导入，真正实现
分别位于 `core/`、`phase1/`、`phase2/` 和 `phase3/`。

当前能力：

- 只访问 `MACPILOT_WORKSPACE` 指定的目录
- 列出目录中的文件
- 读取受支持的文本文件
- 在 `MACPILOT_READ_ONLY=false` 时写入受支持的文本文件
- 通过路径解析阻止 `..` 和符号链接越权
- 将任务、步骤、工具调用、审批和异常持久化到 SQLite
- 根据文件内容回答问题或生成摘要
- 使用 LangGraph checkpoint 保留同一会话的消息状态
- 使用 `Planner → Researcher → Critic → Finalizer` 完成可恢复的研究流程
- Critic 发现证据不足时自动重试 Researcher 一次
- 高风险计划会暂停在人工审批节点，可通过 API 恢复
- 通过域名白名单读取网页，网页内容始终作为不可信数据处理
- 提取 PDF、Word、Excel 和文本文件，并保留来源文件名
- 使用带证据和置信度的 `ResumeProfile` 数据结构

## 启动

```bash
cp .env.example .env
# 在 .env 中填写新的 DASHSCOPE_API_KEY
.venv/bin/pip install -e '.[dev,phase3]'
.venv/bin/macpilot
```

示例输入：

```text
读取所有文件，告诉我这个项目的定位、当前能力和目标用户。
```

默认工作目录是 `data/workspace`。第一版只读，不具备写文件、浏览器操作或提交动作。

## FastAPI 服务

启动本地 API：

```bash
.venv/bin/macpilot-api
```

打开 `http://127.0.0.1:8000/docs` 可以查看交互式 API 文档。

当前接口：

- `GET /health`：健康检查
- `POST /tasks`：创建任务
- `GET /tasks/{task_id}`：查询任务
- `POST /tasks/{task_id}/messages`：向任务发送一条消息并运行 Agent
- `GET /tasks/{task_id}/steps`：查询步骤记录
- `GET /tasks/{task_id}/events`：查询审计事件
- `GET /tasks/{task_id}/approvals`：查询任务的审批请求
- `POST /tasks/{task_id}/approvals/{approval_id}`：批准或拒绝审批请求
- `POST /tasks/{task_id}/resume`：用审批决定恢复暂停的任务
- `POST /tasks/{task_id}/cancel`：终止未完成任务
- `GET /metrics`：聚合所有已持久化任务的评测指标
- `GET /tasks/{task_id}/metrics`：查看单个任务的指标

Phase 2 的一次任务会依次经过 Planner、Researcher、Critic 和 Finalizer；
每个节点都会写入步骤和事件。模型调用超时默认为 120 秒，可在 `.env` 中通过
`MACPILOT_AGENT_TIMEOUT_SECONDS` 调整。

示例：

```bash
curl -X POST http://127.0.0.1:8000/tasks \
  -H 'Content-Type: application/json' \
  -d '{"user_goal":"总结本地项目资料"}'
```

创建任务后，把返回的 `id` 用于发送消息：

```bash
curl -X POST http://127.0.0.1:8000/tasks/TASK_ID/messages \
  -H 'Content-Type: application/json' \
  -d '{"content":"读取所有文件并生成摘要"}'
```

任务记录默认保存在 `data/macpilot.sqlite3`。每次工具调用都会写入事件表，
方便在后续 API、时间线和评测功能中复用。写入能力默认关闭，打开前应确认工作目录
是专门给 MacPilot 使用的目录。

安全配置：API Key 只从 `DASHSCOPE_API_KEY` 环境变量读取，不应写入源码或提交到仓库。
如果旧版本的 Key 曾经暴露，应在 DashScope 控制台撤销并重新生成。

Phase 3 浏览器配置默认关闭。只有配置白名单域名后，Researcher 才能读取网页：

```env
MACPILOT_ALLOWED_BROWSER_DOMAINS=example.com,wikipedia.org
```

浏览器工具当前是只读的，不会提交表单、上传文件或发送消息。首次使用 Playwright
时，如果本机没有 Chromium 运行时，可以执行：

```bash
.venv/bin/playwright install chromium
```

## 测试

```bash
.venv/bin/pytest
```

## Phase 5 评测与优化

评测任务定义在 `evals/tasks.json`，共 50 个任务：本地文件 10 个、网页研究 15 个、
文档生成 10 个、失败恢复 8 个、安全 7 个。默认评测是离线、确定性的策略和工具回归，
不会联网，也不需要 API Key：

```bash
.venv/bin/macpilot-evals --output data/evals/latest.json
# 或
.venv/bin/python evals/run_evals.py --category security
```

命令同时生成 JSON 和 Markdown 报告。它不会把离线回归结果冒充真实端到端成绩；真实任务
完成后，可以把 SQLite 事件流纳入同一份报告：

```bash
.venv/bin/macpilot-evals --database data/macpilot.sqlite3 \
  --output data/evals/latest.json
```

报告包含任务完成率、平均步骤数、工具调用数、恢复率、未授权操作数、Prompt Injection
检测率、引用正确率、Token 数、估算成本和缓存命中率。成本默认是 0，只有在 `.env` 中
填写对应模型的每百万 Token 价格后才会估算，不会把估算值当作账单金额。

Phase 5 默认启用 SQLite 响应缓存和上下文预算。缓存只作用于模型响应，工具调用和审批
仍然每次执行；`MACPILOT_CONTEXT_MAX_TOKENS`、`MACPILOT_CACHE_ENABLED` 和
`MACPILOT_CACHE_TTL_SECONDS` 可调整行为。

架构说明和 3 分钟 Demo 讲稿位于 `docs/architecture.md` 和 `docs/demo-script.md`；
发布前检查清单位于 `docs/release-checklist.md`。

## Phase 4 桌面端

Tauri + React 桌面端位于 `apps/desktop`，包含任务输入、时间线、审批弹窗、结果预览、
任务终止和菜单栏托盘入口。桌面端默认连接本地 FastAPI：

```bash
cd apps/desktop
npm install
npm run tauri dev
```

当前 Python 环境没有 Node.js、Rust 和 Tauri CLI，因此暂时只能完成工程代码和后端验证；
安装桌面端构建依赖后即可编译 macOS 应用。
