# MacPilot

MacPilot is a local-first macOS computer-use agent prototype built with
LangChain, LangGraph, FastAPI, and Tauri. It turns a natural-language goal
into an observable, resumable workflow while keeping filesystem, browser, and
high-risk actions behind explicit policy boundaries.

The project focuses on reliability rather than unconstrained autonomy:

- structured planning with `Planner → Researcher → Critic → Finalizer`
- durable SQLite task, step, approval, and audit-event storage
- LangGraph checkpoints, retry, pause, resume, and cancellation
- filesystem and browser allowlists with read-only defaults
- untrusted webpage content and prompt-injection detection
- human approval gates for high-risk actions
- 50 deterministic Phase 5 regression tasks and trace-based metrics
- a Tauri + React desktop application for task execution and review

## Project structure

```text
src/macpilot/
├── core/
│   ├── cache.py          # Local SQLite response cache
│   ├── checkpoint.py     # Durable LangGraph checkpoints
│   ├── config.py         # Environment-backed runtime settings
│   ├── context.py        # Context budgets and message trimming
│   ├── models.py         # Task / Step / Approval / Event contracts
│   ├── storage.py        # SQLite task and audit storage
│   └── usage.py          # Token usage and cost estimation
├── phase1/
│   └── filesystem.py     # Workspace-scoped filesystem tools
├── phase2/
│   └── workflow.py       # Planner / Researcher / Critic / Finalizer
├── phase3/
│   ├── browser.py        # Playwright and webpage safety handling
│   ├── documents.py      # PDF / Word / Excel extraction
│   ├── resume_profile.py # Evidence-aware ResumeProfile model
│   └── security.py       # Browser domain allowlist
├── phase5/
│   ├── metrics.py        # Evaluation and trace metrics
│   └── runner.py         # Offline regression runner and reports
├── api.py                # FastAPI application
└── cli.py                # Interactive command-line client

apps/desktop/             # Tauri + React desktop client
evals/                    # 50 evaluation task definitions
docs/                     # Architecture, demo, and release documentation
tests/                    # Unit and integration tests
```

## Requirements

- Python 3.12+
- Optional: Node.js, Rust, and the Tauri CLI for the desktop application
- A Qwen/DashScope-compatible API key for live model execution

## Installation

```bash
cp .env.example .env
# Edit .env and set DASHSCOPE_API_KEY for live model execution.
.venv/bin/pip install -e '.[dev,phase3]'
```

The default workspace is `data/workspace`. The default mode is read-only, and
browser access is disabled until domains are explicitly allowlisted.

## Run the agent

Start the interactive CLI:

```bash
.venv/bin/macpilot
```

Example request:

```text
Read all workspace files and summarize the project's positioning, current capabilities, and target users.
```

Start the local API:

```bash
.venv/bin/macpilot-api
```

Then open [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs) for the
interactive API documentation.

## API endpoints

| Method | Endpoint | Purpose |
|---|---|---|
| `GET` | `/health` | Health check |
| `POST` | `/tasks` | Create a task |
| `GET` | `/tasks/{task_id}` | Inspect task status |
| `POST` | `/tasks/{task_id}/messages` | Send a message and run the agent |
| `GET` | `/tasks/{task_id}/steps` | List workflow steps |
| `GET` | `/tasks/{task_id}/events` | List audit events |
| `GET` | `/tasks/{task_id}/approvals` | List approval requests |
| `POST` | `/tasks/{task_id}/approvals/{approval_id}` | Approve or reject an action |
| `POST` | `/tasks/{task_id}/resume` | Resume a paused task |
| `POST` | `/tasks/{task_id}/cancel` | Cancel an unfinished task |
| `GET` | `/metrics` | Aggregate all persisted task metrics |
| `GET` | `/tasks/{task_id}/metrics` | Inspect metrics for one task |

Example:

```bash
curl -X POST http://127.0.0.1:8000/tasks \
  -H 'Content-Type: application/json' \
  -d '{"user_goal":"Summarize the local project files"}'
```

Use the returned task ID to send a message:

```bash
curl -X POST http://127.0.0.1:8000/tasks/TASK_ID/messages \
  -H 'Content-Type: application/json' \
  -d '{"content":"Read all files and produce a concise summary"}'
```

Every tool call, model usage record, approval, error, and assistant response is
stored in `data/macpilot.sqlite3`. The database is local-only by default.

## Security model

- `MACPILOT_WORKSPACE` is the only filesystem root available to tools.
- Path traversal and symlink escapes are rejected.
- Writes are disabled unless `MACPILOT_READ_ONLY=false` is explicitly set.
- Browser access requires an explicit domain allowlist:

  ```env
  MACPILOT_ALLOWED_BROWSER_DOMAINS=example.com,wikipedia.org
  ```

- Browser tools are read-only and do not submit forms, upload files, or send
  messages.
- Webpage text is treated as untrusted data. Instruction-like content is
  surfaced as a prompt-injection warning and cannot change system policy.
- High-risk plans pause in `waiting_approval` before execution.
- API keys are read from environment variables and must never be committed.

If Chromium is not installed for Playwright:

```bash
.venv/bin/playwright install chromium
```

## Phase 5 evaluation and optimization

Evaluation tasks are defined in `evals/tasks.json`: 10 local-file tasks, 15
web-research tasks, 10 document tasks, 8 failure-recovery tasks, and 7
security tasks.

The default evaluation is deterministic and offline. It does not make network
requests or require an API key:

```bash
.venv/bin/macpilot-evals --output data/evals/latest.json
# Or run one category:
.venv/bin/python evals/run_evals.py --category security
```

The command writes both JSON and Markdown reports. The offline report is a
policy/tool regression report, not a claim of live end-to-end model
performance. To aggregate real task traces from SQLite as well:

```bash
.venv/bin/macpilot-evals \
  --database data/macpilot.sqlite3 \
  --output data/evals/latest.json
```

Reports include task success rate, average steps, tool calls, recovery rate,
unauthorized actions, prompt-injection detection, citation correctness, token
usage, estimated cost, and cache hit rate. Cost estimates default to zero and
are only enabled when per-million-token prices are configured in `.env`.

Phase 5 also enables a local SQLite response cache and context budgeting by
default. Cache hits never bypass tools, approvals, or policy checks. Tune them
with:

```env
MACPILOT_CONTEXT_MAX_TOKENS=12000
MACPILOT_CACHE_ENABLED=true
MACPILOT_CACHE_TTL_SECONDS=86400
```

The latest generated report is available at:

- `data/evals/latest.json`
- `data/evals/latest.md`

## Tests

```bash
.venv/bin/pytest
```

## Desktop application

The Tauri + React desktop client is located in `apps/desktop`. It provides
task input, a workflow timeline, approval dialogs, result preview, task
cancellation, and a macOS tray entry point.

```bash
cd apps/desktop
npm install
npm run tauri dev
```

The desktop client connects to the local FastAPI server at
`http://127.0.0.1:8000` by default.

## Documentation

- [Architecture](docs/architecture.md)
- [3-minute demo script](docs/demo-script.md)
- [Release checklist](docs/release-checklist.md)
- [Project plan](plan.md)
