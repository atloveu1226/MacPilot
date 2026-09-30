import { useEffect, useMemo, useState, type Dispatch, type SetStateAction } from "react";

type Section = "基本信息" | "教育经历" | "工作经历" | "项目经历" | "技能特长" | "证书与荣誉" | "自我评价";
type FormState = Record<string, string>;
type RepeatItem = { id: string; [key: string]: string };

function joinDistinct(values: Array<string | undefined>, separator = " · ") {
  return [...new Set(values.filter((value): value is string => Boolean(value && value.trim())))].join(separator);
}

function educationLabel(item: Record<string, string>) {
  return joinDistinct([item.field_of_study, item.school, item.degree]);
}

const API_BASE = "http://127.0.0.1:8000";
const sections: { name: Section; icon: string; fields: { key: string; label: string; placeholder: string; wide?: boolean }[] }[] = [
  { name: "基本信息", icon: "◎", fields: [{ key: "name", label: "姓名", placeholder: "例如：林晓川" }, { key: "role", label: "目标职位", placeholder: "例如：产品设计师" }, { key: "email", label: "邮箱", placeholder: "name@example.com" }, { key: "phone", label: "电话", placeholder: "+86 138 0000 0000" }, { key: "location", label: "所在城市", placeholder: "例如：上海" }, { key: "links", label: "个人链接", placeholder: "LinkedIn / GitHub / 作品集" }] },
  { name: "教育经历", icon: "▣", fields: [{ key: "education", label: "专业与学校", placeholder: "例如：交互设计 · 同济大学 · 硕士" }, { key: "education_period", label: "时间", placeholder: "例如：2021.09 — 2024.06" }, { key: "education_detail", label: "补充说明", placeholder: "课程、成绩或相关活动（可选）", wide: true }] },
  { name: "工作经历", icon: "▤", fields: [{ key: "work_company", label: "公司与职位", placeholder: "例如：澄明科技 · 高级产品设计师" }, { key: "work_period", label: "时间", placeholder: "例如：2023.06 — 至今" }, { key: "work_detail", label: "工作内容与成果", placeholder: "描述职责、影响和可量化成果", wide: true }] },
  { name: "项目经历", icon: "◇", fields: [{ key: "project_name", label: "项目名称", placeholder: "例如：企业协作平台 2.0" }, { key: "project_period", label: "项目时间", placeholder: "例如：2024.03 — 2024.08" }, { key: "project_role", label: "项目角色", placeholder: "例如：负责人 / 产品设计" }, { key: "project_detail", label: "项目介绍", placeholder: "目标、行动、结果与使用的工具或技术", wide: true }] },
  { name: "技能特长", icon: "✦", fields: [{ key: "skills", label: "技能与工具", placeholder: "例如：Figma、用户研究、原型设计、Python", wide: true }] },
  { name: "证书与荣誉", icon: "♢", fields: [{ key: "honors", label: "证书与荣誉", placeholder: "例如：英语六级、校级一等奖学金", wide: true }] },
  { name: "自我评价", icon: "≋", fields: [{ key: "summary", label: "自我评价", placeholder: "用 2–3 句话介绍你的优势、工作方式和职业方向", wide: true }] },
];

function RepeatableEditor({ items, fields, onChange, onAdd, onRemove }: { items: RepeatItem[]; fields: { key: string; label: string; placeholder: string; wide?: boolean }[]; onChange: (id: string, key: string, value: string) => void; onAdd: () => void; onRemove: (id: string) => void }) {
  return <div className="repeatable-list">{items.map((item, index) => <div className="repeatable-card" key={item.id}><div className="repeatable-head"><strong>第 {index + 1} 条</strong>{items.length > 1 && <button type="button" className="remove-entry" onClick={() => onRemove(item.id)}>删除</button>}</div><div className="fields-grid">{fields.map((field) => <label className={field.wide ? "field wide" : "field"} key={field.key}><span>{field.label}</span>{field.wide ? <textarea value={item[field.key] ?? ""} onChange={(event) => onChange(item.id, field.key, event.target.value)} placeholder={field.placeholder} rows={4} /> : <input value={item[field.key] ?? ""} onChange={(event) => onChange(item.id, field.key, event.target.value)} placeholder={field.placeholder} />}</label>)}</div></div>)}<button type="button" className="add-entry" onClick={onAdd}>＋ 添加一条经历</button></div>;
}

function App() {
  const [active, setActive] = useState<Section>("基本信息");
  const [values, setValues] = useState<FormState>({});
  const [preview, setPreview] = useState(false);
  const [notice, setNotice] = useState("填写完成后可生成预览，内容只在当前设备处理。");
  const [url, setUrl] = useState("");
  const [domain, setDomain] = useState("");
  const [domainState, setDomainState] = useState<"idle" | "checking" | "approval" | "allowed" | "error">("idle");
  const [uploadTaskId, setUploadTaskId] = useState<string | null>(null);
  const [uploadedFile, setUploadedFile] = useState<string | null>(null);
  const [uploadState, setUploadState] = useState<"idle" | "uploading" | "ready" | "parsing" | "done" | "error">("idle");
  const [webState, setWebState] = useState<"idle" | "running" | "done" | "error">("idle");
  const [parseProgress, setParseProgress] = useState(0);
  const [educationEntries, setEducationEntries] = useState<RepeatItem[]>([{ id: "education-1", school: "", period: "", detail: "" }]);
  const [projectEntries, setProjectEntries] = useState<RepeatItem[]>([{ id: "project-1", name: "", period: "", role: "", detail: "" }]);
  useEffect(() => { const entries = values.education_entries; if (Array.isArray(entries) && entries.length > 0) setEducationEntries(entries as unknown as RepeatItem[]); }, [values.education_entries]);
  const repeatableFilled = useMemo(() => educationEntries.reduce((count, item) => count + Object.entries(item).filter(([key, value]) => key !== "id" && Boolean(value)).length, 0) + projectEntries.reduce((count, item) => count + Object.entries(item).filter(([key, value]) => key !== "id" && Boolean(value)).length, 0), [educationEntries, projectEntries]);
  const repeatableTotal = educationEntries.length * 3 + projectEntries.length * 4;
  const filled = Object.values(values).filter(Boolean).length + repeatableFilled;
  const total = sections.reduce((sum, item) => sum + item.fields.length, 0) + repeatableTotal;
  const missing = useMemo(() => sections.flatMap((section) => section.fields.filter((field) => !values[field.key]).map((field) => field.label)), [values]);
  function sectionProgress(section: { name: Section; fields: { key: string }[] }) {
    if (section.name === "教育经历") return `${educationEntries.reduce((count, item) => count + Object.entries(item).filter(([key, value]) => key !== "id" && Boolean(value)).length, 0)}/${educationEntries.length * 3}`;
    if (section.name === "项目经历") return `${projectEntries.reduce((count, item) => count + Object.entries(item).filter(([key, value]) => key !== "id" && Boolean(value)).length, 0)}/${projectEntries.length * 4}`;
    return `${section.fields.filter((field) => values[field.key]).length}/${section.fields.length}`;
  }
  function update(key: string, value: string) { setValues((current) => ({ ...current, [key]: value })); }
  function clearAll() { setValues({}); setPreview(false); setNotice("已清空所有内容，可以重新填写。"); }
  function generatePreview() { setPreview(true); setNotice(missing.length ? `预览已生成，还有 ${missing.length} 个字段未填写。` : "预览已生成，所有字段均已填写。"); }
  function updateRepeat(items: RepeatItem[], setItems: Dispatch<SetStateAction<RepeatItem[]>>, id: string, key: string, value: string) { setItems(items.map((item) => item.id === id ? { ...item, [key]: value } : item)); }
  async function checkDomain() { setDomainState("checking"); try { const response = await fetch(`${API_BASE}/browser/domains/check`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ url }) }); if (!response.ok) throw new Error(); const result = await response.json() as { domain: string; allowed: boolean; requires_approval: boolean }; setDomain(result.domain); setDomainState(result.allowed ? "allowed" : result.requires_approval ? "approval" : "error"); } catch { setDomainState("error"); } }
  async function approveDomain() { const response = await fetch(`${API_BASE}/browser/domains/approve`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ domain }) }); if (response.ok) { setDomainState("allowed"); setNotice(`已临时授权 ${domain}，Agent 可以继续访问。`); } else setDomainState("error"); }
  async function uploadResume(file: File) {
    if (!/[.]((pdf)|(docx)|(txt)|(md))$/i.test(file.name) && !file.type) { setUploadState("error"); setNotice("仅支持 PDF、Word 或文本简历。"); return; }
    setUploadState("uploading");
    try {
      const taskResponse = await fetch(`${API_BASE}/tasks`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ user_goal: "读取上传的简历，提取基本信息、教育经历、工作经历、项目经历、技能特长和证书荣誉" }) });
      if (!taskResponse.ok) throw new Error();
      const task = await taskResponse.json() as { id: string };
      const body = new FormData(); body.append("file", file, file.name || "resume.pdf");
      const uploadResponse = await fetch(`${API_BASE}/tasks/${task.id}/files`, { method: "POST", body });
      if (!uploadResponse.ok) { const error = await uploadResponse.json().catch(() => ({})) as { detail?: string }; throw new Error(error.detail || `上传失败（${uploadResponse.status}）`); }
      setUploadTaskId(task.id); setUploadedFile(file.name); setUploadState("ready");
      setNotice("简历已上传，点击解析后由 CV Extractor 生成 ResumeProfile。");
    } catch (error) { setUploadState("error"); setNotice(error instanceof Error ? error.message : "上传失败，请确认本地 Agent 服务已启动。"); }
  }
  async function parseResume() {
    if (!uploadTaskId) return;
    setUploadState("parsing"); setParseProgress(8); setNotice("CV Extractor 正在读取简历…");
    try {
      const response = await fetch(`${API_BASE}/tasks/${uploadTaskId}/messages/stream`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ content: "请先使用 CV Extractor 读取上传的简历，再由 Resume Form Filler 根据 ResumeProfile 回填本地简历表单。只返回 FORM_FILL_RESULT JSON，不要填写网页。" }) });
      if (!response.ok || !response.body) throw new Error("Extractor 请求失败");
      const reader = response.body.getReader(); const decoder = new TextDecoder(); let buffer = ""; let conclusion = "";
      while (true) {
        const { value, done } = await reader.read(); buffer += decoder.decode(value ?? new Uint8Array(), { stream: !done });
        const blocks = buffer.split("\n\n"); buffer = blocks.pop() ?? "";
        for (const block of blocks) {
          const event = block.match(/^event: (.+)$/m)?.[1]; const dataLine = block.match(/^data: (.+)$/m)?.[1]; if (!event || !dataLine) continue;
          const data = JSON.parse(dataLine) as Record<string, unknown>;
          if (event === "thinking") { setNotice(String(data.message ?? "Agent 正在处理…")); setParseProgress(42); }
          if (event === "conclusion") { conclusion += String(data.delta ?? ""); setParseProgress(84); }
          if (event === "error") throw new Error(String(data.message ?? "Extractor 解析失败"));
        }
        if (done) break;
      }
      const parsed = JSON.parse(conclusion) as { form_mapping?: { basics?: FormState; education_entries?: Array<Record<string, string>>; work?: Record<string, string>; project_entries?: Array<Record<string, string>> }; basics?: FormState; education?: Array<Record<string, string>>; experience?: Array<Record<string, string>>; projects?: Array<Record<string, string | string[]>>; skills?: string[] };
      const mapping = parsed.form_mapping;
      if (mapping) {
        const basics = mapping.basics ?? {};
        const education = Array.isArray(mapping.education_entries) ? mapping.education_entries : [];
        const projects = Array.isArray(mapping.project_entries) ? mapping.project_entries : [];
        setEducationEntries(education.map((item, index) => ({ id: `education-agent-${index}`, school: String(item.school ?? ""), period: String(item.period ?? ""), detail: String(item.detail ?? "") })));
        setProjectEntries(projects.map((item, index) => ({ id: `project-agent-${index}`, name: String(item.name ?? ""), period: String(item.period ?? ""), role: String(item.role ?? ""), detail: String(item.detail ?? "") })));
        setValues((current) => ({ ...current, name: basics.name ?? current.name, email: basics.email ?? current.email, phone: basics.phone ?? current.phone, location: basics.location ?? current.location, role: basics.role ?? current.role, links: basics.links ?? current.links, summary: basics.summary ?? current.summary, skills: basics.skills ?? current.skills, honors: basics.honors ?? current.honors, work_company: mapping.work?.company ?? current.work_company, work_period: mapping.work?.period ?? current.work_period, work_detail: mapping.work?.detail ?? current.work_detail }));
        setParseProgress(100); setUploadState("done"); setNotice("CV Extractor + Resume Form Filler 已完成本地表单回填。");
      } else {
        const basics = parsed.basics ?? {}; const education = Array.isArray(parsed.education) ? parsed.education : []; const experience = Array.isArray(parsed.experience) ? parsed.experience : []; const projects = Array.isArray(parsed.projects) ? parsed.projects : [];
        if (education.length) setEducationEntries(education.map((item, index) => ({ id: `education-agent-${index}`, school: educationLabel(item), period: joinDistinct([item.start_date, item.end_date], " — "), detail: item.details ?? "" })));
        if (projects.length) setProjectEntries(projects.map((item, index) => ({ id: `project-agent-${index}`, name: String(item.name ?? ""), period: [item.start_date, item.end_date].filter(Boolean).join(" — "), role: String(item.role ?? ""), detail: [item.description, ...(Array.isArray(item.outcomes) ? item.outcomes : [])].filter(Boolean).join("\n") })));
        setValues((current) => ({ ...current, name: basics.name ?? current.name, email: basics.email ?? current.email, phone: basics.phone ?? current.phone, location: basics.location ?? current.location, role: basics.target_role ?? current.role, summary: basics.summary ?? current.summary, skills: (parsed.skills ?? []).join("、") || current.skills, work_company: experience.map((item) => [item.company, item.title].filter(Boolean).join(" · ")).join("\n") || current.work_company, work_detail: experience.map((item) => item.details).filter(Boolean).join("\n") || current.work_detail }));
        setParseProgress(100); setUploadState("done"); setNotice("已兼容旧版 ResumeProfile 输出；建议重新解析以使用双 Agent 回填。");
      }
    } catch (error) { setParseProgress(100); setUploadState("done"); setNotice(error instanceof Error ? error.message : "Extractor 解析失败，请检查原始字段。"); }
  }
  async function fillWebForm() { if (domainState !== "allowed" || !url || !uploadTaskId) { setWebState("error"); setNotice("请先上传简历并完成网址授权。"); return; } setWebState("running"); try { const response = await fetch(`${API_BASE}/tasks/${uploadTaskId}/messages`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ content: `请打开已授权的网址 ${url}，等待页面加载完成，识别网页表单字段，并使用已上传的简历内容填写表单草稿。只填写，不要点击最终提交按钮；完成后用普通中文汇报成功步骤、未填写字段和失败原因。` }) }); if (!response.ok) throw new Error(); const result = await response.json() as { response?: string }; const message = String(result.response ?? ""); if (/(登录|账号|密码|用户名)/.test(message)) { setWebState("idle"); setNotice(`${message} 登录完成后再次点击“打开网页并填写草稿”。`); } else { setWebState("done"); setNotice(message || "网页表单填写任务已完成，请回到目标网页检查草稿；Agent 不会自动提交。"); } } catch { setWebState("error"); setNotice("网页填写失败，请确认网址已授权、API 服务正常且模型配置可用。"); } }
  return <main className="resume-app">
    <aside className="resume-nav"><div className="brand-mark"><span>CV</span><div><strong>Resume Lab</strong><small>Agent form workspace</small></div></div><div className="nav-label">简历字段</div><nav>{sections.map((section) => <button key={section.name} className={active === section.name ? "nav-item active" : "nav-item"} onClick={() => setActive(section.name)}><span>{section.icon}</span>{section.name}<em>{sectionProgress(section)}</em></button>)}</nav><div className="nav-foot"><span className="secure-dot" />本地草稿 · 不上传服务器</div></aside>
    <section className="resume-main"><header className="resume-header"><div><p className="kicker">空白简历表单 <span>·</span> 本地工作区</p><h1>把经历，写成你的下一步。</h1><p className="header-copy">填写一份清晰、可预览的简历。Agent 可在获得域名授权后，通过浏览器识别并填写网页表单。</p></div><div className="header-actions"><button className="ghost-btn" onClick={clearAll}>清空内容</button><button className="primary-btn" onClick={generatePreview}>生成预览 <span>↗</span></button></div></header>
    <div className="progress-line"><span><b>{filled}</b> 个字段已填写</span><span>{Math.round((filled / total) * 100)}%</span><i><b style={{ width: `${(filled / total) * 100}%` }} /></i></div>
    <section className="upload-card"><div><p className="kicker">Import resume</p><h2>从已有简历开始</h2><p>上传 PDF、Word 或文本简历，Agent 会提取内容帮助你完成下面的字段。</p>{(uploadState === "parsing" || uploadState === "done") && <div className="parse-progress" aria-live="polite"><div className="parse-progress-top"><span>{uploadState === "done" ? "解析完成" : notice}</span><b>{parseProgress}%</b></div><div className="parse-track"><i style={{ width: `${parseProgress}%` }} /></div><div className="parse-steps"><span className={parseProgress >= 18 ? "step-active" : ""}>读取简历</span><span className={parseProgress >= 42 ? "step-active" : ""}>提取字段</span><span className={parseProgress >= 68 ? "step-active" : ""}>校验结果</span><span className={parseProgress >= 100 ? "step-active" : ""}>回填表单</span></div></div>}</div><input id="resume-upload" className="sr-only" type="file" accept=".pdf,.docx,.txt,.md" onChange={(event) => { const file = event.target.files?.[0]; if (file) void uploadResume(file); event.currentTarget.value = ""; }} /><div className="upload-actions"><label className="ghost-btn upload-label" htmlFor="resume-upload">{uploadState === "uploading" ? "上传中…" : "选择简历文件"}</label>{uploadedFile && <span className="file-name">✓ {uploadedFile}</span>}{uploadState === "ready" && <button className="agent-btn parse-btn" onClick={() => void parseResume()}>解析并填入表单 <span>→</span></button>}</div></section>
    <div className="workspace-grid"><div className="form-column"><section className="form-card"><div className="card-heading"><div className="section-glyph">{sections.find((item) => item.name === active)?.icon}</div><div><p className="kicker">当前部分</p><h2>{active}</h2></div></div>{active === "教育经历" ? <RepeatableEditor items={educationEntries} fields={[{ key: "school", label: "专业与学校", placeholder: "例如：交互设计 · 同济大学 · 硕士" }, { key: "period", label: "时间", placeholder: "例如：2021.09 — 2024.06" }, { key: "detail", label: "补充说明", placeholder: "课程、成绩或相关活动（可选）", wide: true }]} onChange={(id, key, value) => updateRepeat(educationEntries, setEducationEntries, id, key, value)} onAdd={() => setEducationEntries((items) => [...items, { id: `education-${Date.now()}`, school: "", period: "", detail: "" }])} onRemove={(id) => setEducationEntries((items) => items.filter((item) => item.id !== id))} /> : active === "项目经历" ? <RepeatableEditor items={projectEntries} fields={[{ key: "name", label: "项目名称", placeholder: "例如：企业协作平台 2.0" }, { key: "period", label: "项目时间", placeholder: "例如：2024.03 — 2024.08" }, { key: "role", label: "项目角色", placeholder: "例如：负责人 / 产品设计" }, { key: "detail", label: "项目介绍", placeholder: "目标、行动、结果与使用的工具或技术", wide: true }]} onChange={(id, key, value) => updateRepeat(projectEntries, setProjectEntries, id, key, value)} onAdd={() => setProjectEntries((items) => [...items, { id: `project-${Date.now()}`, name: "", period: "", role: "", detail: "" }])} onRemove={(id) => setProjectEntries((items) => items.filter((item) => item.id !== id))} /> : <div className="fields-grid">{sections.find((item) => item.name === active)?.fields.map((field) => <label className={field.wide ? "field wide" : "field"} key={field.key}><span>{field.label}</span>{field.wide ? <textarea value={values[field.key] ?? ""} onChange={(event) => update(field.key, event.target.value)} placeholder={field.placeholder} rows={4} /> : <input value={values[field.key] ?? ""} onChange={(event) => update(field.key, event.target.value)} placeholder={field.placeholder} />}</label>)}</div>}</section><p className="save-note"><span>✦</span> {notice}</p></div>
    <aside className="agent-card"><div className="agent-heading"><span className="agent-icon">✳</span><div><p className="kicker">Browser agent</p><h3>让 Agent 帮你填写</h3></div><span className="live-pill">READY</span></div><p className="agent-copy">提交目标网址后，Agent 会先检查域名权限，再打开网页、识别字段并填写简历内容。</p><label className="url-label">目标网页地址<input value={url} onChange={(event) => { setUrl(event.target.value); setDomainState("idle"); setWebState("idle"); }} placeholder="https://example.com/resume" /></label><button className="agent-btn" onClick={() => void checkDomain()} disabled={!url || domainState === "checking"}>{domainState === "checking" ? "检查中…" : "检查访问权限"}<span>→</span></button>{domainState === "approval" && <div className="approval-box"><strong>需要你的授权</strong><p>发现网址 <code>{domain}</code> 尚未获得访问授权。是否允许 Agent 临时访问该精确域名并操作网页？</p><div><button className="ghost-btn" onClick={() => setDomainState("idle")}>暂不允许</button><button className="approve-btn" onClick={() => void approveDomain()}>允许访问</button></div></div>}{domainState === "allowed" && <><div className="allowed-box"><span>✓</span><div><strong>{domain}</strong><small>已授权 · 仅当前域名</small></div></div><button className="agent-btn fill-btn" onClick={() => void fillWebForm()} disabled={webState === "running" || !uploadTaskId}>{webState === "running" ? "正在打开并填写…" : webState === "done" ? "已完成草稿填写" : "打开网页并填写草稿"}<span>→</span></button>{!uploadTaskId && <p className="inline-error">请先上传简历，再开始网页填写。</p>}</>}{domainState === "error" && <p className="inline-error">只允许 HTTPS 地址，且需要权限服务在线。</p>}<div className="agent-steps"><span><b>01</b> 检查域名</span><span><b>02</b> 识别表单</span><span><b>03</b> 填写草稿</span></div></aside></div>
    {preview && <section className="preview-card"><div className="preview-top"><div><p className="kicker">Preview</p><h2>{values.name || "你的姓名"}</h2><p>{values.role || "目标职位"} {values.location && ` · ${values.location}`}</p></div><button className="ghost-btn" onClick={() => setPreview(false)}>返回编辑</button></div><div className="preview-body">{sections.slice(1).map((section) => { const content = section.fields.map((field) => values[field.key]).filter(Boolean).join(" · "); return content ? <div className="preview-row" key={section.name}><strong>{section.name}</strong><p>{content}</p></div> : null })}</div>{missing.length > 0 && <p className="missing-note">未填写：{missing.join("、")}</p>}</section>}
    </section></main>;
}
export default App;
