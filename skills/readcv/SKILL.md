---
name: readcv
description: Extract structured personal information and project experience from resumes and personal documents for RAG, resume analysis, and later form mapping.
---

# Resume Reading Skill

## Purpose

从简历、个人材料或相关文档中提取可复用的个人信息和项目经历，为 RAG 检索、简历分析和后续自动填表提供结构化数据。

本技能只负责读取、整理和引用证据，不修改原始文件，不补写未知信息，也不提交求职申请。

## Extraction Rules

1. 只提取源文件中明确出现或可以直接推断的事实。
2. 找不到的信息使用 `null` 或空数组，不使用猜测值。
3. 保留原文中的专有名词、项目名称、机构名称和职位名称。
4. 日期优先使用 `YYYY-MM`；只有年份时使用 `YYYY`；无法确定时保留原文并降低置信度。
5. 项目按照原文出现的顺序保存，除非用户要求重新排序。
6. 同一信息在多个来源出现时合并去重，并保留相关证据。
7. 不把课程、普通活动或工作经历误归类为项目，除非原文明确将其作为项目描述。
8. 每个已提取的重要字段都记录来源、位置和置信度。
9. PDF 中的换行必须结合版面判断：同一条经历的职责、成果和技术栈可以保留为多行；只有识别到新的标题、日期、机构或明显的垂直间距时，才创建新条目。
10. 不要使用“每一行对应一个条目”的规则。PDF 的内部文本顺序可能与视觉顺序不同，必须以版面分组后的内容为准。
11. 教育经历中，学校、学位、专业和时间属于同一个条目；如果日期出现在学校前后，先将它与最近的学校/学位候选配对，不要把日期单独创建成学校。
12. 项目经历中，项目名称、时间、角色、描述、技术和成果属于同一个条目；描述中的项目符号或换行不能拆成多个项目。

## Personal Information

提取源文件中存在的字段：

- `name`：姓名
- `email`：邮箱
- `phone`：电话号码
- `location`：所在城市或地址概述
- `links`：个人网站、GitHub、LinkedIn、作品集等链接
- `summary`：个人简介或职业概述
- `target_role`：目标职位或求职方向
- `nationality`：国籍
- `work_authorization`：工作许可或签证信息

不要根据姓名、语言、学校或居住地推断性别、年龄、国籍或签证状态。

## Project Experience

每个项目提取：

- `name`：项目名称
- `start_date`：项目起始时间
- `end_date`：项目结束时间；进行中的项目可使用 `进行中`
- `role`：项目角色
- `description`：项目介绍，包括目标、场景、用户或最终成果
- `technologies`：技术、工具或平台
- `url`：项目链接
- `outcomes`：项目结果、指标或影响

项目介绍只记录原文对项目的描述，不额外推断个人贡献。

## Output Contract

只返回 JSON，不要返回 Markdown 代码围栏或额外解释。教育经历、工作经历和项目经历必须保持数组结构；每一条经历必须是独立对象，不能把多条经历拼接到同一个字符串中：

```json
{
  "basics": {
    "name": null,
    "email": null,
    "phone": null,
    "location": null,
    "summary": null,
    "target_role": null,
    "nationality": null,
    "work_authorization": null,
    "links": []
  },
  "education": [
    {
      "school": null,
      "degree": null,
      "field_of_study": null,
      "start_date": null,
      "end_date": null,
      "details": null
    }
  ],
  "experience": [
    {
      "company": null,
      "title": null,
      "start_date": null,
      "end_date": null,
      "details": null
    }
  ],
  "projects": [
    {
      "name": null,
      "start_date": null,
      "end_date": null,
      "role": null,
      "description": null,
      "technologies": [],
      "url": null,
      "outcomes": []
    }
  ],
  "skills": [],
  "evidence": [
    {
      "field": "projects[0].role",
      "value": "原文中的角色",
      "source": "文件名",
      "location": "页码、章节或段落",
      "confidence": 0.0,
      "reason": "为什么该片段支持这个字段"
    }
  ]
}
```

没有提取到的列表返回 `[]`，没有提取到的单值字段返回 `null`。

## Entry Boundary Rules

在结构化输出前，按以下优先级判断是否开始新条目：

1. 新的章节标题。
2. 新的日期范围，并且附近出现新的学校、公司或项目名称。
3. 新的加粗/大字号标题或明显的版面分隔。
4. 只有在以上线索都不存在时，才把连续文本保留在当前条目的 `details`、`description` 或 `outcomes` 中。

如果条目边界无法确定，保留原文、降低 `confidence`，并在 `evidence.reason` 中说明，不要擅自拆分或合并。

## Evidence and Confidence

置信度范围为 `0.0` 到 `1.0`：

- `0.90–1.00`：原文明确、字段含义清晰
- `0.70–0.89`：原文基本明确，但日期或字段边界存在轻微歧义
- `0.40–0.69`：需要结合上下文推断，但仍有依据
- `< 0.40`：信息不可靠，通常不应写入结构化字段

证据尽可能包含文件名、页码或章节名，以及支持该字段的原文片段摘要。

## Conflict Handling

不同来源出现冲突时：

1. 不要静默覆盖。
2. 优先保留日期较新且来源更明确的内容。
3. 在 `evidence` 中记录冲突来源。
4. 无法判断时返回 `null` 或多个候选值，并说明冲突原因。

## Downstream Usage

提取结果可以用于当前会话的 RAG、简历分析、自动填写前的字段映射和用户确认。提取结果不能直接视为用户已经确认的提交内容。
