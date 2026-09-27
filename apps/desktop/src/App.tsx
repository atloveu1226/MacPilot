import { FormEvent, useCallback, useEffect, useState } from "react";

const API_BASE = "http://127.0.0.1:8000";

type TaskStatus = "pending" | "running" | "waiting_approval" | "failed" | "completed" | "cancelled";

type Task = {
  id: string;
  session_id: string;
  user_goal: string;
  status: TaskStatus;
  plan: Record<string, unknown> | null;
};

type Session = {
  id: string;
  title: string;
  status: string;
  updated_at: string;
  archived_at: string | null;
};

type ChatMessage = {
  id: string;
  role: "user" | "assistant";
  content: string;
  created_at: string;
};

type Approval = {
  id: string;
  action_type: string;
  risk_reason: string;
  preview: string;
  status: "pending" | "approved" | "rejected";
};

type UploadedFile = {
  name: string;
  original_name?: string;
  path: string;
  size: number;
  format: string;
};

const ACCEPTED_EXTENSIONS = [".pdf", ".docx", ".xlsx", ".xlsm", ".txt", ".md", ".csv", ".json", ".yaml", ".yml"];
const MAX_FILE_BYTES = 200_000;

const statusText: Record<TaskStatus, string> = {
  pending: "待开始",
  running: "执行中",
  waiting_approval: "等待审批",
  failed: "失败",
  completed: "已完成",
  cancelled: "已终止",
};

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const isMultipart = init?.body instanceof FormData;
  const response = await fetch(`${API_BASE}${path}`, {
    headers: isMultipart ? init?.headers : { "Content-Type": "application/json", ...init?.headers },
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
  const [sessions, setSessions] = useState<Session[]>([]);
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [goal, setGoal] = useState("");
  const [task, setTask] = useState<Task | null>(null);
  const [approvals, setApprovals] = useState<Approval[]>([]);
  const [pendingFiles, setPendingFiles] = useState<File[]>([]);
  const [uploadedFiles, setUploadedFiles] = useState<UploadedFile[]>([]);
  const [uploadingFiles, setUploadingFiles] = useState<string[]>([]);
  const [dragActive, setDragActive] = useState(false);
  const [fileError, setFileError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [conclusion, setConclusion] = useState("");

  const selectSession = useCallback(async (sessionId: string) => {
    setActiveSessionId(sessionId);
    setGoal("");
    setTask(null);
    setApprovals([]);
    setPendingFiles([]);
    setUploadedFiles([]);
    setFileError(null);
    setConclusion("");
    try {
      const [nextTask, nextMessages] = await Promise.all([
        request<Task | null>(`/sessions/${sessionId}/task`),
        request<ChatMessage[]>(`/sessions/${sessionId}/messages`),
      ]);
      setTask(nextTask);
      setMessages(nextMessages);
      if (nextTask) {
        const [nextApprovals] = await Promise.all([
          request<Approval[]>(`/tasks/${nextTask.id}/approvals`),
        ]);
        setApprovals(nextApprovals);
      }
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "会话加载失败");
    }
  }, []);

  useEffect(() => {
    void (async () => {
      try {
        const nextSessions = await request<Session[]>("/sessions");
        setSessions(nextSessions);
        if (nextSessions.length > 0) await selectSession(nextSessions[0].id);
      } catch (reason) {
        setError(reason instanceof Error ? reason.message : "会话加载失败");
      }
    })();
  }, [selectSession]);

  async function createNewSession() {
    if (loading) return;
    try {
      const created = await request<Session>("/sessions", {
        method: "POST",
        body: JSON.stringify({ title: "新会话" }),
      });
      setSessions((current) => [created, ...current]);
      await selectSession(created.id);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "新建会话失败");
    }
  }

  async function ensureSession(): Promise<string> {
    if (activeSessionId) return activeSessionId;
    const created = await request<Session>("/sessions", {
      method: "POST",
      body: JSON.stringify({ title: "新会话" }),
    });
    setSessions((current) => [created, ...current]);
    setActiveSessionId(created.id);
    return created.id;
  }

  async function deleteSession(session: Session) {
    if (loading) return;
    const confirmed = window.confirm(
      `确定删除“${session.title}”吗？\n\n这会同时删除会话记录、上传文件和对应的 RAG 索引，且无法恢复。`,
    );
    if (!confirmed) return;
    setLoading(true);
    setError(null);
    try {
      await request(`/sessions/${session.id}`, { method: "DELETE" });
      const remaining = sessions.filter((item) => item.id !== session.id);
      if (session.id === activeSessionId) {
        if (remaining.length > 0) {
          setSessions(remaining);
          await selectSession(remaining[0].id);
        } else {
          setSessions([]);
          setActiveSessionId(null);
          setTask(null);
          setMessages([]);
          setApprovals([]);
          setPendingFiles([]);
          setUploadedFiles([]);
          setConclusion("");
        }
      } else {
        setSessions(remaining);
      }
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "删除会话失败");
    } finally {
      setLoading(false);
    }
  }

  const refresh = useCallback(async (taskId: string) => {
    const [nextTask, nextApprovals] = await Promise.all([
      request<Task>(`/tasks/${taskId}`),
      request<Approval[]>(`/tasks/${taskId}/approvals`),
    ]);
    setTask(nextTask);
    setApprovals(nextApprovals);
  }, []);
  const pendingApproval = approvals.find((approval) => approval.status === "pending");

  function fileKey(file: File) {
    return `${file.name}:${file.size}:${file.lastModified}`;
  }

  async function addFiles(files: FileList | File[]) {
    if (loading) return;
    setFileError(null);
    const incoming = Array.from(files);
    const invalid = incoming.find((file) => {
      const extension = `.${file.name.split(".").pop()?.toLowerCase() ?? ""}`;
      return !ACCEPTED_EXTENSIONS.includes(extension) || file.size > MAX_FILE_BYTES;
    });
    if (invalid) {
      const extension = `.${invalid.name.split(".").pop()?.toLowerCase() ?? ""}`;
      setFileError(
        !ACCEPTED_EXTENSIONS.includes(extension)
          ? `不支持 ${extension || "该文件"}。请上传 PDF、Word、Excel 或文本文件。`
          : `${invalid.name} 超过 200 KB 限制。`,
      );
      return;
    }
    const existing = new Set([
      ...pendingFiles.map(fileKey),
      ...uploadedFiles.map((file) => `${file.original_name ?? file.name}:${file.size}:uploaded`),
    ]);
    const selected = incoming.filter((file) => !existing.has(fileKey(file)));
    if (selected.length === 0) return;

    setPendingFiles((current) => [...current, ...selected]);
    setLoading(true);
    try {
      const sessionId = await ensureSession();
      let currentTask = task;
      if (!currentTask) {
        currentTask = await request<Task>("/tasks", {
          method: "POST",
          body: JSON.stringify({
            user_goal: goal.trim() || "分析上传的资料",
            session_id: sessionId,
          }),
        });
        setTask(currentTask);
      }
      for (const file of selected) {
        const key = fileKey(file);
        setUploadingFiles((current) => [...current, key]);
        try {
          const formData = new FormData();
          formData.append("file", file);
          const uploaded = await request<UploadedFile>(`/tasks/${currentTask.id}/files`, {
            method: "POST",
            body: formData,
          });
          setUploadedFiles((current) => [...current, uploaded]);
          setPendingFiles((current) => current.filter((item) => item !== file));
        } finally {
          setUploadingFiles((current) => current.filter((item) => item !== key));
        }
      }
      await refresh(currentTask.id);
    } catch (reason) {
      setFileError(reason instanceof Error ? reason.message : "文件上传失败");
    } finally {
      setLoading(false);
    }
  }

  function removePendingFile(file: File) {
    setPendingFiles((current) => current.filter((item) => item !== file));
  }

  async function streamTask(taskId: string, content: string, sessionId: string) {
    const response = await fetch(`${API_BASE}/tasks/${taskId}/messages/stream`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ content }),
    });
    if (!response.ok) {
      throw new Error((await response.text()) || `请求失败：${response.status}`);
    }
    if (!response.body) throw new Error("服务器没有返回流式内容");

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    while (true) {
      const { value, done } = await reader.read();
      buffer += decoder.decode(value ?? new Uint8Array(), { stream: !done });
      const blocks = buffer.split("\n\n");
      buffer = blocks.pop() ?? "";
      for (const block of blocks) {
        const eventName = block.match(/^event: (.+)$/m)?.[1];
        const dataLine = block.match(/^data: (.+)$/m)?.[1];
        if (!eventName || !dataLine) continue;
        const data = JSON.parse(dataLine) as Record<string, unknown>;
        if (eventName === "conclusion") {
          setConclusion((current) => current + String(data.delta ?? ""));
        } else if (eventName === "approval") {
          // Approval details are shown in the dedicated approval panel.
        } else if (eventName === "error") {
          throw new Error(String(data.message ?? "Agent 执行失败"));
        } else if (eventName === "done" && data.task) {
          setTask(data.task as Task);
        }
      }
      if (done) break;
    }
    await refresh(taskId);
    const nextMessages = await request<ChatMessage[]>(`/sessions/${sessionId}/messages`);
    setMessages(nextMessages);
    setSessions(await request<Session[]>("/sessions"));
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    const content = goal.trim();
    if (!content || loading) return;
    setLoading(true);
    setError(null);
    setConclusion("");
    const displayContent = content;
    const optimisticMessage: ChatMessage = {
      id: `pending-${Date.now()}`,
      role: "user",
      content: displayContent,
      created_at: new Date().toISOString(),
    };
    setMessages((current) => [...current, optimisticMessage]);
    setGoal("");
    setPendingFiles([]);
    setUploadedFiles([]);
    try {
      const sessionId = await ensureSession();
      let currentTask = task;
      if (!currentTask) {
        currentTask = await request<Task>("/tasks", {
          method: "POST",
          body: JSON.stringify({ user_goal: content, session_id: sessionId }),
        });
        setTask(currentTask);
      }
      await streamTask(currentTask.id, displayContent, sessionId);
    } catch (reason) {
      setMessages((current) => current.filter((message) => message.id !== optimisticMessage.id));
      setGoal(content);
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
      <aside className="session-sidebar" aria-label="会话列表">
        <div className="sidebar-brand">
          <div>
            <p className="eyebrow">LOCAL-FIRST AGENT</p>
            <h1>MacPilot</h1>
          </div>
          <button type="button" className="new-session-button" onClick={() => void createNewSession()} disabled={loading} aria-label="新建会话" title="新建会话">＋</button>
        </div>
        <div className="sidebar-label">会话</div>
        <nav className="session-list">
          {sessions.length === 0 ? (
            <p className="sidebar-empty">暂无会话<br />点击右上角 ＋ 新建</p>
          ) : sessions.map((item) => (
            <div className={`session-row${activeSessionId === item.id ? " session-row-active" : ""}`} key={item.id}>
              <button
                type="button"
                className="session-item"
                onClick={() => void selectSession(item.id)}
                disabled={loading}
              >
                <span className="session-title">{item.title}</span>
                <span className="session-date">{formatSessionDate(item.updated_at)}</span>
              </button>
              <button
                type="button"
                className="session-delete"
                onClick={(event) => {
                  event.stopPropagation();
                  void deleteSession(item);
                }}
                disabled={loading}
                aria-label={`删除会话 ${item.title}`}
                title="删除会话"
              >×</button>
            </div>
          ))}
        </nav>
      </aside>

      <section className="workspace">
      <header className="topbar">
        <div>
          <p className="eyebrow">当前会话</p>
          <h1>{sessions.find((item) => item.id === activeSessionId)?.title ?? "未选择会话"}</h1>
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
          <div
            className={`composer${dragActive ? " composer-active" : ""}`}
            onDragEnter={(event) => {
              event.preventDefault();
              setDragActive(true);
            }}
            onDragOver={(event) => event.preventDefault()}
            onDragLeave={(event) => {
              event.preventDefault();
              if (!event.currentTarget.contains(event.relatedTarget as Node | null)) setDragActive(false);
            }}
            onDrop={(event) => {
              event.preventDefault();
              setDragActive(false);
              void addFiles(event.dataTransfer.files);
            }}
          >
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
              placeholder="输入问题，或把资料拖到这里一起分析"
              rows={3}
              disabled={loading || task?.status === "cancelled"}
            />
            <input
              id="file-input"
              className="file-input"
              type="file"
              multiple
              disabled={loading}
              accept={ACCEPTED_EXTENSIONS.join(",")}
              onChange={(event) => {
                if (event.target.files) void addFiles(event.target.files);
                event.currentTarget.value = "";
              }}
            />
            {(pendingFiles.length > 0 || uploadedFiles.length > 0) && (
              <ul className="composer-files" aria-label="已添加的资料">
                {pendingFiles.map((file) => (
                  <li key={`${file.name}:${file.lastModified}`} className="composer-file">
                    <span className="file-chip-icon" aria-hidden="true">↗</span>
                    <span className="composer-file-name">{file.name}</span>
                    <small>{uploadingFiles.includes(fileKey(file)) ? "上传中…" : "等待上传"}</small>
                    <button type="button" className="remove-file" onClick={() => removePendingFile(file)} disabled={uploadingFiles.includes(fileKey(file))} aria-label={`移除 ${file.name}`}>×</button>
                  </li>
                ))}
                {uploadedFiles.map((file) => (
                  <li key={file.path} className="composer-file composer-file-uploaded">
                    <span className="file-chip-icon" aria-hidden="true">✓</span>
                    <span className="composer-file-name">{file.original_name ?? file.name}</span>
                    <small>已添加</small>
                  </li>
                ))}
              </ul>
            )}
            {fileError && <p className="field-error" role="alert">{fileError}</p>}
            <div className="form-footer">
              <div className="composer-tools">
                <label className="upload-button" htmlFor="file-input" title="上传资料" aria-label="上传资料">
                  <span aria-hidden="true">↑</span>
                  <span className="sr-only">上传资料</span>
                </label>
                <span className="hint">拖入资料，或点击 ↑ 上传 · ⌘ + Enter 发送</span>
              </div>
              <button className="primary-button" type="submit" disabled={loading || !goal.trim() || task?.status === "cancelled"}>
                {loading ? "处理中…" : task ? "发送" : "开始任务"}
              </button>
            </div>
          </div>
        </form>
      </section>

      {error && <p className="error-banner" role="alert">{error}</p>}

      {messages.length > 0 && (
        <section className="conversation-panel" aria-label="会话记录">
          {messages.map((message) => (
            <article key={message.id} className={`message message-${message.role}`}>
              <span className="message-role">{message.role === "user" ? "你" : "MacPilot"}</span>
              <p>{message.content}</p>
            </article>
          ))}
        </section>
      )}

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

      </section>
    </main>
  );
}

function formatBytes(value: number) {
  return value < 1024 ? `${value} B` : `${(value / 1024).toFixed(1)} KB`;
}

function formatSessionDate(value: string) {
  return new Date(value).toLocaleDateString("zh-CN", { month: "numeric", day: "numeric" });
}

export default App;
