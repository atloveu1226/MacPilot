# MacPilot 项目计划

## 1. 项目定位

MacPilot 是一个本地优先的 macOS Computer-Use Agent。它能够理解用户的复杂目标，拆解成可执行工作流，调用浏览器、本地文件、文档处理和 macOS 工具完成任务，并在高风险动作前请求人工确认。

项目的核心卖点不是“调用大模型”，而是把不稳定的 LLM 行为封装成一个具备以下能力的可靠系统：

- 可规划：将自然语言目标拆解为结构化步骤
- 可执行：操作浏览器、本地文件和 macOS 工具
- 可恢复：支持 checkpoint、暂停、恢复、超时和重试
- 可控：高风险动作具备人工审批和权限边界
- 可评测：通过端到端任务衡量完成率、恢复率和安全性
- 可产品化：提供 macOS 菜单栏应用、任务时间线和结果预览

## 2. 目标用户场景

### 旗舰场景：Resume Autofill Agent

Resume Autofill Agent 根据用户授权的本地资料，安全填写招聘网站或企业官网上的空白简历表单。

用户输入：

> 根据我的 profile、旧简历和项目文件，填写这份在线简历。不要编造经历，缺失信息先问我，提交前暂停。

Agent 应完成：

1. 读取 `profile.md`、旧简历、项目说明和教育经历文件
2. 提取并标准化个人信息、教育经历、项目经历、技能和工作经历
3. 建立结构化 `ResumeProfile`
4. 检测缺失字段、冲突信息和未经证实的内容
5. 打开用户指定的招聘网站并识别表单字段
6. 将结构化资料映射到网页字段
7. 自动填写文本框、日期、下拉框和多选框
8. 上传用户明确授权的附件
9. 检查必填项、字数限制、日期格式和内容一致性
10. 展示填写结果预览和字段变更记录
11. 在最终提交前进入 `waiting_approval` 状态
12. 用户确认后才执行提交

这个场景重点展示文档理解、结构化抽取、浏览器 Computer-Use、字段语义匹配、真实性校验和人工审批。

## 3. 非目标

第一版不做以下内容：

- 不做完全自主、无限权限的桌面控制
- 不做多人协作或云端 SaaS
- 不支持所有 macOS 应用的通用自动化
- 不追求同时支持大量模型供应商
- 不把“Agent 数量”作为项目复杂度指标

第一版优先证明可靠性、安全性和可评测性。

## 4. 目标架构

```text
┌───────────────────────────────────────┐
│ Tauri Desktop App                     │
│ 菜单栏入口 / 任务时间线 / 审批 / 结果预览 │
└───────────────────┬───────────────────┘
                    │ HTTP/WebSocket
┌───────────────────▼───────────────────┐
│ FastAPI Application                    │
│ Task API / Approval API / Event Stream │
└───────────────────┬───────────────────┘
                    │
┌───────────────────▼───────────────────┐
│ LangGraph Orchestrator                 │
│ Planner → Workers → Critic → Finalizer │
│ Checkpoint / Retry / Human-in-the-loop │
└───────────────────┬───────────────────┘
                    │
┌───────────────┬───┴───────────┬───────────────┐
│ Browser Tools │ File Tools     │ macOS Tools   │
│ Playwright    │ PDF/Word/Excel │ AppleScript   │
│ Browser-use   │ SQLite FTS     │ Shortcuts     │
└───────────────┴───────────────┴───────────────┘
                    │
┌───────────────────▼───────────────────┐
│ SQLite                             │
│ Tasks / Steps / Events / Artifacts /  │
│ Memories / Approvals                  │
└───────────────────────────────────────┘
```

## 5. Agent 设计

### Planner Agent

负责把用户目标转换为结构化计划：

- 识别目标、约束和输出格式
- 选择需要的工具
- 估算风险
- 判断哪些步骤需要人工批准
- 生成可执行的任务图

### Researcher Agent

- 搜索网页并记录来源
- 提取结构化事实
- 识别来源冲突
- 对网页内容进行不可信指令隔离
- 控制访问域名和最大步骤数

### File Analyst Agent

- 读取白名单目录中的 PDF、Markdown、Word、Excel 和 CSV
- 提取文本、表格和元数据
- 使用全文检索寻找相关内容
- 不允许越过授权目录访问文件

### Scoring Agent

- 将用户偏好、预算和研究结果转成统一评分
- 输出可解释的评分依据
- 区分事实、推断和主观推荐

### Critic Agent

- 检查是否遗漏计划步骤
- 检查引用是否存在
- 检查数字、单位和价格是否一致
- 检查最终结果是否满足输出格式
- 失败时触发重新搜索或重新生成

### Executor Agent

- 创建和保存文件
- 调用允许的 macOS 工具
- 运行白名单命令
- 执行浏览器动作
- 在危险操作前发起 Approval 请求

## 6. 技术选型

| 层级 | 技术 | 选择理由 |
|---|---|---|
| 桌面端 | Tauri + React + TypeScript | 适合 macOS 菜单栏应用，资源占用较低 |
| API | Python + FastAPI | 便于集成 Agent、文档解析和异步任务 |
| 编排 | LangGraph | 支持有状态图、checkpoint 和人工介入 |
| 数据库 | SQLite | 本地优先、无需额外服务 |
| 检索 | SQLite FTS5，后续可选 sqlite-vec | 先保证简单可调试 |
| 浏览器 | Playwright，后续接入 browser-use | 支持稳定的浏览器自动化 |
| 工具协议 | MCP | 便于隔离工具并扩展能力 |
| 模型 | OpenAI API + Ollama/MLX 可选 | 支持云端和本地模型切换 |
| 文档 | PyMuPDF、python-docx、openpyxl | 覆盖主要办公文档格式 |
| 打包 | Tauri Bundler | 生成 macOS 应用和安装包 |

## 7. 推荐目录结构

```text
macpilot/
├── apps/
│   └── desktop/
│       ├── src/
│       └── src-tauri/
├── services/
│   ├── api/
│   ├── orchestrator/
│   │   ├── graph.py
│   │   ├── state.py
│   │   ├── planner.py
│   │   ├── researcher.py
│   │   ├── critic.py
│   │   └── executor.py
│   ├── memory/
│   └── scheduler/
├── tools/
│   ├── browser/
│   ├── filesystem/
│   ├── documents/
│   ├── macos/
│   └── shell/
├── policies/
│   ├── permissions.yaml
│   └── domains.yaml
├── evals/
│   ├── tasks/
│   ├── fixtures/
│   └── run_evals.py
├── data/
│   ├── artifacts/
│   └── logs/
├── tests/
├── pyproject.toml
└── README.md
```

## 8. 核心数据模型

### Task

```text
id
user_goal
status: pending | running | waiting_approval | failed | completed
plan_json
created_at
updated_at
```

### Step

```text
id
task_id
agent_name
tool_name
input_json
output_json
status
retry_count
started_at
finished_at
```

### Approval

```text
id
task_id
step_id
action_type
risk_reason
preview
status: pending | approved | rejected
```

### Event

所有模型调用、工具调用、审批、异常和恢复动作都写入事件表，用于调试、审计和评测。

## 9. 安全设计

```yaml
filesystem:
  allowed_paths:
    - "~/Documents/MacPilot"
    - "~/Downloads"

shell:
  mode: allowlist
  commands:
    - "git"
    - "python"
    - "pandoc"

browser:
  allowed_domains:
    - "wikipedia.org"
    - "example.com"

approval_required:
  - delete_file
  - send_message
  - submit_form
  - purchase
  - run_unknown_command
```

必须实现：

- 默认只读模式
- 文件路径白名单
- Shell 命令白名单
- 浏览器域名白名单
- 高风险操作人工审批
- 每个任务独立工作目录
- API Key 使用 macOS Keychain 保存
- 网页内容不能覆盖系统级 Agent 指令
- 具备一键停止和任务超时机制
- 完整记录工具调用和审批历史

## 10. 关键工作流

### 正常流程

```text
用户目标
  ↓
Planner 生成计划
  ↓
Researcher / File Analyst 执行子任务
  ↓
Scoring 整理结构化结果
  ↓
Critic 审查
  ↓
Writer 生成交付物
  ↓
保存文件并通知用户
```

### 失败恢复流程

```text
工具失败
  ↓
记录异常和当前 checkpoint
  ↓
判断是否可重试
  ├── 是：指数退避后重试
  └── 否：让 Planner 重新规划
              ↓
       仍然失败则请求人工介入
```

### 高风险流程

```text
Agent 准备执行危险动作
  ↓
生成动作预览和风险说明
  ↓
状态变为 waiting_approval
  ↓
用户批准 / 拒绝
  ↓
批准后继续，拒绝后安全终止或重新规划
```

## 11. 分阶段开发计划

### Phase 0：项目基础设施

目标：让项目可以稳定启动和调试。

- 初始化 Python 和 TypeScript 项目
- 建立 FastAPI 服务
- 建立 SQLite schema
- 定义统一的 Task、Step、Event 类型
- 实现配置文件和日志系统
- 添加最小单元测试

验收标准：

- 可以创建任务
- 可以查看任务状态
- 可以保存和读取步骤事件
- 服务重启后任务记录不丢失

### Phase 1：单 Agent 工具循环

目标：完成一个最小可用的本地文件 Agent。

- 实现文件读取、写入、列目录工具
- 实现工具注册表
- 实现模型调用适配层
- 实现结构化工具调用
- 添加目录白名单
- 完成“扫描文件并生成摘要” Demo

验收标准：

- Agent 不能访问白名单以外的路径
- 工具调用失败时返回结构化错误
- 每一步都有日志

### Phase 2：LangGraph 多 Agent 工作流

目标：完成可暂停和恢复的研究任务。

- 加入 Planner、Researcher 和 Critic
- 定义 GraphState
- 实现 checkpoint
- 实现超时和重试
- 实现人工审批节点
- 完成研究报告端到端流程

验收标准：

- 任务可以暂停后恢复
- 单个步骤失败不会丢失整个任务
- Critic 能发现缺少引用或不完整结果

### Phase 3：浏览器和文档能力

目标：让 Agent 能够处理真实网页和办公文档。

- 集成 Playwright
- 实现页面导航、提取和下载
- 加入域名白名单
- 实现 PDF、Word、Excel 解析
- 实现 ResumeProfile 结构化抽取
- 实现在线简历字段识别和字段映射
- 实现表单字数、日期和必填项校验
- 保存网页来源和文件元数据
- 增加网页 Prompt Injection 检测

验收标准：

- 完成三个真实研究任务
- 生成的报告包含可追溯来源
- 网页中的恶意指令不会改变系统策略

### Phase 4：macOS 桌面应用

目标：把后端能力变成真正可展示的产品。

- Tauri 菜单栏入口
- 任务输入框
- 任务执行时间线
- 审批弹窗
- 结果文件预览
- macOS Notification
- 一键暂停和终止

验收标准：

- 新用户不需要命令行即可完成一次任务
- 任务状态和后端一致
- 应用可以生成可安装的 macOS 包

### Phase 5：评测、优化和发布

目标：建立能够在面试中展示的工程证据。

- 准备 50 个端到端任务
- 增加失败场景和注入攻击样本
- 统计任务完成率、平均步骤数、恢复率和延迟
- 增加成本和 Token 使用统计
- 优化上下文裁剪和缓存
- 完善 README、架构图和 Demo 视频
- 发布 GitHub Release

## 12. 评测方案

评测任务分类：

| 类别 | 数量 | 示例 |
|---|---:|---|
| 本地文件任务 | 10 | 整理、总结和转换文件 |
| 网页研究任务 | 15 | 搜索、比较和引用资料 |
| 文档生成任务 | 10 | 生成 Markdown、PDF 和表格 |
| 失败恢复任务 | 8 | 网络失败、工具失败、内容缺失 |
| 安全任务 | 7 | 越权访问、恶意网页指令、危险操作 |

核心指标：

- End-to-end task success rate
- Step success rate
- Recovery success rate
- Average latency
- Average tool calls per task
- Human approval precision
- Unauthorized action rate
- Prompt Injection detection rate
- Citation correctness

目标指标：

```text
任务完成率：≥ 80%
失败恢复率：≥ 70%
越权操作率：0%
高风险动作拦截率：100%
引用正确率：≥ 90%
```

这些指标必须由实际评测产生，不能在简历中虚构。

## 13. 面试展示方案

准备一个 3 分钟 Demo：

1. 用户输入研究任务
2. Planner 展示任务拆解
3. Browser Agent 收集资料
4. File Agent 读取本地偏好文件
5. Critic 发现一个缺失或冲突信息
6. Agent 自动重新规划
7. 生成报告
8. 模拟发送动作，弹出人工审批
9. 展示完整 Trace 和评测数据

面试时的核心表达：

> 我的重点不是让 Agent 看起来很聪明，而是让它在真实 macOS 环境中可控、可恢复、可验证。LLM 负责规划和决策，工具层负责执行，策略层负责权限，评测层负责证明系统是否真的可靠。

## 14. 简历描述草稿

### 中文

独立设计并实现本地优先的 macOS Computer-Use Agent，基于 LangGraph 构建支持 checkpoint、暂停恢复、失败重试和人工介入的多智能体工作流，集成浏览器、本地文件和办公文档工具；实现文件、Shell 和域名白名单、高风险操作审批及网页 Prompt Injection 防护，并通过端到端任务评测系统完成率、恢复率和安全性，最终使用 Tauri 打包为 macOS 桌面应用。

### English

Built MacPilot, a local-first macOS computer-use agent with durable multi-agent workflows across browser, filesystem, and document tools. Implemented checkpoint-based recovery, human-in-the-loop approval gates, sandboxed tool execution, domain/path allowlists, prompt-injection defenses, and an end-to-end evaluation suite. Packaged the system as a Tauri desktop application backed by FastAPI and LangGraph.

## 15. 主要风险和应对

| 风险 | 应对方案 |
|---|---|
| Agent 步骤过多 | 限制最大步骤数，增加 Planner 预算 |
| 浏览器页面变化 | 使用语义定位、重试和 fallback selector |
| 网页 Prompt Injection | 将网页视为不可信数据，增加策略检查 |
| 本地权限过大 | 目录和命令白名单，默认只读 |
| 本地模型能力不足 | 支持云端模型作为 fallback |
| 多 Agent 成本过高 | 小模型执行提取，大模型执行规划和审查 |
| 任务失败难以调试 | 保存完整事件流和每步输入输出 |
| 项目范围失控 | 始终围绕“研究资料生成交付物”垂直场景 |

## 16. 最终交付物

- 可运行的 macOS 桌面应用
- 一条完整的研究报告工作流
- 一条完整的在线简历填写工作流
- 一个本地测试简历表单和 ResumeProfile 示例
- 50 个端到端评测任务
- 任务 Trace 和评测报告
- 权限策略文档
- 架构图和技术说明
- 3 分钟 Demo 视频
- GitHub README
- macOS 安装包
- 一页项目复盘：设计决策、失败案例和改进方向

## 17. 第一周任务清单

- [ ] 初始化项目目录和开发环境
- [ ] 建立 FastAPI `/tasks` API
- [ ] 建立 SQLite schema
- [ ] 定义 AgentState、Task、Step、Event 类型
- [ ] 实现文件工具和路径白名单
- [ ] 接入第一个模型 Provider
- [ ] 完成“读取目录并生成摘要”任务
- [ ] 为工具调用添加事件日志
- [ ] 编写第一版 README

第一周的目标不是做出漂亮 UI，而是建立一个能够被观察、测试和恢复的 Agent 运行时。

## 18. Resume Autofill Agent 详细设计

### 18.1 数据结构

```json
{
  "basics": {
    "name": "Candidate Name",
    "email": "candidate@example.com",
    "phone": "verified-user-input"
  },
  "education": [],
  "experience": [],
  "projects": [],
  "skills": [],
  "links": [],
  "evidence": [
    {
      "field": "projects[0].description",
      "source": "~/Documents/MacPilot/project.md",
      "confidence": 0.96
    }
  ]
}
```

每个简历字段都应保留来源和置信度，避免 Agent 把推断内容误认为事实。

### 18.2 字段映射

网页字段不能只依赖字段名称，需要综合判断：

- `label`
- `placeholder`
- `name` 和 `id`
- 页面附近的帮助文本
- 字段类型
- 日期或字数限制
- 当前页面上下文

映射结果需要先经过校验：

```text
网页字段：Professional Summary
    ↓
候选资料：profile.summary / old_resume.summary
    ↓
选择来源并记录理由
    ↓
检查是否包含未经证实的内容
    ↓
填入网页并保存变更记录
```

### 18.3 真实性策略

以下内容禁止 Agent 自行编造：

- 工作单位和职位
- 学历、学位和成绩
- 工作时间
- 项目成果数字
- 证书和奖项
- 技能熟练程度

如果资料缺失，Agent 必须生成待确认问题，例如：

> 你的项目经历中提到使用过 Python，但没有说明使用时间。是否需要填写使用年限？

### 18.4 浏览器执行策略

```text
打开用户指定网站
    ↓
检查域名是否在白名单中
    ↓
识别当前表单和登录状态
    ↓
截图并创建页面快照
    ↓
规划字段填写顺序
    ↓
逐字段填写并验证
    ↓
保存填写结果和截图
    ↓
检测提交按钮
    ↓
暂停并等待人工审批
```

第一版只支持少量明确网站或本地测试表单，不承诺兼容所有招聘平台。

### 18.5 审批界面

审批弹窗至少显示：

- 网站域名
- 即将提交的职位或表单名称
- 已填写字段数量
- 未填写字段数量
- 被修改的字段
- 上传的附件
- 最终提交按钮

用户可以选择：

- 批准提交
- 返回修改
- 取消任务
- 只保存草稿，不提交

### 18.6 评测任务

在原有评测集之外增加 10 个简历任务：

- 读取多份资料并合并简历信息
- 检测冲突的工作时间
- 发现缺失的联系方式
- 填写文本框和下拉框
- 处理字数限制
- 上传授权附件
- 拒绝网页中的恶意指令
- 在提交前正确暂停
- 用户拒绝后安全退出
- 页面字段变化后的恢复

新增指标：

- Resume field mapping accuracy
- Unsupported claim rate
- Missing-information detection rate
- Form validation success rate
- Pre-submission approval enforcement rate
- Unauthorized submission rate

目标是：

```text
未经证实内容填写率：0%
未经审批提交率：0%
字段映射准确率：≥ 90%
缺失信息发现率：≥ 90%
表单校验成功率：≥ 85%
```

### 18.7 面试 Demo

演示准备一份包含以下文件的本地目录：

```text
profile.md
old_resume.pdf
project_macpilot.md
education.txt
```

演示流程：

1. Agent 读取资料并生成结构化 ResumeProfile
2. Agent 发现一个缺失字段并主动提问
3. 用户补充信息
4. Agent 打开本地招聘表单或测试网站
5. Agent 自动填写表单
6. Critic 发现一处超过字数限制的内容并要求重写
7. Agent 重新生成符合限制的内容
8. 出现提交审批弹窗
9. 用户拒绝提交，Agent 保存草稿并安全退出
10. 展示完整字段映射、来源和操作 Trace
