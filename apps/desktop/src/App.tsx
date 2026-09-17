import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";

const API_BASE = "http://127.0.0.1:8000";

type TaskStatus = "pending" | "running" | "waiting_approval" | "failed" | "completed" | "cancelled";

type Task = {
  id: string;
  user_goal: string;
  status: TaskStatus;
  plan: Record<string, unknown> | null;
};

type TimelineEvent = {
  id: string;
  event_type: string;
  payload: Record<string, unknown>;
  created_at: string;
};

type Step = {
  id: string;
  agent_name: string;
  status: string;
  started_at: string | null;
  finished_at: string | null;
};

type Approval = {
  id: string;
  action_type: string;
  risk_reason: string;
  preview: string;
  status: "pending" | "approved" | "rejected";
};

const statusText: Record<TaskStatus, string> = {
  pending: "待开始",
  running: "执行中",
  waiting_approval: "等待审批",
  failed: "失败",
  completed: "已完成",
  cancelled: "已终止",
};

const eventText: Record<string, string> = {
  task_created: "创建任务",
  task_started: "开始任务",
  user_message: "用户消息",
  agent_started: "开始执行角色",
  agent_finished: "角色完成",
  tool_call: "调用工具",
  waiting_approval: "等待审批",
  assistant_message: "Agent 回复",
  task_cancelled: "任务终止",
  error: "发生错误",
};

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!response.ok) {
    const detail = await response.text();
    throw new Error(detail || `请求失败：${response.status}`);
  }
  return response.json() as Promise<T>;
}

async function notify(title: string, body: string) {
  try {
    const module = await import("@tauri-apps/plugin-notification");
    await module.sendNotification({ title, body });
  } catch {
    if ("Notification" in window && Notification.permission === "granted") {
      new Notification(title, { body });
    }
  }
}

function App() {
  const [goal, setGoal] = useState("");
  const [task, setTask] = useState<Task | null>(null);
  const [events, setEvents] = useState<TimelineEvent[]>([]);
  const [steps, setSteps] = useState<Step[]>([]);
  const [approvals, setApprovals] = useState<Approval[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async (taskId: string) => {
    const [nextTask, nextEvents, nextSteps, nextApprovals] = await Promise.all([
      request<Task>(`/tasks/${taskId}`),
      request<TimelineEvent[]>(`/tasks/${taskId}/events`),
      request<Step[]>(`/tasks/${taskId}/steps`),
      request<Approval[]>(`/tasks/${taskId}/approvals`),
    ]);
    setTask(nextTask);
    setEvents(nextEvents);
    setSteps(nextSteps);
    setApprovals(nextApprovals);
  }, []);

  useEffect(() => {
    if (!task || !["running", "waiting_approval"].includes(task.status)) return;
    const timer = window.setInterval(() => {
      void refresh(task.id).catch((reason: Error) => setError(reason.message));
    }, 2000);
    return () => window.clearInterval(timer);
  }, [refresh, task]);

  const latestAnswer = useMemo(
    () => [...events].reverse().find((event) => event.event_type === "assistant_message"),
    [events],
  );
  const pendingApproval = approvals.find((approval) => approval.status === "pending");

  async function submit(event: FormEvent) {
    event.preventDefault();
    const content = goal.trim();
    if (!content || loading) return;
    setLoading(true);
    setError(null);
    try {
      let currentTask = task;
      if (!currentTask) {
        currentTask = await request<Task>("/tasks", {
          method: "POST",
          body: JSON.stringify({ user_goal: content }),
        });
        setTask(currentTask);
      }
      await request(`/tasks/${currentTask.id}/messages`, {
        method: "POST",
        body: JSON.stringify({ content }),
      });
      await refresh(currentTask.id);
      setGoal("");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "请求失败");
    } finally {
      setLoading(false);
    }
  }

  async function resume(status: "approved" | "rejected") {
    if (!task || loading) return;
    setLoading(true);
    setError(null);
    try {
      await request(`/tasks/${task.id}/resume`, {
        method: "POST",
        body: JSON.stringify({ status }),
      });
      await refresh(task.id);
      await notify(status === "approved" ? "MacPilot 已继续" : "MacPilot 已停止", "审批结果已处理");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "审批处理失败");
    } finally {
      setLoading(false);
    }
  }

  async function cancel() {
    if (!task || loading) return;
    setLoading(true);
    setError(null);
    try {
      await request(`/tasks/${task.id}/cancel`, { method: "POST" });
      await refresh(task.id);
      await notify("MacPilot 任务已终止", "任务不会继续提交外部动作");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "终止任务失败");
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="app-shell">
      <header className="topbar">
        <div>
          <p className="eyebrow">LOCAL-FIRST AGENT</p>
          <h1>MacPilot</h1>
        </div>
        <div className={`status status-${task?.status ?? "pending"}`} aria-live="polite">
          <span className="status-dot" aria-hidden="true" />
          {statusText[task?.status ?? "pending"]}
        </div>
      </header>

      <section className="goal-panel" aria-labelledby="goal-title">
        <div className="section-heading">
          <div>
            <p className="eyebrow">任务</p>
            <h2 id="goal-title">告诉 MacPilot 你要完成什么</h2>
          </div>
          {task && <span className="task-id">任务 {task.id.slice(0, 8)}</span>}
        </div>
        <form onSubmit={submit}>
          <label className="sr-only" htmlFor="goal">任务目标</label>
          <textarea
            id="goal"
            value={goal}
            onChange={(event) => setGoal(event.target.value)}
            onKeyDown={(event) => {
              if ((event.metaKey || event.ctrlKey) && event.key === "Enter") {
                event.preventDefault();
                event.currentTarget.form?.requestSubmit();
              }
            }}
            placeholder="例如：读取本地资料，生成项目摘要"
            rows={3}
            disabled={loading || task?.status === "cancelled"}
          />
          <div className="form-footer">
            <span className="hint">⌘ + Enter 发送 · 默认只读</span>
            <button className="primary-button" type="submit" disabled={loading || !goal.trim() || task?.status === "cancelled"}>
              {loading ? "处理中…" : task ? "继续发送" : "开始任务"}
            </button>
          </div>
        </form>
      </section>

      {error && <p className="error-banner" role="alert">{error}</p>}

      {pendingApproval && (
        <section className="approval-panel" aria-labelledby="approval-title">
          <div className="approval-icon" aria-hidden="true">!</div>
          <div className="approval-copy">
            <p className="eyebrow">需要你的决定</p>
            <h2 id="approval-title">任务准备执行高风险动作</h2>
            <p>{pendingApproval.risk_reason}</p>
            <details>
              <summary>查看动作预览</summary>
              <pre>{pendingApproval.preview}</pre>
            </details>
            <div className="approval-actions">
              <button type="button" className="secondary-button" onClick={() => void resume("rejected")} disabled={loading}>拒绝并停止</button>
              <button type="button" className="danger-button" onClick={() => void resume("approved")} disabled={loading}>批准继续</button>
            </div>
          </div>
        </section>
      )}

      <section className="content-grid">
        <section className="panel" aria-labelledby="timeline-title">
          <div className="section-heading">
            <div>
              <p className="eyebrow">可观察执行</p>
              <h2 id="timeline-title">任务时间线</h2>
            </div>
            {task && <button type="button" className="text-button" onClick={() => void refresh(task.id)}>刷新</button>}
          </div>
          {events.length === 0 ? (
            <p className="empty-state">提交任务后，这里会显示每一步执行记录。</p>
          ) : (
            <ol className="timeline" aria-live="polite">
              {events.map((item) => (
                <li key={item.id} className="timeline-item">
                  <span className="timeline-mark" aria-hidden="true" />
                  <div>
                    <strong>{eventText[item.event_type] ?? item.event_type}</strong>
                    <p>{formatEvent(item)}</p>
                    <time>{formatTime(item.created_at)}</time>
                  </div>
                </li>
              ))}
            </ol>
          )}
          {task && !["completed", "failed", "cancelled"].includes(task.status) && (
            <button type="button" className="stop-button" onClick={() => void cancel()} disabled={loading}>终止任务</button>
          )}
        </section>

        <aside className="side-column">
          <section className="panel result-panel" aria-labelledby="result-title">
            <p className="eyebrow">交付物</p>
            <h2 id="result-title">结果预览</h2>
            {latestAnswer ? <p className="result-text">{String(latestAnswer.payload.content ?? "")}</p> : <p className="empty-state">完成任务后，最终回答会显示在这里。</p>}
          </section>
          <section className="panel" aria-labelledby="steps-title">
            <p className="eyebrow">工作流</p>
            <h2 id="steps-title">执行角色</h2>
            <ul className="step-list">
              {(["Planner", "Researcher", "Critic", "Finalizer"] as const).map((name) => {
                const step = [...steps].reverse().find((item) => item.agent_name === name);
                return <li key={name}><span>{name}</span><span className={step ? `step-${step.status}` : "step-idle"}>{step ? step.status : "待执行"}</span></li>;
              })}
            </ul>
          </section>
        </aside>
      </section>
    </main>
  );
}

function formatTime(value: string) {
  return new Date(value).toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" });
}

function formatEvent(event: TimelineEvent) {
  if (event.event_type === "tool_call") return String(event.payload.tool_name ?? "执行工具");
  if (event.event_type === "agent_started" || event.event_type === "agent_finished") return String(event.payload.agent_name ?? "工作流节点");
  if (event.event_type === "error") return String(event.payload.message ?? "未知错误");
  if (event.event_type === "user_message") return String(event.payload.content ?? "");
  return event.event_type === "assistant_message" ? "已生成回复" : "状态已更新";
}

export default App;
