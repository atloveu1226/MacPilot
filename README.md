# MacPilot

MacPilot 是一个本地优先的简历自动化与 Computer-Use Agent 原型。它使用
FastAPI、LangGraph、React/Tauri、SQLite 和 Playwright，把简历读取、字段映射、
网页表单识别和草稿填写组织成可追踪的工作流。

## 当前能力

- 从 PDF、DOCX、Markdown 和 TXT 简历中提取结构化 `ResumeProfile`；
- 保留教育、研究/工作经历和项目经历的数组结构与证据来源；
- 根据经历数量动态创建教育和项目字段；
- 使用 LangGraph checkpoint、任务状态、审计事件和 Token 用量记录；
- 浏览器访问使用域名白名单，网页内容按不可信数据处理；
- 表单默认只填写草稿，不自动提交；高风险操作需要人工审批；
- 提供离线回归评测和真实任务 Trace 指标。

## Agent 流程

```text
简历 PDF
   │
   ▼
CV Extractor
   │  ResumeProfile + evidence
   ▼
字段校验与映射
   │
   ├── 本地简历工作区：回填基本信息、教育、工作和项目经历
   │
   └── 外部网页表单：Form Filler → inspect_form → 动态创建字段 → 填写草稿
```

`Form Filler` 只使用上一阶段的 `ResumeProfile`，不能自行补造内容，也不会点击最终提交按钮。

## 项目结构

```text
src/macpilot/
├── api.py                    # FastAPI 任务、上传和消息接口
├── phase2/workflow.py        # LangGraph 工作流与 CV Extractor/Form Filler
├── phase3/documents.py       # PDF、DOCX、Excel 和文本解析
├── phase3/resume_profile.py  # ResumeProfile 数据契约
├── phase3/browser.py         # Playwright 浏览器与表单工具
├── core/storage.py           # SQLite 任务、步骤和审计事件
└── phase5/                   # 离线评测与指标

apps/desktop/src/App.tsx      # React 简历表单界面
evals/                        # 能力评测任务和固定表单
tests/                        # 单元测试和 API 测试
docs/                         # 架构与演示文档
```

## 环境要求

- Python 3.12+
- Node.js 18+
- Qwen/DashScope 兼容 API Key（运行实时 Agent 时需要）

## 安装

```bash
cd MacPilot
source .venv/bin/activate
.venv/bin/pip install -e '.[dev,phase3]'

cd apps/desktop
npm install
```

在项目根目录创建 `.env`，至少配置：

```env
DASHSCOPE_API_KEY=你的百炼APIKey
QWEN_MODEL=qwen3.8-flash
QWEN_REGION=cn-beijing
QWEN_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
MACPILOT_WORKSPACE=./data/workspace
MACPILOT_READ_ONLY=true
```

不要把 `.env` 或 API Key 提交到 GitHub。

## 启动前后端

终端一：

```bash
cd MacPilot
source .venv/bin/activate
.venv/bin/macpilot-api
```

后端地址：[http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)

终端二：

```bash
cd MacPilot/apps/desktop
npm run dev
```

前端地址：[http://127.0.0.1:1420/](http://127.0.0.1:1420/)

如果端口已经被旧进程占用，先查找并停止对应进程：

```bash
lsof -nP -iTCP:8000 -sTCP:LISTEN
lsof -nP -iTCP:1420 -sTCP:LISTEN
kill <PID>
```

## 简历测试

1. 打开前端；
2. 选择 PDF 简历；
3. 点击“解析并填入表单”；
4. 检查基本信息、教育经历、工作经历和项目经历；
5. 只有在明确授权域名后，才使用 Browser Agent 填写外部网页草稿。

系统不会自动提交外部表单。

## API 示例

```bash
curl -X POST http://127.0.0.1:8000/tasks \
  -H 'Content-Type: application/json' \
  -d '{"user_goal":"读取上传的简历并提取 ResumeProfile"}'
```

主要接口：

| 方法 | 路径 | 作用 |
|---|---|---|
| GET | `/health` | 健康检查 |
| POST | `/tasks` | 创建任务 |
| POST | `/tasks/{id}/files` | 上传源文件 |
| POST | `/tasks/{id}/messages/stream` | 运行并流式返回 Agent 进度 |
| GET | `/tasks/{id}/events` | 查看审计事件 |
| GET | `/tasks/{id}/metrics` | 查看任务指标 |

## 评测与测试

离线评测不调用模型：

```bash
.venv/bin/macpilot-evals --output data/evals/latest.json
```

运行测试：

```bash
PYTHONPATH=src .venv/bin/pytest -q
```

评测关注成功率、平均步骤数、工具调用数、恢复率、Prompt Injection 阻断、
Token 用量和估算成本。离线评测结果不能替代真实模型端到端评测。

## 安全边界

- 默认只读，不允许 Agent 任意写入工作区；
- 文件访问限制在 `MACPILOT_WORKSPACE`；
- 浏览器只允许访问显式授权域名；
- 网页中的指令不会改变系统策略；
- 表单提交、删除、命令执行和消息发送等高风险操作需要审批；
- 简历上传和模型调用只用于当前任务，不会自动公开或提交。

更多设计说明见 [docs/architecture.md](docs/architecture.md) 和
[docs/demo-script.md](docs/demo-script.md)。
