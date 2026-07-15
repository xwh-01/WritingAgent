# WritingAgent / NovelForge 完整代码笔记

> **历史文档（已归档）**：本文只描述下方标注的旧提交，不代表当前架构。当前设计请阅读 `docs/ARCHITECTURE.md`、`docs/KNOWLEDGE_PIPELINE.md` 与 `docs/STORAGE_MODEL.md`。

> 阅读对象：[xwh-01/WritingAgent main](https://github.com/xwh-01/WritingAgent/tree/main)  
> 代码基准：[8c39f2e](https://github.com/xwh-01/WritingAgent/commit/8c39f2e926d91db83ca47ccb18a933e704cd1f5f)，提交时间 2026-07-10 11:10:35 +0800  
> 阅读原则：以当前源码和实际测试为准，不把 README、KNOWLEDGE_BASE.md 中的描述直接当成已实现事实。

## 0. 先给结论

NovelForge 是一个面向长篇小说创作的垂直 Agentic Workflow。用户输入故事前提后，系统可以生成章节大纲、场景细纲和正文，再执行审查、自动修订、长篇记忆更新、连续性审计、批量写作和自然语言工具调度。

它不是一个通用多 Agent 平台。因为所有 Agent 都由 NovelForgeEngine 或 SupervisorAgent 中央编排，Agent 之间没有自由通信协议、独立消息队列或协商机制，所以准确定位是：

> 一个带 Director 工具决策、Supervisor 任务规划、结构化记忆、自动质量闭环和 Trace 的小说创作 Agent 工程项目。

项目中最接近“真正 Agent”的部分是 NovelDirectorAgent：它读取当前故事状态和工具 Schema，由 LLM 选择工具、填参数、观察结果，并在可恢复错误后重新规划。Planner、Writer、Critic、Editor 等模块本质上是职责明确的 LLM Service/Workflow Node，由引擎按确定流程调用。

项目中做得较好的是边界清楚、数据模型完整、工作流可运行、Mock 演示路径完整、Trace 和测试覆盖面较广。主要问题不是“功能少”，而是部分正确性还没有闭合：四个长篇模块的 LLM JSON 分支实际失效、历史版本和未来章节可能污染召回、连续性问题不一定进入修订闭环、后台任务只适合单进程演示。

### 仓库规模

- novelforge/：约 8,635 行 Python。
- tests/：约 1,192 行，54 个 pytest 用例。
- evals/：12 个 JSON 场景，乘以 3 个 baseline 标签后输出 36 条结果。
- core/models.py：30 个核心领域模型。
- Director Tool Registry：10 个工具。
- 用户入口：CLI、REST API、Workspace、Dashboard、Agent Trace 页面。

---

## 1. 从用户角度看，这个产品能做什么

### 1.1 用户功能

| 功能 | 用户输入 | 系统输出 | 实际调用 |
| --- | --- | --- | --- |
| 新建故事 | 标题、故事前提、类型、文风 | 一个持久化的 Story | start_new_story |
| 生成大纲 | 目标章节数、是否强制重建 | ChapterOutline 列表 | PlannerAgent.generate_outline |
| 生成细纲 | 章节号 | 3–5 个 Beat | ContextAssembler → Planner |
| 写章节 | 章节号 | 章节正文、版本、摘要、记忆和审计报告 | Planner → Writer → Editor → Longform |
| 手动保存 | 标题、正文、状态 | 新章节版本及更新后的记忆 | update_chapter_content |
| 普通审查 | 章节号 | 逻辑、人设、节奏问题和建议 | Critic + 长篇规则检查 |
| 手动/自动修订 | 章节号，可选人工正文 | 修订后的章节版本 | Editor |
| 自动写作闭环 | 章节号 | 多轮评分、修订正文、最终分数、残留问题 | AutoRevisor |
| 连续性审计 | 章节号 | 风险分、问题、证据、建议 | ContinuityAuditor |
| 批量写作 | 起止章节、是否自动修订 | 每章状态、字数、分数、失败数 | batch_write_chapters |
| Agentic Run | 自然语言目标、章节范围 | Supervisor 任务队列及执行记录 | Supervisor → Engine |
| Director Agent | 一句自然语言任务 | 工具选择、参数、执行观察和 Trace | Director → ToolRegistry |
| 查看全景 | 故事 ID | 伏笔、角色时间线、节奏、质量趋势、因果图 | Dashboard |
| 导出 | 故事 ID | Markdown 或 DOCX | Engine exporter |
| 删除故事 | 故事 ID | 删除 JSON、向量、全文索引和关系图数据 | delete_story_data |

### 1.2 一条完整的用户路径

1. 用户创建故事，系统生成 Story.id 并立即写入 JSON。
2. 用户生成大纲。因为细纲和写作都通过 story.get_outline(chapter_index) 获取章节目标，所以没有大纲就无法进入后续流程。
3. 用户生成某章细纲。系统先组装历史上下文，再让 Planner 把本章拆成场景目标和结果。
4. 用户写正文。若细纲不存在，Engine 会先自动生成细纲；Writer 生成初稿后，默认再调用 Editor 润色。
5. 正文写入后，系统同步更新章节摘要、角色、世界观、伏笔、因果事件、人物状态、节奏、记忆卡和连续性报告。
6. 用户可以执行普通审查，也可以进入 AutoRevisor 的“评分 → 修订 → 再评分”循环。
7. 后续章节写作时，ContextAssembler 会召回前文状态和记忆，再注入 Writer Prompt。
8. 用户可以通过 Workspace 查看正文和 Trace，通过 Dashboard 查看故事全局状态，最后导出 Markdown/DOCX。

---

## 2. 总体架构

~~~mermaid
flowchart TD
    A["CLI / Workspace / REST API"] --> B["NovelForgeEngine"]
    B --> C["Planner · Writer · Critic · Editor"]
    B --> D["Director · Supervisor · AutoRevisor"]
    B --> E["ContextAssembler · LongformManager"]
    E --> F["Story JSON · Chroma · SQLite FTS · NetworkX"]
~~~

核心依赖方向是单向的：入口层调用 Engine，Engine 调 Agent 和记忆层，最终把所有业务状态收敛回 Story。因此 Story 是领域聚合根，NovelForgeEngine 是应用服务和工作流编排中心。

### 2.1 目录职责

| 目录 | 职责 |
| --- | --- |
| novelforge/core/ | Pydantic 领域模型、配置、异常、通用 JSON/文本工具 |
| novelforge/llm/ | LLMClient 抽象、Mock、DeepSeek 适配器和工厂 |
| novelforge/agents/ | Planner、Writer、Critic、Editor、Director、Supervisor、连续性审计、记忆提取 |
| novelforge/orchestrator/ | Engine、AutoRevisor、ToolRegistry、后台任务、Trace、EventBus |
| novelforge/context/ | 多来源记忆召回和写作上下文拼装 |
| novelforge/longform/ | 伏笔、因果、角色状态、摘要、节奏、分层记忆和排序 |
| novelforge/memory/ | Chroma、SQLite FTS、NetworkX 抽象与实现 |
| novelforge/storage/ | Story JSON、索引、图数据和报告的运行时目录 |
| novelforge/api/ | FastAPI 应用、请求模型、故事/章节/Agent 路由 |
| novelforge/workspace/ | 主创作工作台 HTML/CSS/JS |
| novelforge/dashboard/ | 全景数据提供层和可视化页面 |
| novelforge/agent_trace/ | 独立 Director Trace 页面 |
| tests/ | 单元与 API 集成测试 |
| evals/ | 规则一致性回归场景和报告生成器 |
| docs/ | 项目地图与 Memory Engine v2 说明 |

---

## 3. 核心数据模型

### 3.1 Story：唯一聚合根

Story 同时承担业务数据库和运行状态快照的角色。因为故事的章节、人物、记忆、报告和 Agent Trace 都嵌套在这个对象里，所以保存一次 Story 就能恢复大部分业务状态。

| 字段组 | 字段 | 含义 |
| --- | --- | --- |
| 基本信息 | id/title/premise/genre/style_guide | 故事身份和生成约束 |
| 规划与正文 | outlines/chapters/current_chapter/status | 章节计划、正文和流程状态 |
| 人物设定 | characters/world_settings | 结构化角色与世界观 |
| 长篇状态 | foreshadowings/causal_events/character_states | 伏笔、因果和人物状态 |
| 分层摘要 | chapter_summaries/volume_summaries/arc_summaries | 章、卷、故事弧摘要 |
| 长期记忆 | story_bible/memory_cards | 全局约束和可排序召回单元 |
| 质量报告 | auto_revision_reports/continuity_reports/batch_reports | 修订、连续性、批量任务结果 |
| Agent 记录 | agent_runs/agent_trace_runs | Supervisor 和 Director 运行历史 |
| 时间 | created_at/updated_at | UTC 创建和更新时间 |

### 3.2 内容生产模型

| 模型 | 关键字段 | 作用 |
| --- | --- | --- |
| Character | id、name、age、appearance、personality、motivation、weakness、relationships、secrets、arc | 角色静态设定 |
| WorldSetting | id、category、content、metadata | 世界规则、地点、组织、物品等 |
| ChapterOutline | chapter_index、title、summary、conflict、pov_character | 每章的结构目标 |
| Beat | scene_index、description、goal、outcome | 场景级执行计划 |
| Chapter | index、title、content、version、status、summary、beats、history | 章节当前状态 |
| ChapterVersion | version、content、status、summary、created_at | 修改前快照 |

Chapter.update_content 会先把旧正文加入 history，然后版本号加一。它提供的是“版本历史记录”，不是完整版本控制：没有 diff、分支、回滚 API 和并发冲突检测。另外，version 初始值是 1，第一次写入正文后会直接变成 2。

### 3.3 审查与修订模型

| 模型 | 作用 |
| --- | --- |
| ReviewReport | 普通审查的逻辑、人设、节奏问题、建议和 verdict |
| QualityScores | 逻辑 25%、人设 25%、伏笔 20%、节奏 15%、风格 15% 的默认加权评分 |
| RevisionIssue | 维度、严重性、描述、段落位置和原文证据 |
| QualityReviewReport | 五维评分、问题列表和总评 |
| ContinuityIssue | 连续性问题、证据和修复建议 |
| ContinuityAuditReport | 章节风险分、是否通过、检查过的约束和问题列表 |
| AutoRevisionRoundReport | 单轮评分、修订正文、评分方差和修改摘要 |
| AutoRevisionReport | 全部轮次、最终正文、最终分数、是否通过和残留问题 |
| BatchChapterResult/BatchWriteReport | 批量写作中每章与整体结果 |

### 3.4 Agent 工程模型

| 模型 | 作用 |
| --- | --- |
| AgentTask | Supervisor 计划中的一个可执行任务及其生命周期 |
| AutonomousRunReport | 一次 Agentic Run 的目标、策略、任务队列和完成统计 |
| AgentDecision | Director 单步选择的工具、参数、原因、是否继续、反思和重试次数 |
| AgentTraceStep | Director 每步的输入、输出、耗时、错误、记忆命中和评分变化 |
| AgentTraceRun | 一次完整 Director 运行及其 Steps/Trace Events |

### 3.5 长篇记忆模型

| 模型 | 作用 |
| --- | --- |
| Foreshadowing | 伏笔描述、创建章、目标回收章和 pending/fulfilled 状态 |
| CausalEvent | 事件描述、所在章节、原因 ID 和结果 ID |
| CharacterState | 某角色在某章后的情绪、位置、知识和关系变化 |
| ChapterSummary | 场景摘要、章摘要和关键事件 ID |
| VolumeSummary | 默认每 10 章的压缩摘要 |
| ArcSummary | 默认每 20 章的故事弧摘要、关键线和未解问题 |
| StoryBible | 全局前提、当前方向、人物名册、世界规则、连续性约束 |
| MemoryCard | 类型化、带重要性和实体标签的最小召回单元 |

---

## 4. 核心工作流的真实执行逻辑

### 4.1 创建故事

start_new_story 创建空 Story，发出 story_started 事件并保存 JSON。因为创建时不自动生成大纲，所以新故事状态是 planning。

### 4.2 生成大纲与“大纲不被误改”

generate_outline(target_count, force=False) 有两条分支：

- force=True：直接用新生成结果替换 story.outlines。
- force=False：若已有数量达到目标，什么也不做；若不足，只生成缺少数量并追加，然后把编号改成正确的后续章节号。

因此，生成细纲不会修改大纲；补齐大纲也不会重写已有大纲。对应测试覆盖了“细纲不改大纲”“补齐只追加”“只有 force 才重建”。

但这里有两个正确性边界：

1. 补齐时 Planner 只收到 story.premise 和“缺几章”，没有收到已有大纲，所以新追加章节可能重复开篇结构。
2. 强制重建只替换大纲，不清理旧章节、摘要、记忆和报告，所以旧正文可能继续挂在全新的大纲下。

### 4.3 生成细纲

generate_beats(chapter_index) 的调用链是：

1. 从 Story.outlines 取出本章大纲；不存在则抛 KeyError。
2. ContextAssembler 组装故事前提、文风、本章大纲、关系图、召回记忆和长篇上下文。
3. Planner 输出 3–5 个 Beat；解析失败则返回三个固定兜底节拍。
4. 若章节不存在则创建；若存在则只替换 chapter.beats。
5. 更新 current_chapter/status，保存 Story。

因为代码没有改 story.outlines，所以“点生成细纲导致所有大纲被改”在当前 main 代码中已经不存在。

### 4.4 写章节

write_chapter 是项目最重要的固定工作流：

~~~text
读取本章大纲
  → 无细纲则先生成细纲
  → 组装写作上下文
  → Writer 生成初稿
  → 默认调用 Editor 润色
  → Chapter.update_content 生成新版本
  → 索引正文与摘要
  → LongformManager 更新结构化记忆
  → 连续性审计
  → 保存 Story
~~~

Writer 本身没有异常兜底；Editor 润色也没有异常兜底。因为这两个调用失败会向上抛错，所以真实 DeepSeek 不可用时，只有外层批量任务能把单章标记为失败，单章同步 API 会直接失败。

### 4.5 普通审查与修订

request_review 会召回 plot_summaries 和 memory_cards，再让 Critic 生成 ReviewReport。随后它额外执行三个规则检查：

- 到期未回收伏笔追加到 logic_issues；
- 节奏趋势问题追加到 pacing_issues；
- 角色状态变化问题追加到 character_issues。

apply_revision 优先使用用户提供的 revised_content；如果用户没提供，则取最近一次 ReviewReport 并调用 Editor。修订后再次执行整套记忆处理。

### 4.6 AutoRevisor 自动质量闭环

默认配置是最多 5 轮、通过阈值 8.5、每轮评分采样 3 次。

每轮流程如下：

1. 获取已有正文；没有正文时 Writer 生成初稿。
2. 重新组装上下文。
3. Critic 连续评分 score_samples 次。
4. 每个维度取中位数，问题按描述去重合并。
5. 按质量权重计算总分，并记录样本方差。
6. 分数达到阈值则立即通过。
7. 未达到阈值则把问题交给 Editor 修订，进入下一轮。
8. 达到最大轮数仍未通过时，再做一次最终审查并输出残留问题。

Trace 会记录初稿、每轮审查、每轮修订和最终审查的耗时、分数变化、错误类型及记忆命中数。

当前实现有两个关键缺口：

- 连续性问题是在“质量分未通过”之后才注入修订报告。因为代码先判断质量分是否达标，所以质量分已达标时，即使预审查发现连续性问题，也会直接通过。
- 最大轮次后的最终审查即使达到阈值，也没有把 result.passed 更新为 True，所以报告可能出现“最终分达到阈值但 passed=False”。

另外，新章节在进入 AutoRevisor 前还没有正文，因此不会执行预连续性审计；连续性审计发生在写完并处理记忆之后，但此时只记录报告，不会自动再修。

### 4.7 批量写作

batch_write_chapters(start, end, use_auto_revision) 会先补齐大纲，然后逐章执行细纲和写作。某章失败时，它记录失败并继续下一章，因此一个坏章节不会中断整个批次。

返回结果包含每章状态、标题、字符数、自动修订分数和失败信息。进度通过 callback 写入后台 Job 的事件数组，前端每 1.2 秒轮询一次。

BatchWriteReport.stopped 当前没有实际更新逻辑；批量任务也没有独立取消标志。

### 4.8 Supervisor Agentic Run

Supervisor 先尝试让 LLM 输出任务列表，再执行严格校验：

- 动作必须属于 6 个 allowlist action；
- 章节号必须落在请求范围；
- write_chapter 和 auto_write_chapter 根据配置互换；
- 重复动作会去重；
- 最后强制补齐大纲、细纲、写作、连续性审计和记忆检查点。

执行器按任务顺序串行运行，任一任务失败就停止后续任务。因此 Supervisor 的“自主性”集中在计划阶段，执行阶段仍是受约束的任务队列。

---

## 5. Agent 体系

### 5.1 各 Agent 的实际职责

| Agent | 输入 | 输出 | 是否自主选工具 |
| --- | --- | --- | --- |
| PlannerAgent | premise 或 chapter outline + context | Outline / Beat | 否 |
| WriterAgent | outline、beats、context、style | 正文字符串 | 否 |
| CriticAgent | 正文、大纲、角色、记忆 | ReviewReport / QualityReviewReport | 否 |
| EditorAgent | 原文、审查问题、文风 | 修订正文 | 否 |
| ContinuityAuditorAgent | Story、章节、长篇上下文 | ContinuityAuditReport | 否 |
| MemoryExtractorAgent | Story、章节正文 | 角色、世界观、关系、约束 | 否 |
| SupervisorAgent | 目标、章节范围、Story 状态 | 受校验的任务计划 | 选择 action，但不直接执行 ToolRegistry |
| NovelDirectorAgent | 用户自然语言、Story 状态、工具列表、历史观察 | AgentDecision | 是 |

所以项目可以叫 Multi-Agent Workflow，但不能描述成“多个 Agent 自由协商合作”。因为 Planner、Writer、Critic、Editor 没有互相发消息，所有数据都由 Engine 以函数参数传递。

### 5.2 Director 的决策循环

Director 每一步都收到：

- 故事 ID、标题、前提、状态、当前章节；
- 大纲数、章节数、最近 12 章的写作状态；
- 最多 12 条未回收伏笔；
- 记忆卡数量；
- 最近 6 步工具观察；
- ToolRegistry 的工具说明和 Pydantic JSON Schema。

然后输出 AgentDecision。如果选择 ask_user，运行状态变为 needs_user_input；否则执行工具并生成 AgentTraceStep。

### 5.3 Director 的 10 个工具

| 工具 | 参数 | 作用 |
| --- | --- | --- |
| show_status | 无 | 查看故事进度和记忆数量 |
| create_outline | num_chapters? | 创建或补齐大纲 |
| create_beats | chapter_index | 生成本章细纲 |
| write_chapter | chapter_index | 写普通草稿 |
| review_chapter | chapter_index | 普通审查 |
| revise_chapter | chapter_index/revised_content? | 修订章节 |
| auto_write_chapter | chapter_index | 自动写审改闭环 |
| audit_continuity | chapter_index | 连续性审计 |
| update_memory | chapter_index | 重新处理章节记忆 |
| list_foreshadowings | status? | 查询伏笔 |

参数先经过 Pydantic 校验，因此 bad 不能作为 chapter_index 进入 Engine。工具不存在或参数不合法时，ToolRegistry 返回结构化错误，而不是直接抛出未处理异常。

### 5.4 错误分类与恢复

错误通过异常消息关键词分类为 provider、参数错误、缺前置条件、质量门槛、记忆召回、工具执行或未知错误。

Director 最多做两次恢复：

- 参数错误：修正为当前章节后重试；
- 缺大纲：先调用 create_outline；
- 缺细纲：先调用 create_beats；
- 质量门槛失败：转入 auto_write_chapter；
- 其他可恢复工具错误：原工具重试一次。

这里的错误分类是字符串启发式，不是异常类型体系。例如消息中出现 api 就会被视为 provider 错误。并且 provider 错误不在 is_recoverable 集合中，所以 DeepSeek 最终失败后 Director 不会再做工具级恢复。

规则 fallback 也有一个行为偏差：它能从文本提取章节号，但“继续/下一章/write”分支最终使用 current_chapter + 1，没有使用提取到的目标章节。因此 LLM 决策解析失败时，“write chapter 5”可能变成写当前下一章。

---

## 6. 记忆系统

### 6.1 四种状态载体

| 载体 | 存什么 | 查询方式 | 持久性 |
| --- | --- | --- | --- |
| Story JSON | 全量结构化业务状态、正文、版本、报告、Trace | 直接字段访问 | 持久化 |
| Chroma | characters、world、plot_summaries、memory_cards | 向量检索 | 持久化；失败时可能退化内存 |
| SQLite FTS5 | 版本化章节正文 | 关键词全文检索 | 持久化 |
| NetworkX JSON | 角色节点和关系边 | Ego Network | 持久化 |

### 6.2 每次写完/修改章节后发生什么

_process_chapter_memory 的顺序是：

1. 用 story_id:chapter:index:v版本 索引完整正文到 SQLite FTS。
2. 把章节摘要写入 Chroma plot_summaries。
3. MemoryExtractor 提取角色、世界观、关系和连续性约束。
4. SummaryManager 写章摘要和卷摘要。
5. CausalityTracker 重建本章因果事件。
6. ForeshadowingTracker 检测新伏笔并尝试回收旧伏笔。
7. CharacterStateTracker 更新人物状态。
8. PacingAnalyzer 写入进程内节奏历史。
9. MemoryEngineV2 生成 MemoryCard、ArcSummary 和 StoryBible。
10. 角色/世界观写入 Chroma，人物关系写入 NetworkX。
11. MemoryCard 写入 Chroma。
12. ContinuityAuditor 生成并保存本章连续性报告。

### 6.3 写作前如何组装上下文

ContextAssembler 先构造查询：

~~~text
outline.title + outline.summary + outline.conflict + pov_character
~~~

然后按优先级加入：

| 优先级 | 内容 |
| --- | --- |
| 100 | 故事前提 |
| 95 | 文风指南 |
| 90 | 本章大纲 |
| 88 | Longform Memory Context Pack |
| 85 | 本章节拍 |
| 70 | POV 角色关系图 |
| 50 | 重排后的向量记忆 |
| 40 | SQLite FTS 片段 |

最终按 max_context_tokens × 4 估算字符上限，并尽量在段落或句子边界截断。这不是精确 Token 计数。

### 6.4 MemoryRanker

向量结果的近似评分公式是：

~~~text
10 × vector_similarity
+ type_weight
+ recency_score
+ query_overlap_bonus
+ entity_match_bonus
~~~

结构化 MemoryCard 从 importance 起分，再加入相同的类型、时间、查询和实体分。默认优先级最高的是 character_state=6.5 和 foreshadowing=6.0，因为角色漂移和伏笔遗忘对长篇一致性的破坏最大。

### 6.5 Memory Engine v2 的层次

- 最近 5 章摘要解决短期连续性；
- 默认每 10 章一个 VolumeSummary；
- 默认每 20 章一个 ArcSummary；
- StoryBible 维护全局前提、方向、角色名册、活跃线程和约束；
- MemoryCard 负责按查询召回具体事件、伏笔和人物状态。

这个分层方向是合理的，因为不同时间跨度的信息不应该全部塞进同一个向量 Top-K。

### 6.6 当前记忆正确性问题

1. **旧版本污染**：章节每次修改都会用新版本 ID 写入 Chroma/FTS，但旧版本没有删除，所以后续召回可能同时看到旧正文和新正文。
2. **未来信息泄漏**：重写早期章节时，MemoryCard 只对未来章节扣 4 分而不排除；角色状态取全书最新状态；因果事件取全书最后 12 条；伏笔也不限制 created_chapter <= target。因此第 3 章可能看到第 20 章的信息。
3. **重修后的结构化残留**：重写章节会替换本章摘要、事件和人物状态，但旧伏笔、人物、世界观和连续性约束大多只增不删，所以已从正文删除的事实可能继续存在。
4. **StoryBible 世界规则未同步**：update_story_bible 会同步前提、风格、人物和约束，但没有把 story.world_settings 写入 story_bible.world_rules。
5. **节奏历史不持久化**：pacing_history 在 LongformManager 内存中，服务重启后丢失；普通审查不会自动从已有章节重建它。
6. **FTS 查询过长**：系统把整段标题+摘要+冲突作为 FTS MATCH 查询。若 MATCH 失败则退化为对整段查询做 LIKE，中文长查询通常难以命中。
7. **内存向量 fallback 的中文分词很粗**：连续中文会被正则当成一个长 Token，余弦相似度质量有限。
8. **关系图 ID 可能不匹配**：图节点按角色 ID 保存，但 ContextAssembler 直接把 pov_character 当角色 ID；如果大纲里写的是角色名而不是 ID，Ego Network 为空。

---

## 7. 长篇一致性子系统

| 模块 | LLM 设计 | 规则 fallback 的真实逻辑 |
| --- | --- | --- |
| SummaryManager | 输出场景、章节和关键事件摘要 | 以空行/句号切句，取前 6 个场景、前 8 句压缩 |
| ForeshadowingTracker | 提取新伏笔 | 六组信号词；每章最多返回第一个命中的一条；以揭露词+描述关键词自动回收 |
| CausalityTracker | 提取事件及 causes/effects | 匹配决定、发现、背叛、受伤等词，最多 5 事件；检查缺失前因、未来前因和循环 |
| CharacterStateTracker | 提取每个角色的情绪、地点、知识和关系变化 | 从整章全局词表猜情绪/地点/知识，再赋给所有出现角色 |
| PacingAnalyzer | 不调用 LLM | 统计冲突词、动作词、对话行、句长和最近三章趋势 |
| MemoryExtractorAgent | 提取角色、世界观、关系和约束 | 姓名模式、世界设定信号、关系词和七类连续性信号 |
| ContinuityAuditorAgent | 结合 StoryBible 与上下文审计 | 到期伏笔、章节目标词、部分约束、位置变化和情绪变化 |

### 7.1 最重要的实现缺陷：四个 LLM 分支实际不可用

extract_json(raw) 已经返回 Python dict/list，但以下四个模块又执行了 json.loads(extract_json(raw))：

- SummaryManager._llm_summary
- ForeshadowingTracker._llm_detect
- CausalityTracker._llm_extract
- CharacterStateTracker._llm_extract

因为 json.loads 不能接受 dict/list，所以即使 LLM 返回完全合法的 JSON，这四个分支也会抛异常并进入规则 fallback。实际诊断结果是：合法摘要返回 None，其他三个返回空列表。

MemoryExtractor、Planner、Critic、Director 使用 BaseAgent 的 _parse_model，没有这个二次解析问题。

### 7.2 规则检测的边界

- 伏笔规则只返回第一个命中的类别，因此一章同时出现秘密、特殊物品和承诺时只记录一条。
- 伏笔 ID 使用 Python hash()，不同进程的哈希随机种子可能让同一正文得到不同 ID。
- 角色状态 fallback 对每个角色使用整章相同的情绪和地点，无法区分“甲在医院、乙在学校”。
- 因果事件批量提取依赖返回顺序；若事件引用同一批次中尚未加入的后续事件，会被当成缺失前因丢弃。
- 删除并重建本章因果事件时，没有清理其他事件中指向旧事件的悬空 effect/cause ID。
- Pacing 的中文弯引号判断源码写成了一个值为 ", " 的三引号字符串，因此 “你好” 不会被识别为对话，而 ASCII "hi" 和「你好」可以。

---

## 8. 持久化、后台任务和并发

### 8.1 StoryRepository

Story 以 {story_id}.json 全量保存。写入过程是：先写固定的 .json.tmp，再 replace 为正式文件，因此单次写入具备较好的原子性。

但这不是数据库事务。因为同一故事的多个线程会使用同一个临时文件名，所以并发保存可能互相覆盖或出现临时文件已被另一线程移动的问题。

### 8.2 API Engine Registry

ENGINES 是进程内 dict[story_id, NovelForgeEngine]。请求第一次访问故事时创建 Engine 并加载 JSON，之后复用同一个 Engine。

这意味着：

- 单进程开发模式简单有效；
- 多 worker 时每个进程拥有独立 Engine 和 Job Registry；
- Engine 状态、last_review、AutoRevisor、pacing history 不会跨进程共享；
- 没有锁保护 Story 对象和 Engine Registry。

### 8.3 后台任务

后台任务使用 daemon threading.Thread，支持单章 AutoRevision、Batch Write 和 Agentic Run。Job 只保存在内存中，事件最多 120 条。

因此它适合 Demo，不适合生产任务系统：

- 服务重启后 Job 和进度全部丢失；
- 没有 Redis/Celery/RQ/数据库任务表；
- 多 worker 查询不到其他进程创建的 Job；
- 一个 Engine 只有 current_auto_revisor，同一故事并发启动多个自动任务时，按 job_id 停止可能停止最后赋值的另一个修订器；
- 删除故事不会先停止后台线程，线程可能在删除后再次保存 Story；
- SQLite 连接设置了 check_same_thread=False，但没有应用层串行锁。

实际测量中，一章非自动修订 Agentic 后台任务约 2.75 秒完成，而对应测试只等待 1 秒，所以测试会稳定超时。

### 8.4 EventBus 与 WebSocket

EventBus 是同步发布订阅。某个 handler 抛异常会被吞掉，后续 handler 继续执行；因为没有日志，所以订阅者故障不可观测。

当前 WebSocket /ws/{story_id} 只发送一条 reserved 消息后立即关闭，没有订阅 EventBus，也没有实时推送批量进度。仓库知识库中“WebSocket 通过 EventBus 推送进度”的描述与代码不符。

---

## 9. REST API

### 9.1 故事接口

| 方法与路径 | 请求 | 响应 |
| --- | --- | --- |
| POST /stories/ | premise、title、genre、style_guide | 完整 Story |
| GET /stories/{id}/ | path id | 完整 Story |
| DELETE /stories/{id} | path id | 各存储删除数量 |
| POST /stories/{id}/outline | num_chapters、force | Outline 列表 |
| POST /stories/{id}/batch-write | 起止章、自动修订、background | Job 或 BatchReport |
| POST /stories/{id}/agentic-run | objective、范围、自动修订、background | Job 或 AutonomousRunReport |
| POST /stories/{id}/agent/run | user_message、max_steps | AgentTraceRun |
| GET /stories/{id}/agent/runs | 无 | Director Run 列表 |
| GET /stories/{id}/agent/runs/{run_id} | run id | 单次 Run |
| GET .../trace.json | run id | Trace JSON |
| GET .../debug.md | run id | Debug Markdown |
| GET /stories/{id}/status | id | 状态摘要 |
| GET /stories/{id}/export-docx | id | DOCX 文件 |

### 9.2 章节接口

| 方法与路径 | 请求 | 响应 |
| --- | --- | --- |
| GET /chapters/{n}/?story_id= | 章节号、故事 ID | Chapter |
| POST /chapters/{n}/beats?story_id= | 章节号 | Chapter + Beats |
| POST /chapters/{n}/write?story_id= | 章节号 | 写完的 Chapter |
| POST /chapters/{n}/review?story_id= | 章节号 | ReviewReport |
| POST /chapters/{n}/audit?story_id= | 章节号 | ContinuityAuditReport |
| PUT /chapters/{n}/revise?story_id= | revised_content? | 修订后的 Chapter |
| PUT /chapters/{n}/content?story_id= | title、content、status | 手动保存后的 Chapter |
| POST /chapters/{n}/auto-write?story_id=&background= | 章节号 | Job 或 AutoRevisionReport |
| GET /chapters/{n}/report?story_id= | 章节号 | 自动修订/连续性报告 |
| GET /chapters/{n}/report.md?story_id= | 章节号 | Markdown 报告 |
| GET /chapters/auto/status?story_id=&job_id= | 可选 Job ID | Engine 或 Job 状态 |
| POST /chapters/auto/stop?story_id=&job_id= | 可选 Job ID | 是否请求停止 |

### 9.3 页面和元数据接口

- GET /workspace/：主创作工作台。
- GET /dashboard/：故事全景页面。
- GET /dashboard/data/{story_id}：全景 JSON。
- GET /dashboard/stories：本地 Story 列表。
- GET /agent-trace/：独立 Director Trace 页面。
- GET /agents/：返回角色名称列表。
- WebSocket /ws/{story_id}：目前只是占位。

### 9.4 API 边界问题

- 没有统一把 WorkflowError/PersistenceError/KeyError 映射成 4xx，部分缺失资源会返回 500。
- 没有认证、授权、租户隔离、速率限制和请求审计。
- 创建和修改请求对字符串长度、章节上限、正文大小缺乏业务校验。
- 同步写作端点会阻塞请求线程直到 LLM 和全部记忆处理结束。
- GET /stories/{id}/ 返回整个 Story，长篇小说会把正文、历史版本、报告和 Trace 全量传给前端，数据量会持续增大。

---

## 10. Web 前端

### 10.1 Workspace

Workspace 是三栏布局：

- 左侧：创建故事、故事库、章节列表、删除故事；
- 中间：流程条、大纲条、章节标题和正文编辑器；
- 右侧：Director 输入、推荐任务、Agent Trace、上下文预览、辅助工具、长篇指标和报告。

前端根据前置条件禁用按钮：没有故事不能生成大纲；没有本章大纲不能生成细纲和写作；没有正文不能审查和自修。

“下一步”卡片按 故事 → 大纲 → 细纲 → 正文 → Director 引导用户，因此当前用户路径比早期纯按钮界面清晰。

### 10.2 前端状态与调用

前端用一个全局 state 保存故事、当前章节、当前 Job、Job Events 和 Director 运行状态。所有数据都通过 Fetch 访问后端，没有前端框架和本地持久化。

后台任务采用轮询，不使用 WebSocket：

~~~text
启动 Job → 保存 job.id → 每 1.2 秒 GET auto/status
→ 渲染事件 → 终态后重新加载完整 Story
~~~

### 10.3 Dashboard

Dashboard 展示：

- 伏笔状态及 overdue 标记；
- 角色情绪/位置时间线；
- 章节冲突、对话、动作、场景数和字符数；
- 自动修订分数与连续性风险趋势；
- 因果事件节点和边；
- 故事总览统计。

Dashboard 的节奏指标是 DashboardDataProvider 重新估算的，不完全等于 PacingAnalyzer 的运行时指标，因此同一章节在不同页面的数值口径可能不同。

---

## 11. 配置和 LLM 层

### 11.1 配置结构

- LLMConfig：provider、model、temperature、max_tokens、api_key、base_url、timeout、重试。
- MemoryConfig：Chroma、NetworkX、SQLite 路径。
- StoryConfig：默认章节数、上下文长度、历史限制、自动润色、目标字数。
- AutoRevisorConfig：轮数、阈值、评分采样、权重。
- MemoryRankerConfig：类型、时间、实体、查询词权重。

YAML 先加载，环境变量再覆盖。环境变量只覆盖 LLM、三个记忆路径和日志级别；Story、AutoRevisor 和 MemoryRanker 没有环境变量覆盖实现。

### 11.2 Mock 和 DeepSeek

build_llm_client 只支持 deepseek 和 mock/local/fake。

DeepSeekClient 使用 OpenAI SDK，失败后按 1s、2s、4s… 外层指数退避，最终抛 ProviderError。

当前有三个配置/稳定性问题：

1. temperature 和 max_tokens 虽然存在于配置，但构造 DeepSeekClient 时没有传入，Agent 调用时也没统一传，所以这两个配置当前不生效。
2. 没有使用 API 的 response_format 或 JSON Schema；结构正确性依赖 Prompt、extract_json 和 Pydantic。
3. requirements 没有版本锁定，也没有 pyproject.toml，因此全新安装可能因依赖升级产生行为变化。

### 11.3 Mock 不完全确定性

Mock 大部分输出是固定的，但质量评分使用 random.uniform 且没有固定随机种子，所以“Deterministic Mock LLM”的注释并不完全准确。评分虽然通常落在安全区间，但测试和演示仍存在波动来源。

Mock 的 scene_transitions 还把 content.count("\n\n") 重复加了两次，会高估结构分。

### 11.4 Chroma 降级边界

代码只在 chromadb.PersistentClient 初始化抛异常时切换到 InMemoryVectorStore。若 Chroma 已成功初始化，但首次查询/写入时下载默认 ONNX embedding 模型失败，异常会直接中断写作，不会自动降级。

在全新环境中，Chroma 还需要可写缓存目录和模型下载；这与 README 中“安装后 Mock 可直接完整运行”之间存在隐含前置条件。

---

## 12. 测试和 Eval 应该怎么理解

### 12.1 pytest 实测

实际验证结果：

- Python compileall：通过。
- 第一次运行：34 passed / 20 failed。失败原因是 Chroma 尝试把模型缓存写入只读 /root/.cache/chroma，说明运行期无法自动降级。
- 改为可写缓存并完成模型下载后：53 passed / 1 failed。
- 唯一失败：test_agentic_run_api_background_job 只轮询 20 × 0.05 秒，即最多 1 秒；实测任务约 2.75 秒完成，因此断言时仍是 running_agentic。
- 单独延长等待后，任务最终状态为 agentic_finished，5/5 tasks 完成。

所以更准确的结论不是简单写“54/54 全过”，而是：核心功能测试基本通过，但后台测试对机器性能敏感，Chroma 首次运行依赖缓存和模型下载。

### 12.2 测试覆盖了什么

- 核心写作、保存和加载；
- 大纲保护；
- Planner/Writer/Critic/Editor；
- AutoRevisor、Trace、残留问题；
- Director 工具选择、参数错误和前置条件恢复；
- Supervisor 任务计划和后台任务；
- Memory Engine、排序、故事隔离和删除；
- 连续性审计、伏笔、因果、节奏、人物状态；
- Workspace、Dashboard、API 和报告导出。

没有覆盖：

- 真实 DeepSeek 端到端调用；
- 四个已失效的长篇 LLM 解析分支；
- 多线程同时修改同一 Story；
- 多进程部署；
- 删除故事与后台任务竞争；
- 历史版本召回污染和未来信息泄漏；
- WebSocket 实时进度；
- 100/1000 章规模、延迟、存储体积和召回准确率；
- Prompt Injection、越权和 API 安全。

### 12.3 Eval 实测与可信范围

python -m evals.run_eval 实测输出 36/36。

但 36 不是 36 个独立场景，而是：

~~~text
12 个 JSON 场景 × 3 个 baseline 标签 = 36 条结果
~~~

三个 baseline 并没有真的关闭 longform context 或 auto revision，run_case 对它们执行完全相同的 deterministic checker，只改变报告标签。因此它不是消融实验。

Eval 的实际价值是验证四类规则：

- 未来/缺失因果前因；
- 到期伏笔；
- 人物位置、情绪和限制变化；
- 连续三章低冲突节奏。

局限是：

- 它直接构造结构化 Story，不验证“正文 → LLM/规则提取 → 结构化状态”的准确率；
- 不验证生成内容是否因记忆注入而改善；
- 多个场景的 expected.keywords 为空，此时只要产生任意 finding 就算通过；
- expected 为空时 false-positive 统计恒为 0；
- 没有 precision、recall、人工标注对照和真实长篇数据。

所以“36/36”只能证明当前规则没有回归，不能证明小说质量、Agent 质量或 1000 章能力。

---

## 13. 仓库文档与代码不一致的地方

| 文档说法 | 当前代码事实 |
| --- | --- |
| WebSocket 订阅 EventBus 实时推送 | 只发一条占位消息后关闭 |
| Mock LLM 是确定性的 | 质量评分使用未固定种子的随机数 |
| 每个 LLM 调用都有 fallback | Writer、Editor 等调用失败会直接抛错；四个 longform LLM 分支实际总是 fallback |
| CLI 有 /agentic-run | cli.py 没有 do_agentic_run，只有 REST/Workspace 入口 |
| 项目含 pyproject.toml | 当前 main 没有该文件 |
| 7 个 Agent | 业务 Agent 实际可数为 8 个；/agents 又把 context、memory 作为名称返回 |
| 4 个 Eval 场景 | 当前有 12 个 JSON 文件，报告按三种标签展开为 36 行 |
| EventBus 的审计事件会送到 WebSocket | _audit_processed_chapter 只保存报告，未 emit；WebSocket 也未订阅 |
| KNOWLEDGE_BASE.md 的项目根名是 BookAgent | 当前仓库和包名是 WritingAgent / NovelForge |

因此面试或继续开发时，应把 Engine、Agent、Longform 和测试源码作为事实来源，把仓库知识库当作早期设计说明。

---

## 14. 项目优点与局限

### 14.1 真正做得好的地方

1. **领域边界清楚**：只解决长篇小说，不包装成通用 Agent 平台。
2. **数据模型完整**：正文、版本、评分、伏笔、因果、人物状态、任务和 Trace 都有结构化模型。
3. **三条执行路径区分明确**：普通固定工作流、Supervisor Agentic Run、Director 自然语言工具循环各自承担不同场景。
4. **工具调用有类型约束**：ToolRegistry 用 Pydantic Schema 验证参数并返回结构化错误。
5. **具备恢复思路**：Director 会补大纲、补细纲、修参数和转自动修订。
6. **长篇记忆不是只接一个向量库**：项目同时建模摘要层级、伏笔、角色状态和因果事件。
7. **可观测性有具体产物**：Trace JSON、Debug Markdown、AutoRevision Report、Workspace Trace、Dashboard。
8. **离线演示路径完整**：Mock 可以展示主要业务，不依赖真实 API 成本。
9. **测试覆盖面广**：包含业务、API、前端页面、后台任务、记忆隔离、删除和 Eval。

### 14.2 不能夸大的地方

1. 不是去中心化或自由协商的多 Agent 系统。
2. 不是 LangGraph/ReAct 框架项目；核心循环和状态机是手写的。
3. Memory Engine 是合理的数据形状，不等于已验证 1000 章可用。
4. AutoRevisor 的分数来自同一 LLM 自评，没有独立 Judge、人工偏好或事实校验器。
5. Eval 是规则回归，不是生成质量评测，也不是真消融实验。
6. Trace 是业务事件记录，不是 OpenTelemetry 分布式追踪。
7. 后台线程、全量 JSON 和进程内 Registry 只适合个人项目/单机 Demo，不是生产任务平台。
8. Chapter history 是版本快照，不是完整版本控制系统。

---

## 15. 已知问题优先级

| 优先级 | 问题 | 因果影响 |
| --- | --- | --- |
| P0 | 四个 longform LLM 分支二次 json.loads | 合法 LLM 输出仍被丢弃，系统长期依赖低精度规则 |
| P0 | Chroma 运行期下载/嵌入失败不降级 | Fresh install、离线环境或缓存权限问题会直接阻断写作 |
| P0 | 旧版本与未来章节进入召回 | Writer 可能依据过期事实或剧透信息生成错误正文 |
| P1 | 连续性问题在质量通过判断后才注入 | 有高风险连续性问题的章节仍可能通过 AutoRevisor |
| P1 | 最终审查达标不更新 passed | 报告状态与 final_score 矛盾 |
| P1 | 强制重建大纲不清理下游数据 | 新大纲与旧正文、记忆、报告错配 |
| P1 | 同一故事后台任务无并发锁 | Story、固定 tmp 文件、SQLite 和 current_auto_revisor 可能竞争 |
| P1 | 结构化记忆修订后只增不删 | 已删除的伏笔/规则/设定继续影响后文 |
| P1 | 后台 Job 只在进程内 | 重启、多 worker 和横向扩容时状态丢失 |
| P2 | DeepSeek temperature/max_tokens 配置不生效 | 用户修改配置却不改变模型调用行为 |
| P2 | Mock 有随机评分 | 测试和演示不完全可复现 |
| P2 | Pacing 中文弯引号判断错误 | 中文对话比例被低估 |
| P2 | WebSocket 和知识库描述不一致 | 使用者误以为已有实时推送能力 |
| P2 | API 缺统一异常映射 | 业务缺失条件表现为 500，前端只能看到通用失败 |
| P2 | Eval baseline 只是标签 | 36/36 容易被误讲成消融实验结果 |

---

## 16. 面试时应该怎么介绍

### 16.1 一分钟版本

> NovelForge 是一个面向长篇小说创作的垂直 Agentic Workflow。固定写作链路由 Planner、Writer、Critic、Editor 分别负责大纲、正文、审查和修订；Director Agent 读取实时 Story 状态和 Tool Schema，根据自然语言选择工具，并对参数错误和缺失前置条件进行恢复。为了缓解长篇遗忘，我把状态分成 StoryBible、Arc/Volume/Chapter Summary、CharacterState、Foreshadowing、CausalEvent 和 MemoryCard，再通过 Chroma、SQLite FTS、NetworkX 和规则 Ranker 组装章节上下文。系统还提供 AutoRevisor 质量闭环、Trace、FastAPI、Workspace、Dashboard 和可复现的 Mock 测试。

### 16.2 面试官继续追问时的主线

1. 先讲用户流程：设定 → 大纲 → 细纲 → 正文 → 审查 → 修订 → 后文召回。
2. 再讲为什么需要 Story 聚合根和结构化数据，而不是只保存聊天记录。
3. 再讲 Director 的状态输入、10 个工具、Pydantic 校验和恢复分支。
4. 再讲 AutoRevisor 如何多样本评分、取中位数、记录方差和残留问题。
5. 最后主动说明边界：它是中央编排的垂直 Agent Workflow，不是自由协作平台；Eval 当前验证规则，不代表小说质量。

### 16.3 最值得展示的 Demo

1. 新建一个 Mock Story。
2. 用 Director 输入“继续写下一章”。
3. 展示它先补大纲，再调用 auto_write_chapter。
4. 打开 Agent Trace，看工具、参数、观察和耗时。
5. 打开章节报告，看多轮分数和修改摘要。
6. 打开 Dashboard，看伏笔、人物状态、因果事件和质量趋势。

这个 Demo 有明确因果链：因为没有大纲，所以 Director 先补前置条件；因为质量分未达标，所以 AutoRevisor 调 Editor；因为章节写完，所以 LongformManager 更新记忆；因为下一章需要前文，所以 ContextAssembler 召回这些记忆。

---

## 17. 运行方式

### 安装

~~~bash
python -m venv .venv
# Windows
.venv\Scripts\activate
# Linux/macOS
source .venv/bin/activate
pip install -r requirements.txt
~~~

首次使用 Chroma 时要保证用户缓存目录可写，并允许下载默认 embedding 模型。

### CLI

~~~bash
python -m novelforge
~~~

常用命令：

~~~text
/new_story <premise>
/outline 10
/beats 1
/write 1
/review 1
/revise 1
/auto-write 1
/batch-write 1 5
/agent 继续写下一章
/foreshadowing list
/causality show
/pacing check
/summary show
/dashboard
/report 1 export
/export markdown
~~~

### Web/API

~~~bash
uvicorn novelforge.api.main:app --reload
~~~

- Workspace：http://127.0.0.1:8000/workspace/
- Dashboard：http://127.0.0.1:8000/dashboard/
- Agent Trace：http://127.0.0.1:8000/agent-trace/
- Swagger：http://127.0.0.1:8000/docs

### 测试

~~~bash
pytest -q
python -m evals.run_eval
~~~

---

## 18. 源码阅读索引

建议按以下顺序回看：

1. [novelforge/core/models.py](https://github.com/xwh-01/WritingAgent/blob/main/novelforge/core/models.py)：先理解 Story 和全部状态。
2. [novelforge/orchestrator/engine.py](https://github.com/xwh-01/WritingAgent/blob/main/novelforge/orchestrator/engine.py)：固定工作流和所有入口。
3. [novelforge/agents/director.py](https://github.com/xwh-01/WritingAgent/blob/main/novelforge/agents/director.py)：真正的工具决策循环。
4. [novelforge/orchestrator/tool_registry.py](https://github.com/xwh-01/WritingAgent/blob/main/novelforge/orchestrator/tool_registry.py)：工具边界、参数验证和 Trace。
5. [novelforge/orchestrator/auto_revisor.py](https://github.com/xwh-01/WritingAgent/blob/main/novelforge/orchestrator/auto_revisor.py)：质量闭环。
6. [novelforge/context/assembler.py](https://github.com/xwh-01/WritingAgent/blob/main/novelforge/context/assembler.py)：写作上下文从哪里来。
7. [novelforge/longform/manager.py](https://github.com/xwh-01/WritingAgent/blob/main/novelforge/longform/manager.py)：章节完成后的记忆处理总入口。
8. [novelforge/longform/memory_engine.py](https://github.com/xwh-01/WritingAgent/blob/main/novelforge/longform/memory_engine.py)：分层记忆形状。
9. [novelforge/longform/ranker.py](https://github.com/xwh-01/WritingAgent/blob/main/novelforge/longform/ranker.py)：可解释召回排序。
10. [novelforge/api/routes/](https://github.com/xwh-01/WritingAgent/tree/main/novelforge/api/routes)：REST 映射。
11. [novelforge/workspace/static/workspace.js](https://github.com/xwh-01/WritingAgent/blob/main/novelforge/workspace/static/workspace.js)：真实前端用户流程。
12. [tests/test_agent_engineering_p0.py](https://github.com/xwh-01/WritingAgent/blob/main/tests/test_agent_engineering_p0.py)：Trace、参数错误、恢复和 Eval 产物。
13. [evals/run_eval.py](https://github.com/xwh-01/WritingAgent/blob/main/evals/run_eval.py)：理解 36/36 的真实计算方式。

---

## 19. 最终判断

这个仓库已经不是“只有几个 Prompt 的小说生成器”。因为它有结构化领域模型、受约束工具、状态持久化、恢复分支、分层记忆、自动修订、Trace、后台任务、Web 工作台和测试，所以它具备明确的 Agent 工程内容。

但它也还不是生产级 Agent 系统。因为召回存在版本/时间污染，四个 LLM 长篇分支当前失效，后台任务和持久化缺乏并发保障，Eval 只验证规则，所以最准确的评价是：

> 架构与工程展示已经成形，适合作为 AI 应用/Agent 工程实习项目；下一阶段应优先修正确性和评测可信度，而不是继续增加 Agent 名称或页面数量。
