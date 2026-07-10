# NovelForge 完整知识库

> 面向 AI Agent / 新开发者 / 面试准备的项目全貌文档。
> 目标：读完本文档即可理解项目架构、设计决策、实现细节和代码组织，无需额外查阅源码。

---

## 目录

1. [项目概述](#1-项目概述)
2. [要解决的问题](#2-要解决的问题)
3. [技术栈](#3-技术栈)
4. [架构全景图](#4-架构全景图)
5. [核心数据模型](#5-核心数据模型)
6. [Agent 体系](#6-agent-体系)
7. [记忆系统](#7-记忆系统)
8. [长篇一致性子系统](#8-长篇一致性子系统)
9. [编排层](#9-编排层)
10. [配置系统](#10-配置系统)
11. [LLM 抽象层](#11-llm-抽象层)
12. [接口层](#12-接口层)
13. [完整数据流追踪](#13-完整数据流追踪)
14. [关键设计决策与取舍](#14-关键设计决策与取舍)
15. [目录结构与文件职责](#15-目录结构与文件职责)
16. [快速上手](#16-快速上手)
17. [术语表](#17-术语表)

---

## 1. 项目概述

### 1.1 一句话定义

**NovelForge** 是一个面向长篇小说创作场景的 Multi-Agent（多智能体）协作工作台。

### 1.2 核心能力

- 从故事前提（premise）自动生成分章大纲（ChapterOutline）和场景级节拍（Beat）
- 根据大纲、节拍和历史记忆自动撰写章节正文（content）
- 5 维度自动审查（逻辑 consistency 一致性、人设 fidelity 保真度、伏笔 handling 处理、节奏 pacing、风格 uniformity 统一性）
- 审查后自动修订（revise），形成"写 → 审 → 改 → 再审"质量闭环
- 自然语言驱动的 Director Agent（导演智能体）：你说"写好第3章并检查质量"，它自主决策调用哪些工具
- Supervisor Agent（调度智能体）将写作目标拆分为多步可执行任务并跟踪执行
- 三层异构记忆系统（向量 Vector + 全文 Full-Text + 图 Graph）缓解长文本上下文遗忘
- Web 写作工作区（Workspace）+ 故事全景仪表盘（Dashboard）+ CLI（命令行） + REST API（接口）

### 1.3 它不是什么

- 不是通用 AI 对话工具
- 不是写作辅助插件
- 不是多用途 Multi-Agent 平台
- **是**专为长篇小说场景构建的垂直领域 Agent 工作流引擎（Workflow Engine）

### 1.4 规模

- Python 代码 ~6000 行
- 40+ 个 Pydantic 数据模型
- 7 个 Agent（智能体） + 7 个长篇子系统（Longform Subsystems） + 10 个注册工具（Tools）
- 20+ pytest 测试文件 + 4 个回归评测场景（Eval Cases）

---

## 2. 要解决的问题

### 2.1 四个结构性问题

| 问题 | 表现 | 根因 |
|---|---|---|
| **上下文遗忘**（Context Forgetting） | 写到第30章忘了第3章的设定 | LLM（大语言模型）上下文窗口有限，早期信息被挤出 |
| **人设漂移**（Character Drift） | 角色性格随章节悄悄改变 | 没有持久的角色状态锚点，每次写作 LLM 独立生成 |
| **伏笔遗漏**（Foreshadowing Omission） | 埋了线索忘了回收 | 伏笔的生命周期缺乏系统化追踪 |
| **因果冲突**（Causal Conflict） | 事件发生时序矛盾，逻辑不自洽 | 因果链没有显式建模和自动检测 |

### 2.2 根因分析

这四个问题的本质是同一个：**LLM 的上下文窗口（Context Window）是有限的（通常 4K-128K token 令牌），而长篇叙事的依赖关系是跨章节的（几十万字的范围）。** 单次 LLM 调用无法承载完整的叙事状态。

### 2.3 解决思路

- 用**外部记忆系统**（向量库 ChromaDB + 全文索引 SQLite FTS + 图库 NetworkX）持久化叙事状态
- 每次写作前**自动检索相关历史记忆**并组装成上下文（Context）注入 LLM
- 用**专职 Agent 管线**（Pipeline）而非单 Agent 处理不同的认知任务（规划 vs 写作 vs 审查）
- 用**自动化质量闭环**（Auto-Revision Loop）而非人工审查来保证输出质量

---

## 3. 技术栈

| 技术 | 用途 | 选型理由 |
|---|---|---|
| **Python 3.11+** | 主语言 | AI/LLM 生态最成熟 |
| **Pydantic v2** | 数据校验与序列化（Validation & Serialization） | 全类型系统，自动生成 JSON Schema（结构定义），`model_dump_json()` 一键序列化 |
| **FastAPI + Uvicorn** | Web 服务框架 + 服务器 | 轻量、异步原生（async native）、自动生成 Swagger（接口文档） |
| **Jinja2** | HTML 模板引擎（Template Engine） | Dashboard（仪表盘）和 Workspace（工作区）前端渲染 |
| **cmd2** | CLI 框架（命令行界面） | 增强的 `cmd` 模块，支持命令补全（Tab Completion）和历史记录 |
| **OpenAI SDK** | LLM 调用客户端 | DeepSeek 兼容 OpenAI API 格式，同一套代码即可调用 |
| **ChromaDB** | 向量数据库（Vector Database） | 嵌入式（Embedded）部署，支持语义搜索（Semantic Search） |
| **NetworkX** | 图数据库/图论库 | 角色关系网和因果事件图的存储与图遍历（Graph Traversal） |
| **SQLite FTS5** | 全文检索引擎（Full-Text Search） | 零配置嵌入，中文关键词搜索 |
| **YAML** | 配置文件格式 | 易读、支持注释 |
| **python-docx** | Word 文档导出 | 导出 .docx 格式 |
| **pytest** | 测试框架 | Python 生态标准 |
| **python-dotenv** | 环境变量加载 | 从 .env（环境变量文件）加载 API Key 等密钥 |

---

## 4. 架构全景图

### 4.1 分层架构

```
┌──────────────────────────────────────────────────────────┐
│  接口层（Interface）:  CLI (cmd2) │ REST API (FastAPI) │ Web UI │
├──────────────────────────────────────────────────────────┤
│  编排层（Orchestrator）: Engine (状态机 FSM) │ Director（导演）│ Supervisor（调度）│
│               ToolRegistry（工具注册）│ AutoRevisor（自动修订器）│ EventBus（事件总线）│
│               TraceRecorder（追踪记录器）│ TraceExporter（追踪导出器）│
├──────────────────────────────────────────────────────────┤
│  Agent 层:  Planner（规划师）│ Writer（作家）│ Critic（评论家）│ Editor（编辑）│
│            DirectorAgent（导演智能体）│ SupervisorAgent（调度智能体）│
│            ContinuityAuditor（连续性审计员）│ MemoryExtractor（记忆提取器）│
├──────────────────────────────────────────────────────────┤
│  记忆层（Memory）:  ContextAssembler（上下文组装器）  MemoryRanker（记忆排序器）│
│          ChromaDB（向量库）│ SQLite FTS（全文检索）│ NetworkX（图库）│
├──────────────────────────────────────────────────────────┤
│  长篇层（Longform）:  ForeshadowingTracker（伏笔追踪器）│ CausalityTracker（因果追踪器）│
│          PacingAnalyzer（节奏分析器）│ CharacterStateTracker（角色状态追踪器）│
│          SummaryManager（摘要管理器）│ MemoryEngineV2（记忆引擎）│
├──────────────────────────────────────────────────────────┤
│  LLM 层:  LLMClient（LLM 客户端抽象基类 ABC）│ DeepSeekClient │ MockLLM（模拟客户端）│
├──────────────────────────────────────────────────────────┤
│  持久层（Persistence）:  StoryRepository（故事仓储/JSON持久化）│ ChromaDB │ SQLite │
├──────────────────────────────────────────────────────────┤
│  配置层（Configuration）:  YAML + 环境变量 → AppConfig（应用配置 Pydantic 模型）│
└──────────────────────────────────────────────────────────┘
```

### 4.2 核心工作流（Happy Path / 正常流程）

```
1. start_new_story(premise)                   → Story（故事对象）创建完成 (status=planning 规划中)
2. generate_outline(num_chapters)             → PlannerAgent 生成 ChapterOutline[]（章节大纲列表）
3. generate_beats(chapter_index)              → PlannerAgent 生成 Beat[]（场景节拍列表）
4. write_chapter(chapter_index)               → ContextAssembler 组装上下文
                                              → WriterAgent 写正文
                                              → EditorAgent 润色（polish 可选）
                                              → LongformManager（长篇管理器）处理记忆
5. request_review(chapter_index)              → CriticAgent 审查
                                              → LongformManager 一致性检查
6. apply_revision(chapter_index)              → EditorAgent 修订
   OR
   auto_write_chapter(chapter_index)          → AutoRevisor 迭代质量循环
7. finalize_chapter(chapter_index)            → 章节完成（finalized）
```

---

## 5. 核心数据模型

### 5.1 Story（故事 — 聚合根 Aggregate Root）

```python
class Story(BaseModel):
    id: UUID                                    # 唯一标识（UUID 通用唯一标识符）
    title: str                                  # 书名
    premise: str                                # 故事前提（一句话概括）
    genre: str = "novel"                        # 类型/流派
    style_guide: str = ""                       # 文风指南
    outlines: list[ChapterOutline]              # 所有章节大纲（ChapterOutline 列表）
    chapters: dict[int, Chapter]                # 章节字典（key=章节编号, value=Chapter对象）
    characters: dict[str, Character]            # 角色字典（key=角色ID, value=Character对象）
    world_settings: list[WorldSetting]          # 世界设定列表
    foreshadowings: list[Foreshadowing]         # 伏笔（Foreshadowing）列表
    causal_events: list[CausalEvent]            # 因果事件（CausalEvent）列表
    character_states: dict[str, list[CharacterState]]  # 角色状态历史（key=角色ID, value=该角色各章状态）
    chapter_summaries: dict[int, ChapterSummary]       # 章节摘要（key=章节编号, value=ChapterSummary）
    volume_summaries: list[VolumeSummary]       # 卷摘要（VolumeSummary）列表
    arc_summaries: list[ArcSummary]             # 弧线摘要（ArcSummary）列表
    story_bible: StoryBible                     # 故事圣经（StoryBible — 全局设定汇总）
    memory_cards: list[MemoryCard]              # 记忆卡片（MemoryCard）列表
    auto_revision_reports: dict[int, AutoRevisionReport]  # 自动修订报告
    continuity_reports: dict[int, ContinuityAuditReport]  # 连续性审计报告
    batch_reports: list[BatchWriteReport]       # 批量写作报告
    agent_runs: list[AutonomousRunReport]       # 自主运行报告
    agent_trace_runs: list[AgentTraceRun]       # Agent 执行追踪
    current_chapter: int = 0                     # 当前章节编号
    status: str = "planning"                     # 故事状态（planning/outline_generated/.../completed）
```

### 5.2 关键子模型

#### Chapter（章节 — 带版本控制 Version Control）

```python
class Chapter(BaseModel):
    index: int                          # 章节编号
    title: str                          # 章节标题
    content: str = ""                   # 章节正文
    version: int = 1                    # 版本号（每次修改递增）
    status: str = "draft"               # 状态: draft（草稿）/reviewed（已审查）/revised（已修订）/finalized（已完成）
    summary: str = ""                   # 章节摘要
    beats: list[Beat]                   # 场景节拍（Beat 列表）
    history: list[ChapterVersion]       # 版本历史（ChapterVersion 列表）

    def update_content(self, content: str, status=None, summary=None):
        if self.content:                     # 已有内容时先存档（snapshot 快照）
            self.history.append(self.snapshot())
        self.version += 1                    # 版本号递增
        self.content = content               # 写入新内容
```

#### QualityScores（5 维度质量评分）

```python
class QualityScores(BaseModel):
    logic_consistency: float       # 逻辑一致性（权重 weight 0.25）
    character_fidelity: float      # 角色保真度（权重 0.25）
    foreshadowing_handling: float  # 伏笔处理（权重 0.20）
    pacing: float                  # 叙事节奏（权重 0.15）
    style_uniformity: float        # 风格统一性（权重 0.15）

    def weighted_total(self, weights: dict[str, float] | None = None) -> float:
        # sum(各维度分 × 对应权重) / sum(所有权重)
```

#### 其他重要模型一览

| 模型（Model） | 用途 | 关键字段 |
|---|---|---|
| `ChapterOutline` | 分章大纲 | `chapter_index`（章节编号）, `title`（标题）, `summary`（摘要）, `conflict`（核心冲突）, `pov_character`（视角角色） |
| `Beat` | 场景节拍 | `scene_index`（场景编号）, `description`（描述）, `goal`（目标）, `outcome`（结果） |
| `ReviewReport` | 审查报告（结构化） | `logic_issues`（逻辑问题）, `character_issues`（人设问题）, `pacing_issues`（节奏问题）, `suggestions`（修改建议）, `verdict`（总体判断） |
| `QualityReviewReport` | 质量评分卡（定量） | `scores`（QualityScores 评分对象）, `issues`（RevisionIssue 问题列表）, `overall_comment`（总评） |
| `AutoRevisionReport` | 自动修订报告 | `chapter_index`, `final_content`（最终正文）, `rounds`（每轮记录）, `final_score`（最终分数）, `passed`（是否通过）, `residual_issues`（残存问题） |
| `ContinuityAuditReport` | 连续性审计报告 | `chapter_index`, `risk_score`（风险评分 0-10）, `passed`（是否通过）, `issues`（ContinuityIssue 问题列表） |
| `AgentDecision` | Director 决策 | `selected_tool`（选中工具名）, `tool_args`（工具参数）, `reasoning_summary`（推理摘要）, `should_continue`（是否继续循环） |
| `AgentTraceStep` | 操作追踪步骤 | `step`（步骤号）, `selected_tool`, `tool_args`, `success`（成功与否）, `error_type`（错误类型）, `duration_ms`（耗时毫秒） |
| `AgentTraceRun` | 一次 Director 运行的完整追踪 | `id`, `story_id`, `user_message`（用户指令）, `steps`（AgentTraceStep 列表）, `trace_events`（追踪事件列表）, `final_summary`（终局摘要） |
| `Foreshadowing` | 伏笔 | `id`, `description`（描述）, `created_chapter`（创建章）, `target_chapter`（计划回收章）, `status`（pending待回收/fulfilled已回收/abandoned已放弃） |
| `CausalEvent` | 因果事件 | `id`, `chapter`（所在章）, `description`, `causes`（前置事件ID列表）, `effects`（后置事件ID列表） |
| `CharacterState` | 角色状态快照 | `character_id`（角色ID）, `chapter`, `emotional_state`（情绪）, `location`（位置）, `knowledge_gained`（获得的知识）, `relationship_changes`（关系变化） |
| `MemoryCard` | 记忆卡片 | `id`, `type`（类型）, `content`（内容）, `chapter`, `importance`（重要性 1-10）, `entities`（关联实体）, `tags`（标签） |
| `StoryBible` | 故事圣经 | `core_premise`（核心前提）, `current_direction`（当前走向）, `active_threads`（活跃剧情线）, `character_roster`（角色名册）, `continuity_constraints`（连续性约束）, `world_rules`（世界观规则） |
| `AutonomousRunReport` | 自主运行报告 | `tasks`（AgentTask 任务列表）, `planning_strategy`（规划策略 llm/rule）, `completed_tasks`（已完成任务数）, `failed_tasks`（失败任务数） |
| `ChapterSummary` | 章节摘要 | `chapter_index`, `scene_summaries`（场景摘要）, `chapter_summary`（章节摘要）, `key_events`（关键事件ID） |
| `VolumeSummary` | 卷摘要 | `volume`（卷号）, `chapter_range`（章节范围）, `summary`（卷摘要文本） |
| `ArcSummary` | 弧线摘要 | `arc`（弧线号）, `chapter_range`, `summary`, `key_threads`（关键线索）, `open_questions`（未解问题） |
| `BatchWriteReport` | 批量写作报告 | `start_chapter`, `end_chapter`, `results`（BatchChapterResult 列表）, `completed`, `failed` |
| `ChapterVersion` | 章节历史版本 | `version`, `content`, `status`, `summary`, `created_at`（创建时间戳） |
| `Character` | 角色 | `id`, `name`（名字）, `age`（年龄）, `appearance`（外表）, `personality`（性格）, `motivation`（动机）, `weakness`（弱点）, `arc`（角色弧线）, `relationships`（关系字典） |
| `WorldSetting` | 世界设定 | `id`, `category`（分类）, `content`, `metadata`（元数据） |
| `ContinuityIssue` | 连续性问题 | `dimension`（维度）, `severity`（严重度 high/medium/low）, `description`, `evidence`（证据）, `suggestion`（建议） |
| `RevisionIssue` | 修订问题 | `dimension`, `severity`, `description` |
| `AgentTask` | 可执行任务 | `id`, `agent`（执行者）, `action`（动作）, `reason`（理由）, `chapter_index`, `status`（pending/running/completed/failed） |

---

## 6. Agent 体系

### 6.1 BaseAgent（基类 — 所有 Agent 的公共父类）

文件位置：`novelforge/agents/base.py`

```python
class BaseAgent:
    def __init__(self, llm: LLMClient):
        self.llm = llm  # 依赖注入（Dependency Injection）LLM 客户端

    def _chat(self, system: str, user: str) -> str:
        """构造 [system_msg, user_msg] 发送给 LLM → 返回文本"""
        return self.llm.chat_completion([
            {"role": "system", "content": system},   # 系统消息（角色设定）
            {"role": "user", "content": user},        # 用户消息（具体任务）
        ])

    def _extract_json(self, text: str) -> Any:
        """从 LLM 返回文本中提取 JSON（三层容错 Fault Tolerance）"""
        # 1. 匹配 ```json ... ``` 代码块（Fenced Code Block）
        # 2. 直接 json.loads() 解析整段文本
        # 3. 正则（Regex）提取首个 {...} 或 [...]

    def _parse_model(self, text: str, ModelType) -> ModelType:
        """提取 JSON → Pydantic model_validate() 校验"""
        return ModelType.model_validate(self._extract_json(text))
```

所有 Agent 通过 `self._chat()` 调用 LLM，通过 `_parse_model()` 解析结构化返回。

关键设计：`_extract_json` 的三层容错解决了 LLM 输出格式不可靠的问题——LLM 有时包在 markdown 代码块里，有时裸输出 JSON，有时前面还有废话，三层尝试覆盖了所有常见情况。

### 6.2 PlannerAgent（规划智能体 — 结构规划）

**职责**：从故事前提生成分章大纲，为单章生成场景节拍。

**generate_outline(premise: str 故事前提, num_chapters: int 目标章节数) → list[ChapterOutline]（章节大纲列表）**

```
1. system prompt（系统提示词）: "你是专业长篇小说规划师。严格输出 JSON 数组"
2. user prompt（用户提示词）: premise + num_chapters → 发送 LLM
3. _parse_model_list(raw, ChapterOutline)  → 解析为 ChapterOutline 对象列表
4. fallback（兜底规则）: LLM 失败 → 生成模板大纲（"第 i 章", 通用冲突描述）
```

**generate_beats(chapter_outline: ChapterOutline 章节大纲, context: str 上下文) → list[Beat]（场景节拍列表）**

```
1. system prompt: "你是小说分场设计师。输出 Beat JSON 数组: scene_index, description, goal, outcome"
2. user prompt: outline.model_dump_json() + context[:3000]（上下文截断至3000字符）
3. _parse_model_list(raw, Beat)
4. fallback: 3 个模板节拍（开场 → 中段遭遇阻碍 → 结尾转折悬念）
```

### 6.3 WriterAgent（写作智能体 — 正文生成）

**职责**：接收大纲、节拍、上下文、文风指南→ 输出小说正文。

**write_chapter(chapter_index: int, outline: ChapterOutline, beats: list[Beat], assembled_context: str 组装好的上下文, style_guide: str 文风指南) → str（纯文本正文）**

```
1. system prompt: 5 条精确写作指令
   - 按场景推进，用具体动作/对话/环境细节/心理变化承载剧情
   - 禁止"本章讲述/随后发生/他经历了"等摘要式句子
   - 每个场景必须有目标（goal）→ 阻力（obstacle）→ 转折（turn）→ 结果（outcome）
   - 语言有节奏和画面感，避免流水账和空泛热血
   - 结尾留情绪余波（emotional residue）/信息钩子（hook）/局势推进
2. user prompt: 大纲 JSON + 节拍 JSON + 上下文 + 输出要求
3. self._chat(system, user) → LLM → .strip()
4. 没有 fallback — Writer 是核心产出环节，失败则整个流程失败
```

### 6.4 CriticAgent（审核智能体 — 质量审查）

**职责**：两种审查模式 —— 结构化审查（ReviewReport）和质量评分卡（QualityReviewReport）。

**review_chapter(chapter_content: str 章节正文, chapter_outline: ChapterOutline, character_list: list[Character] 角色列表, plot_memory: list[dict]|str 情节记忆, longform_context: str 长篇一致性上下文) → ReviewReport**

```
输出: {logic_issues（逻辑问题）, character_issues（人设问题）, pacing_issues（节奏问题）, suggestions（建议）, verdict（判断）}
fallback: 返回 "未能解析模型审查结果，请人工复核"
```

**review_quality_scorecard(content: str, chapter_outline: ChapterOutline, story: Story 完整故事对象, extra_context: str 额外上下文) → QualityReviewReport**

```
1. system prompt: 5 维度 1-10 评分 + 问题列表 + 总评
2. user prompt 中注入 _get_memory_snapshot(story):
   - pending_foreshadowings（未回收伏笔 前10条）
   - recent_causal_events（最近因果事件 前12条）
   - latest_character_states（每个角色的最新状态）
   - recent_chapter_summaries（最近5章摘要）
   # 这保证 Critic 能做跨章节的一致性判断！
3. _parse_model(raw, QualityReviewReport)
4. _clamp(value: float) → 确保评分在 1.0-10.0 范围内
5. fallback: _fallback_quality_review() 规则化评审
   - 篇幅 < 300 字 → pacing（节奏）= 6.0
   - 大纲冲突关键词不在正文中 → logic_consistency（逻辑一致性）= 6.5
   - 存在逾期未回收的伏笔 → foreshadowing_handling（伏笔处理）= 6.0
   - 文风关键词缺失 → style_uniformity（风格统一）= 7.0
   - 默认全 8.0
```

### 6.5 EditorAgent（编辑修订智能体 — 三种编辑模式）

**职责**：基于审查报告修订、纯文笔润色、基于质量卡逐项修复。

**revise_chapter(chapter_content: str 原正文, review_report: ReviewReport 审查报告, style_guide: str 文风指南) → str（修订后全文）**
- 根据 ReviewReport 逐条修复逻辑/人设/节奏问题
- 输入：审查报告 JSON + 原文→ 输出修订后全文

**polish_prose(content: str 草稿, instructions: str 润色指令) → str（润色后正文）**
- 文笔润色，保留剧情核心不动
- 改进目标：场景质感、动作细节、心理层次、对话自然度、结尾余味
- 调用方（engine._polish_draft_if_enabled）用 `polished or content` 保证失败时回退到原文

**revise_from_quality_report(chapter_content: str, quality_report: QualityReviewReport 质量评分卡, style_guide: str) → str**
- 根据 QualityReviewReport 逐项修复 5 个维度问题
- 专用于 AutoRevisor 自动修订循环中

### 6.6 NovelDirectorAgent（导演智能体 — 自然语言编排）

**职责**：根据用户自然语言意图和当前故事状态，自主决策下一步调用哪个工具。

**run(story_id: str, user_message: str 用户自然语言指令, max_steps: int 最大步数, story: Story, tool_registry: ToolRegistry 工具注册表) → AgentTraceRun（追逐运行记录）**

每次循环执行：
```
1. decide(story, user_message, step, run, tools) → AgentDecision
   - 将故事状态序列化为 JSON（标题/前提/状态/章节/伏笔/前6步执行记录 last_observations）
   - 将 10 个工具的 JSON Schema 列出（tool_registry.list_specs()）
   - LLM 返回: {selected_tool（选中工具）, tool_args（工具参数）, reasoning_summary（推理摘要）, should_continue（是否继续循环）}

2. tool_registry.execute(decision.selected_tool, decision.tool_args) → dict
   - Pydantic 参数校验（model_validate）
   - 执行工具 → 调用 engine 方法
   - 记录 Trace（追踪）

3. 成功且 should_continue=True → 继续循环（让 LLM 再决策下一步）
   成功且 should_continue=False → 结束
   失败 → 错误分类（classify_exception）→ 可恢复的错误自动修复并重试（最多 2 次）
```

**decide() 的关键设计**：
- 故事状态中 `chapters` 只取最近 12 章（`[-12:]` 截断）
- `pending_foreshadowings` 只取前 12 条
- `last_observations` 是前 6 步的执行结果 → 让 LLM 有 "执行记忆"（Execution Memory）
- fallback: `_fallback_decision()` 用关键词匹配做规则路由 ——"伏笔" → list_foreshadowings, "检查/审查" → review_chapter, "改/修" → revise_chapter, "继续/下一章/write" → auto_write_chapter, 其他 → show_status

**错误恢复机制（_recovery_decision）**：
- `tool_arg_invalid`（工具参数非法） → 修复参数（默认取 `max(story.current_chapter, 1)`），重试
- `precondition_missing`（前置条件缺失）：
  - 缺大纲 → 自动调 `create_outline`
  - 缺节拍 → 自动调 `create_beats`
- `quality_gate_failed`（质量门控失败） → 路由到 `auto_write_chapter`
- `tool_execution_failed`（工具执行失败） → 重试
- 最多 2 次恢复尝试（`recovery_attempts < 2`），超限标记整个 run 失败

### 6.7 SupervisorAgent（调度智能体 — 任务规划与拆解）

**职责**：将用户的写作目标拆分为可执行的多步任务序列。

**plan_writing_run(story: Story, objective: str 目标, start_chapter: int, end_chapter: int, use_auto_revision: bool 是否用自动修订) → AutonomousRunReport**

```
1. _plan_with_llm() → LLM 规划任务序列（优先）
   - 将故事状态 + 可用动作列表（allowed_actions）+ 章节范围发给 LLM
   - LLM 返回: {strategy（策略）, notes（备注）, tasks[]（任务列表）}
   - _validate_llm_tasks() 三层校验:
     a) action 是否在 allowed_actions 内
     b) chapter_index 是否在 [start, end] 范围内
     c) 去重（同一章的同一动作不重复）
   - _complete_minimum_plan() 兜底补充 — 确保每个章节都有最少必要步骤

2. LLM 规划失败 → _rule_plan() 确定性规划
   固定生成 5N+1 个任务（N=章节数）:
     Task 0: ensure_outline（确保大纲覆盖）
     for each chapter（每章循环）:
       generate_beats（生成节拍）
       → write_chapter 或 auto_write_chapter（写正文）
       → audit_chapter_continuity（审核连续性）
       → memory_checkpoint（记忆检查点）

3. 返回 AutonomousRunReport(planning_strategy="llm" 或 "rule")
```

### 6.8 ContinuityAuditorAgent（连续性审计智能体 — 长篇一致性风险检查）

**职责**：检查故事圣经违规（Story Bible Violation）、角色状态矛盾（Character State Contradiction）、伏笔逾期（Foreshadowing Overdue）、因果缺口（Causal Gap）、位置跳变、能力漂移等。

**audit_chapter(story: Story, chapter_index: int, content: str, longform_context: str) → ContinuityAuditReport**

LLM 审查 + 规则 fallback:

```
规则 fallback（_rule_audit）四项检测:
  1. 逾期伏笔检测: target_chapter（计划回收章）≤ chapter_index（当前章）
     且 status == "pending"（仍未回收）→ 风险为 high（高）
  2. 章节冲突落实: outline.conflict（大纲冲突描述）的关键词不在正文中 → 风险为 medium（中）
  3. 连续性约束检查: story_bible.continuity_constraints（连续性约束列表）中
     涉及 injury/secret/foreshadowing/ability 的约束是否被提及 → 风险为 medium
  4. 角色位置跳变: 前后章 location（位置）不同但无 knowledge_gained（知识获取）→ 风险为 low（低）

risk_score（风险评分）= sum(severity_weight（严重度加权）for issue in issues)
  low=1.5, medium=3.0, high=5.0
  risk_score 上限 10.0

passed（通过）= risk_score < 7.0 AND 无 high 严重度问题
```

### 6.9 MemoryExtractorAgent（记忆提取智能体 — 结构化记忆抽取）

**职责**：从章节正文中提取结构化持久记忆（角色/世界设定/关系/连续性约束）。

**extract_chapter_memory(story: Story, chapter_index: int, content: str) → MemoryExtractionResult**

输出（MemoryExtractionResult）包含四个字段：
- `characters: list[Character]` —— 新增或更新的角色
- `world_settings: list[WorldSetting]` —— 新增世界设定
- `relationships: list[ExtractedRelationship]` —— 角色关系 {source 源角色, target 目标角色, relation 关系描述}
- `continuity_constraints: list[str]` —— 连续性约束

规则 fallback（_rule_extract）使用的关键词映射表：
- "football/足球/goalkeeper/门将" → sport_system（运动体系）
- "training/训练" → training（训练）
- "王者荣耀/后羿" → game_link（游戏关联能力）
- "球场" → location（地点）
- "伤/injury/受伤" → 伤情追踪约束
- "秘密/secret/真相" → 保留悬念约束

提取结果通过 `LongformManager._apply_extraction()` 合并到 Story 对象中 —— 新角色直接加入，已有角色只更新非空字段，用 `_merge_text()` 拼接性格描述（去重）。

---

## 7. 记忆系统

### 7.1 设计理念 —— 为什么是三层存储

| 存储 | 解决什么问题 | 局限性 |
|---|---|---|
| **ChromaDB**（向量库 Vector Store） | 语义相似性搜索 ——和第20章大纲意思最接近的历史记忆 | 不保证精确命中特定名词（"近似匹配"的固有局限） |
| **SQLite FTS5**（全文检索 Full-Text Search） | 关键词精确匹配 ——大纲中提到的专有名词在前文确切出现过几次 | 不理解语义，纯字符串匹配 |
| **NetworkX**（图库 Graph Store） | 关系结构查询 ——角色关系网、因果事件链是图结构，塞进向量库是错的 | 只能处理图数据 |

三层各司其职，互补而非替代。同时查三种库，结果统一汇入 ContextAssembler。

### 7.2 ChromaDB（向量库）

**4 个 collection（集合）**：

| Collection | 存储内容 | 何时写入 |
|---|---|---|
| `characters`（角色） | 角色属性拼接文本（名字 + 年龄 + 外表 + 性格 + 动机 + 弱点 + 弧线） | MemoryExtractor 提取后，`_index_extracted_memory()` 写入 |
| `world`（世界设定） | 世界设定文本 | MemoryExtractor 提取后 |
| `plot_summaries`（情节摘要） | 章节摘要（chapter.summary） | 每章写完后，`_index_chapter()` 写入 |
| `memory_cards`（记忆卡片） | 记忆卡片内容 | MemoryEngineV2 生成后，`_process_chapter_memory()` 写入 |

每个文档（Document）附带 metadata（元数据）：`story_id`（故事ID）, `type`（类型）, `chapter`（章节号）, `importance`（重要性）, `entities`（关联实体）, `tags`（标签）。

查询时始终按 `story_id` 过滤，确保仅召回当前故事的相关记忆，不跨故事混淆。

### 7.3 SQLite FTS5（全文检索）

每章正文作为一个文档索引，doc_id（文档ID）格式：`"{story_id}:chapter:{index}:v{version}"`。

版本号嵌入 doc_id 意味着**同章修改不会覆盖旧索引**——旧版本在新版本写入时被替换。支持中文关键词搜索（依赖 FTS5 内置的 unicode61 tokenizer 分词器）。

### 7.4 NetworkX（图库）

- **节点（Node）**：`"{story_id}:character:{character_id}"`，附带角色完整属性 dict
- **边（Edge）**：`(source_node, target_node, relation_type)` —— 有向边，标签为关系描述
- **ego_network(node_id, depth=1)**：BFS（广度优先搜索）获取该角色的 1 层邻居子图

用途：写作前查询视角角色（POV Character）的关系网，确保 Writer 写的互动不违反已有关系设定。

### 7.5 ContextAssembler（上下文组装器）

文件位置：`novelforge/context/assembler.py`

**assemble_writing_context(chapter_index: int, story: Story) → str（上下文大字符串）**

完整流程：
```
1. 构造查询文本（query）: outline.title + summary + conflict + pov_character（拼接大纲的关键字段）

2. 构建优先级分区列表 sections: list[tuple[int, str]]（(优先级分, 文本) 元组列表）
   (100) 故事前提（story.premise）— 最高优先级
   (95)  文风指南（story.style_guide）
   (90)  本章大纲 JSON（outline.model_dump()）
   (88)  LongformManager 增强上下文（MemoryEngineV2.build_context_pack() 输出）
   (85)  场景节拍（chapter.beats model_dump）
   (70)  视角角色关系网（graph_store.get_ego_network 结果）

3. 三库检索:
   ChromaDB: 遍历 4 个 collection × 各取 k=12 条 → 最多 48 条原始命中
   → MemoryRanker.rank_vector_hits() 多维评分 → 取 top 12
   → 每条的 sections 优先级为 50

   SQLite FTS: text_store.search(query, limit=5) → 5 条文本片段
   → 每条的 sections 优先级为 40（最低，因为它们只是关键词匹配无语义理解）

4. sections.sort(key=优先级分, reverse=True)  # 按优先级降序排列
5. 双换行（\n\n）拼接所有文本
6. _truncate(context) → 截断至 max_context_tokens × 4 字符（默认 6000×4=24000 字符）
   截断方式: text[:max_chars] — 暴力切片，不做语义分割
```

`last_context_stats`（上下文统计 dict）记录每次组装的统计信息：向量命中数、排序后数量、FTS 命中数、是否包含长篇上下文、总记忆命中数。这些数据会被 TraceRecorder 用于追踪记录。

### 7.6 MemoryRanker（记忆排序器）

文件位置：`novelforge/longform/ranker.py`

**纯规则算法，零 LLM 调用。**

**rank_vector_hits（对 ChromaDB 返回的向量命中评分）：**

```python
最终分 = 原始向量相似度（vector_score）× 10.0                           # 语义相关性基线
       + 类型权重（TYPE_WEIGHTS）:                                      # 类型加权
           foreshadowing（伏笔）: 6.0
           character_state（角色状态）: 5.0
           causal_event（因果事件）: 4.0
           chapter_summary（章节摘要）: 3.0
           world（世界设定）: 3.0
           character（角色）: 3.0
       + recency_score（时效性分）= max(0.0, 5.0 - (distance / 20.0))
         # distance = |当前章节 - 记忆章节|
         # 距离超过 100 章完全衰减为 0，未来章节返回 -4.0（惩罚）
       + query 词重叠分（query_overlap）= min(8.0, 重叠词数 × 2.0)
         # query_terms（查询词集）∩ doc_terms（记忆词集）的重叠度
       + 实体匹配分（entity_match）= 7.0（如果记忆关联的角色 entity 在查询实体中出现）
```

**rank_cards（对 MemoryCard 记忆卡片评分）：**

```python
最终分 = card.importance（卡片重要性 1-10）                             # 结构化的优先级
       + 类型权重（同上 TYPE_WEIGHTS）
       + recency_score（同上）
       + 实体匹配分 = 7.0
       + query 词重叠分（同上）
       + last_seen 分（最近出现分）= max(0.0, 2.0 - (distance / 100.0))
         # 卡片上次被看到的章节距离当前章的距离，越近越高
```

**为什么不用 LLM 排序？**
1. **可复现（Reproducible）** — 相同输入永远相同结果
2. **零延迟** — 不额外调 API
3. **零成本** — 不消耗 token
4. **排序本质是算法问题** — 规则公式比 LLM 更可靠、更适配

---

## 8. 长篇一致性子系统

### 8.1 LongformManager（长篇管理器 — 统一门面 Facade）

文件位置：`novelforge/longform/manager.py`

**process_new_chapter(story: Story, chapter_index: int, content: str) → dict**

每章写完或修订后触发，顺序执行 7 个子系统（全部是副作用函数，修改 Story 对象）：

```
1. MemoryExtractorAgent.extract_chapter_memory() → MemoryExtractionResult
   → _apply_extraction() 合并到 Story.characters / Story.world_settings

2. SummaryManager.generate_chapter_summary() → ChapterSummary
   → story.chapter_summaries[chapter_index] = summary

3. CausalityTracker.extract_events_from_chapter() → list[CausalEvent]
   → 先删同章旧事件（过滤掉 event.chapter == chapter_index 的记录）
   → check_conflicts() 验证（前因存在、时序正确、无因果循环）
   → add_event() 通过验证的写入

4. ForeshadowingTracker.analyze_new_chapter() → list[Foreshadowing]
   → LLM/规则检测新伏笔 → register() 注册
   → _auto_fulfill() 遍历 pending 伏笔自动回收

5. CharacterStateTracker.extract_state_from_chapter() → list[CharacterState]
   → 每个 state 通过 update_state() 写入 story.character_states[character_id]

6. PacingAnalyzer.analyze_chapter() → dict{conflict_intensity, dialogue_ratio, description_density, plot_progress}
   → 存入 pacing_history（节奏历史），每个 story_id 独立存储

7. MemoryEngineV2.process_chapter() → dict{memory_cards, arc_summary, story_bible}
   → _upsert_chapter_cards()  → 更新 arc_summary → 更新 story_bible → _trim_cards() 修剪
```

### 8.2 ForeshadowingTracker（伏笔追踪器）

文件位置：`novelforge/longform/foreshadowing.py`

**analyze_new_chapter(story, chapter_index, content) → list[Foreshadowing]**

流程：
1. LLM 检测（`_llm_detect`）：从正文识别潜在伏笔线索 → 返回 Foreshadowing 对象列表
2. 规则检测（`_rule_detect`）：关键词匹配 "秘密/预言/钥匙/梦/纹章/信物/奇怪/似曾相识/没有解释" → 只取首条（break 跳出）
3. 去重检查（`_is_duplicate`）：同章同描述的不重复注册
4. `self.register(story, item)`—— 写入 story.foreshadowings

**自动回收（_auto_fulfill）**：
- 遍历所有 `status == "pending"` 的伏笔
- 从伏笔描述中提取 2+ 字符关键词（`re.findall(r"[\w\u4e00-\u9fff]{2,}", description)`）
- 判断条件：关键词出现在新章正文中 AND 正文中出现回收信号词（"真相/原来/终于/揭开/回想"）
- 满足条件 → `self.fulfill(story, item.id, chapter_index)` —— 状态改为 fulfilled，补充回收章记录

**fulfill(story, foreshadowing_id, chapter)** → 标记为 fulfilled，notes 追加 "回收于第 N 章"

### 8.3 CausalityTracker（因果追踪器）

文件位置：`novelforge/longform/causality.py`

**extract_events_from_chapter(story, chapter_index, content) → list[CausalEvent]**

流程：
1. 删除同章旧事件（`story.causal_events = [e for e in story.causal_events if e.chapter != chapter_index]`）
2. LLM 提取（`_llm_extract`）或规则提取（`_rule_extract`）
   - 规则：按句号/感叹号/问号/换行切分句子 → 包含 "决定/发现/失去/得到/击败/背叛/真相/受伤/离开" 等关键词的句子视为因果事件
3. `check_conflicts()` 验证三项：
   - **前因缺失**：`new_event.causes` 中的 event_id 在 `by_id`（已有事件哈希表）中不存在
   - **未来锚定**：前因事件发生章节号 > 当前事件章节号（时间悖论）
   - **因果循环**：`_has_cycle()` —— DFS（深度优先）环检测算法（三色标记：visiting 正在访问 / visited 已访问）
4. 通过验证的 `self.add_event()` —— 建立前置事件和后置事件之间的双向链接

### 8.4 PacingAnalyzer（节奏分析器 — 零 LLM）

文件位置：`novelforge/longform/pacing.py`

**纯规则统计，不调任何 LLM。**

**analyze_chapter(content: str) → dict** 四个指标：

| 指标 | 计算方式 |
|---|---|
| `conflict_intensity`（冲突强度） | 14 个冲突词出现次数 + 11 个动作词出现次数 / 2 → clamp(1, 10) |
| `dialogue_ratio`（对话比例） | 以" / 「 / " / ' / ：/ :" 开头的行数 / 总行数 |
| `description_density`（描述密度） | 平均句长 / 80 |
| `plot_progress`（情节推进度） | 动作词 + 冲突词 + 句子数/8 → clamp(1, 10) |

**check_pacing_trend(analyses: list[dict]) → str** 趋势预警：
- 最近 3 章 `conflict_intensity`（冲突强度）均值 ≤ 3 → "预警：最近三章冲突强度偏低，建议插入明确转折、失败代价或对抗场景"
- `dialogue_ratio`（对话占比） ≥ 0.7 → "预警：对话占比过高，建议增加行动、场景压力或可视化冲突"
- 否则 → "节奏趋势正常"

### 8.5 CharacterStateTracker（角色状态追踪器）

文件位置：`novelforge/longform/character_state.py`

**extract_state_from_chapter(story, chapter_index, content, characters) → list[CharacterState]**

- LLM 模式：提取 `{character_id, chapter, emotional_state, location, knowledge_gained, relationship_changes}`
- 规则模式（`_rule_extract`）：
  - `_guess_emotion(content)`：关键词匹配 —— 害怕/恐惧/发抖 → "恐惧"; 愤怒/怒火/咬牙 → "愤怒"; 高兴/兴奋/笑 → "兴奋"; 默认 → "紧张"
  - `_guess_location(content)`：地点关键词 —— 球场/学校/城市/城墙/湖/房间/训练场 → 匹配到的
  - `_guess_knowledge(content)`：认知关键词 —— 发现/知道/明白/意识到/真相 → 生成知识获取记录

**check_consistency(state_before: CharacterState | None 前章状态, state_after: CharacterState 当前章状态) → list[str]** 自动检测：
- 位置变更但无过渡记录 → 告警
- 情绪极端反转（恐惧→兴奋）但无关系变化记录 → 告警
- "怕水"角色出现在湖相关场景且未记录克服 → 告警

### 8.6 SummaryManager（分层摘要管理器）

文件位置：`novelforge/longform/summaries.py`

**分层摘要结构（Hierarchical Summaries）**：

| 层级 | 单位 | 生成时机 | 压缩上限 |
|---|---|---|---|
| 场景摘要（Scene Summary） | 按段落切分，每段压缩 | 每章 LLM/规则 | 80 字/段 |
| 章节摘要（Chapter Summary） | 整章合并 | 每章 LLM/规则 | 300 字 |
| 卷摘要（Volume Summary） | 每 10 章一卷 | 每章触发，拼接卷内所有摘要 | 500 字 |
| 弧线摘要（Arc Summary） | 每 20 章一弧 | MemoryEngineV2 维护 | 900 字 |

**get_rolling_context(story, current_chapter, window=3) → str**（滚动上下文）
= 最近 window 章摘要 + 当前卷概览 + 全书主线概要 → 拼接为上下文字符串

### 8.7 MemoryEngineV2（记忆引擎 — 确定性算法）

文件位置：`novelforge/longform/memory_engine.py`

**完全确定性算法，不需要 LLM。**

**process_chapter(story, chapter_index, summary, events, foreshadowings, character_states) → dict**

```
1. _upsert_chapter_cards()
   将 4 种对象转为 MemoryCard（记忆卡片）:
   - ChapterSummary → type="chapter_summary", importance=7, tags=["summary"]
   - CausalEvent    → type="causal_event", importance=8, tags=["causal_event"]
   - Foreshadowing  → type="foreshadowing", importance=9, tags=["foreshadowing", status]
     # 伏笔优先级最高——丢了伏笔后续章会出硬伤
   - CharacterState → type="character_state", importance=8, entities=[character_id], tags=["character_state"]
   按 chapter 去重合并到 story.memory_cards

2. update_arc_summary(chapter_index)
   弧线 = 每 20 章一个弧（arc_index = max(1, (chapter_index-1)//20 + 1)）
   拼接弧内章节摘要 + 因果事件 + pending 伏笔 → _compress() 压缩至 900 字符

3. update_story_bible()
   更新故事圣经（StoryBible）的 5 个字段:
   - core_premise（核心前提）← story.premise
   - current_direction（当前走向）← 最新摘要压缩至 600 字符
   - active_threads（活跃剧情线）← pending 伏笔描述 + 最近因果事件 → _dedupe 去重 → 取前 24 条
   - character_roster（角色名册）← 每个角色名 + 最新状态（情绪 + 位置）→ 压缩至 240 字符/角色
   - continuity_constraints（连续性约束）← 原有约束 + pending 伏笔约束 + 角色最新状态约束 → 取前 30 条

4. _trim_cards()
   超过 max_cards（5000）张 → 按 (importance 重要性, chapter 章节) 降序排
   → 保留前 5000 → 再按 (chapter, importance) 升序恢复排序
```

**build_context_pack(chapter_index, story) → ChapterContextPack（上下文数据包）**

为写作组装结构化的分层上下文包：
```
[Story Bible]          → bible.core_premise + current_direction + active_threads + world_rules
[Current Arc]          → 当前弧线摘要（如果存在）
[Current Volume]       → 当前卷摘要（如果存在）
[Recent Chapters]      → chapter_index 前 5 章的 chapter_summary
[Character States]     → 实体匹配到的角色最新状态（_format_character_states）
[Open Foreshadowing]   → pending 伏笔按紧急性排序（target_chapter 距离当前最近的优先）
[Causal Threads]       → 最近 12 条因果事件的 description
[Retrieved Memory Cards] → MemoryRanker.rank_cards() 排序后的记忆卡片
[Continuity Constraints] → story_bible.continuity_constraints 前 12 条
```

`format_context_pack(pack, max_chars=9000)` 格式化为 `[Section Title]\n-content` 的 Markdown 结构，截断至 9000 字符。

---

## 9. 编排层

### 9.1 NovelForgeEngine（核心引擎 — 有限状态机 FSM）

文件位置：`novelforge/orchestrator/engine.py`（906 行）

**状态机（WorkflowState 枚举）**：

```
planning（规划中）
  ↓ generate_outline
outline_generated（大纲已生成）
  ↓ generate_beats
chapter_beats_ready（节拍已就绪）
  ↓ write_chapter
chapter_draft（章节草稿）
  ↓ request_review
reviewing（审查中）
  ↓ apply_revision
revising（修订中）
  ↓ finalize_chapter
chapter_finalized（章节已完成）
  ↓ 最后一章完成
completed（全书完成）
```

**核心方法一览**：

| 方法 | 功能 | 主要调用链 |
|---|---|---|
| `start_new_story(premise, title, genre, style_guide)` | 创建新故事 | `Story()` 构造函数 → `save_state()` 持久化 |
| `generate_outline(num_chapters, force)` | 生成/补充大纲 | `PlannerAgent.generate_outline()` |
| `generate_beats(chapter_index)` | 生成场景节拍 | `ContextAssembler.assemble_writing_context()` → `PlannerAgent.generate_beats()` |
| `write_chapter(chapter_index)` | 写正文 | 先确保节拍 → `ContextAssembler` → `WriterAgent.write_chapter()` → `_polish_draft_if_enabled()` → `_process_chapter_memory()` |
| `request_review(chapter_index)` | 审查章节 | ChromaDB 检索记忆 → `CriticAgent.review_chapter()` → `LongformManager.review_chapter_consistency()` |
| `apply_revision(chapter_index, revised_content)` | 修订章节 | 获取审查报告 → `EditorAgent.revise_chapter()` |
| `auto_write_chapter(chapter_index)` | 自动写+审+改 | `AutoRevisor(config).run(chapter_index)` |
| `batch_write_chapters(start, end, use_auto_revision, progress_callback)` | 批量写作 | 循环 `auto_write_chapter` 或 `write_chapter`，通过 progress_callback 实时推送进度 |
| `agentic_writing_run(objective, start, end, use_auto_revision, progress_callback)` | 自主运行 | `SupervisorAgent.plan_writing_run()` → 逐任务执行 `_execute_agent_task()` |
| `run_director_agent(user_message, max_steps)` | Director 运行 | `NovelDirectorAgent.run()` + `ToolRegistry` |
| `export_markdown(output_path)` | 导出 Markdown | 拼接所有章节 → `write_text()` |
| `export_docx(output_path)` | 导出 Word | `python-docx` `Document()` → 设置宋体字体/首行缩进/行距 |
| `save_state()` | 持久化故事 | `StoryRepository.save(story)` —— `story.model_dump_json(indent=2)` |
| `load_state(story_id)` | 加载故事 | `StoryRepository.load(story_id)` —— `Story.model_validate_json()` |
| `delete_story_data(story_id)` | 删除故事 | 四层清理：JSON 文件 + ChromaDB + SQLite FTS + NetworkX |
| `finalize_chapter(chapter_index)` | 完成章节 | 标记 status="finalized"，最后一章则 story.status="completed" |
| `advance_to_next_chapter()` | 推进到下一章 | `max(story.current_chapter + 1, 1)` → `generate_beats(next_index)` |

**_polish_draft_if_enabled(story, chapter_index, content) → str**（可选润色）：
```
if not config.story.auto_polish_drafts: return content  # 配置关闭则直接返回
构造 instructions（润色指令）:
  f"目标字数约 {config.story.prose_target_words} 字；
   把草稿改成更有小说质感的完整正文。
   保留章节大纲、节拍和长篇记忆中的事实，不改变结局走向。
   本章标题: {outline.title}；核心冲突: {outline.conflict}；
   文风: {story.style_guide or '清晰克制，有画面感...'}"
polished = self.editor.polish_prose(content, instructions)
return polished or content  # 润色失败（返回空字符串）→ 回退到原文
```

**_process_chapter_memory(story, chapter) → None**（全量记忆处理）：
```
1. _index_chapter() → SQLite FTS 索引全文 + ChromaDB plot_summaries 索引摘要
2. LongformManager.process_new_chapter() → 7 个子系统全量处理
3. _index_extracted_memory() → ChromaDB 索引角色/世界设定 + NetworkX 更新图
4. 如果 memory_cards 不为空 → ChromaDB memory_cards collection 批量写入
5. _audit_processed_chapter() → ContinuityAuditorAgent 自动审计
```

### 9.2 ToolRegistry（工具注册表）

文件位置：`novelforge/orchestrator/tool_registry.py`

**注册的 10 个工具**：

| 工具名（tool name） | 参数模型（args_model） | 功能 |
|---|---|---|
| `show_status`（显示状态） | `EmptyArgs`（空参数） | 显示故事进度、大纲数、章节数、角色数、记忆卡数、伏笔数 |
| `create_outline`（创建大纲） | `CreateOutlineArgs`：`num_chapters: int\|None` | 创建/扩展章节大纲，默认取已有数 |
| `create_beats`（创建节拍） | `ChapterIndexArgs`：`chapter_index: int（≥1）` | 为指定章生成 3-5 个场景节拍 |
| `write_chapter`（写章节） | `ChapterIndexArgs` | 写草稿（自动含节拍生成+可选润色+记忆处理） |
| `review_chapter`（审查章节） | `ChapterIndexArgs` | 审核章节的结构化问题+长篇一致性 |
| `revise_chapter`（修订章节） | `ReviseChapterArgs`：`chapter_index + revised_content: str\|None` | 基于审查报告修订（可选替换内容） |
| `auto_write_chapter`（自动写章） | `ChapterIndexArgs` | 自动写+审+改迭代直到质量达标或达上限 |
| `audit_continuity`（审计连续性） | `ChapterIndexArgs` | 长篇一致性风险检查 |
| `update_memory`（更新记忆） | `ChapterIndexArgs` | 为指定章重新索引和提取记忆 |
| `list_foreshadowings`（列出伏笔） | `ListForeshadowingsArgs`：`status: str\|None` | 列出伏笔，可选按状态过滤 |

每个工具通过 `TOOL_ARG_SCHEMAS`（`tool_schemas.py`）映射到对应的 Pydantic 参数模型。

**execute(name: str, args: dict, run_id: str) → dict 执行流程**：
```
1. 查找工具 → 不存在返回 {success: False, error_type: "tool_arg_invalid"}
2. tool.args_model.model_validate(args) → Pydantic 运行时校验 → 失败返回 {success: False, error_type: "tool_arg_invalid"}
3. trace_timer 上下文管理器开始计时（perf_counter 高精度计时）
4. tool.handler(validated_args) → 调用 engine 的对应方法
5. 成功 → 返回 {success: True, observation: str, data: dict, trace_event: dict, duration_ms: int}
6. 异常 → classify_exception(exc) 分类 → 返回 {success: False, error_type: str, error_message: str, trace_event: dict}
```

### 9.3 AutoRevisor（自动修订器 — 质量闭环）

文件位置：`novelforge/orchestrator/auto_revisor.py`

**AutoRevisorConfig（自动修订配置）**：
```python
max_rounds: int = 5                     # 最大迭代轮数
pass_threshold: float = 8.5             # 通过阈值（满分 10）
quality_weights: dict = {               # 5 维度权重
    "logic_consistency": 0.25,          # 逻辑一致性
    "character_fidelity": 0.25,         # 角色保真度
    "foreshadowing_handling": 0.20,     # 伏笔处理
    "pacing": 0.15,                     # 叙事节奏
    "style_uniformity": 0.15,           # 风格统一
}
```

**run(chapter_index: int) → AutoRevisionReport 完整流程**：
```
1. _initial_draft(chapter_index)
   - 如果 chapter.content 已有内容 → 复用
   - 否则 WriterAgent.write_chapter() 写初稿
   - 返回 current_content: str

2. for round_num in 1..max_rounds:
   a. 检查 stop_requested（用户请求中止）→ 设置 result.stopped = True, break
   b. CriticAgent.review_quality_scorecard(current_content, outline, story, extra_context)
      → 返回 QualityReviewReport，计算 total_score = weighted_total(quality_weights)
   c. TraceRecorder.record() 记录本轮审查（旧分 → 新分，耗时，成功/失败）
   d. 如果 total_score >= pass_threshold（8.5）:
      - result.passed = True
      - result.final_score = total_score
      - result.final_content = current_content
      - break（通过，结束循环）
   e. EditorAgent.revise_from_quality_report(current_content, review, style_guide)
      → 返回 revised: str（修订后正文）
   f. 记录本轮修订（AutoRevisionRoundReport: 轮号, 评分卡, 修订后内容, 总分, 修改摘要）
   g. current_content = revised（进入下一轮）
   h. previous_score = total_score（记录旧分供下一轮对比）

3. 循环结束未通过（result.passed == False 且未中止）:
   - 执行最终审查 final_review
   - result.final_score = final_review.total_score()
   - result.final_content = current_content
   - result.residual_issues = final_review.issues（残存问题列表）

4. 返回 result（AutoRevisionReport: chapter_index, final_content, rounds, final_score, passed, residual_issues, trace_events）
```

**_summarize_revision(before, after, review) → str**（修订摘要生成）：
```
如果 issue_count > 0:
  return "针对 {N} 个问题修订，涉及：{维度列表}；字数变化 {+/-N}"
否则:
  return "按评分卡进行整体润色；字数变化 {+/-N}"
```

### 9.4 EventBus（事件总线 — 发布/订阅 Pub-Sub）

文件位置：`novelforge/orchestrator/bus.py`（仅 22 行）

```python
class EventBus:
    def subscribe(self, event_name: str, handler: Callable) → None
        # 注册事件处理器（handler 函数），同名事件可以有多个订阅者

    def emit(self, event_name: str, payload: dict = {}) → None
        # 同步通知所有订阅者，直接调用 handler(payload)
        # 不做异步队列，因为当前场景订阅者少且处理快
```

**主要事件（15 种）**：

| 事件名（event_name） | 触发时机 | payload（载荷）关键字段 |
|---|---|---|
| `story_started` | 创建新故事 | `story_id` |
| `outline_generated` | 大纲生成完成 | `story_id`, `chapters` |
| `beats_generated` | 节拍生成完成 | `story_id`, `chapter` |
| `chapter_written` | 章节写完 | `story_id`, `chapter` |
| `chapter_reviewed` | 章节审查完成 | `story_id`, `chapter` |
| `chapter_revised` | 章节修订完成 | `story_id`, `chapter` |
| `chapter_finalized` | 章节完成 | `story_id`, `chapter` |
| `chapter_continuity_audited` | 连续性审计完成 | `story_id`, `chapter`, `risk_score`, `passed` |
| `chapter_updated` | 内容更新 | `story_id`, `chapter` |
| `auto_revision_started` | 自动修订开始 | `story_id`, `chapter` |
| `auto_revision_finished` | 自动修订结束 | `story_id`, `chapter`, `passed`, `final_score` |
| `batch_write_finished` | 批量写作完成 | `story_id`, `start`, `end`, `completed`, `failed` |
| `agentic_run_finished` | 自主运行完成 | `story_id`, `run_id`, `status`, `completed_tasks`, `failed_tasks` |
| `director_run_finished` | Director 运行完成 | `story_id`, `run_id`, `status`, `steps` |

WebSocket 通过订阅这些事件实现实时进度推送。

### 9.5 TraceRecorder（追踪记录器）与错误分类

文件位置：`novelforge/orchestrator/trace.py`

**错误分类（6 类，classify_exception() 根据异常消息关键词自动匹配）**：

```python
ERROR_PROVIDER_CALL_FAILED   = "provider_call_failed"    # LLM 调用失败（不可恢复）
ERROR_TOOL_ARG_INVALID       = "tool_arg_invalid"        # 工具参数非法（可恢复）
ERROR_TOOL_EXECUTION_FAILED  = "tool_execution_failed"   # 工具执行失败（可恢复）
ERROR_PRECONDITION_MISSING   = "precondition_missing"    # 前置条件缺失（可恢复）
ERROR_QUALITY_GATE_FAILED    = "quality_gate_failed"     # 质量门控未通过（可恢复）
ERROR_MEMORY_RECALL_FAILED   = "memory_recall_failed"    # 记忆召回失败（可恢复）
ERROR_UNKNOWN                = "unknown_error"           # 未知错误（可恢复）
```

**is_recoverable(error_type: str) → bool** — 只有 `provider_call_failed` 返回 False（因为 DeepSeekClient 内部已重试 3 次）。

**TraceRecorder**：
```python
class TraceRecorder:
    def __init__(self, run_id, story_id, chapter_index) → list[AgentTraceEvent]（事件列表）
    def record(**kwargs) → AgentTraceEvent  # 追加事件

class trace_timer:                              # 上下文管理器
    def __enter__() → self                     # perf_counter() 开始计时
    def __exit__() → duration_ms = (now-start) × 1000  # 毫秒
```

**TraceExporter**（`trace_exporter.py`）支持两种导出格式：
- **JSON**：完整的 `AgentTraceRun.model_dump()`（含所有 steps 和 events）
- **Markdown**：人类可读报告（每步一个 h3 section，显示 tool/args/success/memory_hits/review_score/duration/error/observation）

---

## 10. 配置系统

### 10.1 配置来源与优先级

```
config.yaml 文件（默认值）
    ↓ .env 文件加载
DEEPSEEK_API_KEY 等环境变量（python-dotenv 加载）
    ↓
NOVELFORGE_* 环境变量（最高优先级）
    ↓
深度合并（_deep_merge）→ AppConfig（Pydantic 模型）
```

### 10.2 配置结构

```python
class AppConfig(BaseModel):
    llm: LLMConfig                     # LLM 相关配置
    memory: MemoryConfig               # 存储路径配置
    story: StoryConfig                 # 写作参数配置
    logging: LoggingConfig             # 日志配置
    auto_revisor: AutoRevisorConfig    # 自动修订参数

class LLMConfig(BaseModel):
    provider: str = "mock"             # 提供商: "deepseek" 或 "mock"
    model: str = "deepseek-chat"       # 模型名
    temperature: float = 0.8           # 温度（越大越有创意，越小越稳定）
    max_tokens: int = 4096             # 最大生成 token 数
    api_key: str = ""                  # API 密钥（优先读 DEEPSEEK_API_KEY 环境变量）
    base_url: str = "https://api.deepseek.com"  # API 地址
    timeout: float = 60.0              # API 超时（秒）
    max_retries: int = 3               # 最大重试次数（指数退避 Exponential Backoff）
    retry_backoff_seconds: float = 1.0 # 基础退避秒数（×2^(attempt-1)）

class MemoryConfig(BaseModel):
    vector_store: str = "chroma"       # 向量库类型
    graph_store: str = "networkx"      # 图库类型
    text_store: str = "sqlite_fts"     # 全文检索类型
    persist_directory: str             # ChromaDB 持久化目录
    graph_directory: str               # NetworkX 数据目录
    sqlite_path: str                   # SQLite 数据库路径

class StoryConfig(BaseModel):
    default_chapters: int = 10         # 默认章节数
    max_context_tokens: int = 6000     # 上下文窗口 token 数（约 24000 中文字符）
    history_limit: int = 20            # 历史记录限制
    auto_polish_drafts: bool = True    # 每章写完自动润色
    prose_target_words: int = 1800     # 润色目标字数

class AutoRevisorConfig(BaseModel):
    max_rounds: int = 5                # 最大修订轮数
    pass_threshold: float = 8.5        # 通过阈值
    quality_weights: dict[str, float]  # 5 维度权重
```

### 10.3 环境变量覆盖

```yaml
# .env 或系统环境变量示例
DEEPSEEK_API_KEY=sk-xxx               # 对应 llm.api_key
NOVELFORGE_LLM_PROVIDER=deepseek      # 对应 llm.provider
NOVELFORGE_LLM_MODEL=deepseek-chat    # 对应 llm.model
NOVELFORGE_LLM_TEMPERATURE=0.9        # 对应 llm.temperature
NOVELFORGE_CHROMA_DIR=./data/chroma   # 对应 memory.persist_directory
NOVELFORGE_LOG_LEVEL=DEBUG            # 对应 logging.level
```

---

## 11. LLM 抽象层

### 11.1 接口定义（LLMClient ABC）

```python
class LLMClient(ABC):  # 抽象基类（Abstract Base Class）
    @abstractmethod
    def chat_completion(self, messages: list[dict[str, str]], **kwargs: Any) -> str:
        """接收对话消息列表 → 返回 LLM 生成的文本"""
```

所有 Agent 只依赖这个抽象接口，不直接依赖 DeepSeekClient 或 MockLLMClient —— 典型的依赖倒置原则（Dependency Inversion）。配置决定用哪个实现。

### 11.2 工厂函数（build_llm_client）

```python
def build_llm_client(config: LLMConfig) -> LLMClient:
    provider = config.provider.lower()
    if provider == "deepseek":
        return DeepSeekClient(api_key, model, base_url, timeout, max_retries, retry_backoff)
    if provider in {"mock", "local", "fake"}:
        return MockLLMClient()
    raise ValueError("Unsupported LLM provider")
```

### 11.3 DeepSeekClient（真实 LLM 客户端）

文件位置：`novelforge/llm/deepseek_client.py`

- 使用 OpenAI 兼容 SDK（`openai.OpenAI`），target URL 指向 DeepSeek API
- **指数退避重试（Exponential Backoff Retry）**：
  ```
  for attempt in 1..max_retries（3）:
      try: self.client.chat.completions.create(model, messages, timeout)
           → response.choices[0].message.content or ""
      except: time.sleep(retry_backoff × 2^(attempt-1))  # 1s → 2s → 4s
  → raise ProviderError(attempts=3)
  ```
- `provider_call_failed` 是唯一不可恢复的错误类型，因为重试已在客户端内部完成

### 11.4 MockLLMClient（模拟 LLM 客户端 — 零成本演示与测试）

文件位置：`novelforge/llm/mock_client.py`（267 行）

**不调任何 API，根据 prompt（提示词）中的 marker（标记）字符串做路由分发**：

| prompt 中出现的 marker 关键词 | 返回内容 |
|---|---|
| `director_decision` | 根据子关键词路由："伏笔" → list_foreshadowings JSON; "检查/审查" → review_chapter JSON; "改/修" → revise_chapter JSON; "继续/下一章" → 先 create_outline 再 auto_write_chapter JSON; 其它 → show_status JSON |
| `supervisor_plan` | 预设 5 步任务序列 JSON（ensure_outline → beats → write → audit → memory） |
| `continuity_audit` | 通过的审计报告 JSON（risk_score=2.0, passed=True, 无问题） |
| `memory_extract` | "主角"角色（personality="敏锐、在压力中成长"）+ 训练世界设定 JSON |
| `quality_scorecard_review` | 含"【修订稿】" → 8.8 分; 否则 → 6.4 分 JSON。**这个设计让 Mock 模式下的 AutoRevisor 能跑出真实的多次循环** |
| `ReviewReport` / `审查报告` | 空逻辑和人设问题，1 个节奏建议 JSON |
| `prose_polish` | 固定中文润色段落文本 |
| `润色` / `revise_chapter` | "【修订稿】\n" + 原文（模拟修订行为） |
| `generate_outline` | N 章模板大纲 JSON（动态章数） |
| `generate_beats` | 2 个模板节拍 JSON |
| 其他（兜底 catch-all） | 固定中文通用叙事段落 |

---

## 12. 接口层

### 12.1 CLI（命令行界面）

文件位置：`novelforge/cli.py`

基于 `cmd2` 框架，约 30 条命令：
`/new_story`（创建故事）, `/outline`（大纲）, `/beats`（节拍）, `/write`（写）, `/review`（审）, `/revise`（改）, `/auto-write`（自动写）, `/batch-write`（批量写）, `/foreshadowing`（伏笔）, `/pacing`（节奏）, `/state`（状态）, `/summary`（摘要）, `/dashboard`（仪表盘）, `/agent`（Agent）, `/export`（导出）, `/load`（加载）, `/save`（保存）等。

### 12.2 REST API

文件位置：`novelforge/api/`

FastAPI 路由文件：
- `stories.py`（故事路由）：CRUD（创建 Create / 读取 Read / 更新 Update / 删除 Delete）
- `chapters.py`（章节路由）：大纲生成、节拍生成、写章、审查、修订、自动修订、导出
- `agents.py`（Agent 路由）：Director 运行、Supervisor 规划、批量写作、导出追踪

### 12.3 Web UI（网页界面）

- **Workspace**（写作工作区 `/workspace/`）：创建故事、撰写章节、审查修订、导出
- **Dashboard**（故事全景仪表盘 `/dashboard/`）：伏笔表、角色时间线、节奏走势图、因果事件力导向图（Force-Directed Graph）
- **Agent Trace**（Agent 追踪查看器 `/agent-trace/`）：每一步的 tool/args/success/duration/error 可视化

所有 Web 界面使用 Jinja2 模板引擎渲染。

### 12.4 WebSocket（实时推送）

端点（Endpoint）：`ws://host:8000/ws/{story_id}`

通过订阅 EventBus 的事件实现实时进度推送。主要推送场景：批量写作进度（每章开始/完成）、自动修订进度（每轮审查/修订）、Director 执行进度（每一步决策和执行）。

---

## 13. 完整数据流追踪

### 13.1 write_chapter(3) 的完整数据流

```
write_chapter(3) 被调用
│
├── _require_story()                                  → Story | raise WorkflowError
├── story.get_outline(3)                              → ChapterOutline | raise KeyError
├── story.chapters.get(3)                             → Chapter | None
│
├── [如无节拍] generate_beats(3)
│   ├── ContextAssembler.assemble_writing_context(3, story) → str (≤24000 字符)
│   │   ├── 构造 query: outline.title + summary + conflict + pov_character（拼接）
│   │   ├── ChromaDB: query 4 个 collection × k=12 → 48 条原始 {document, metadata, score}
│   │   ├── MemoryRanker.rank_vector_hits() → 多维评分后的 top 12 RankedMemory（排序记忆对象）
│   │   ├── SQLite FTS: text_store.search(query, limit=5) → 5 条文本片段
│   │   ├── NetworkX: graph_store.get_ego_network(node_id, depth=1) → dict（关系子图）
│   │   ├── LongformManager.get_enhanced_context() → str（长篇增强上下文）
│   │   └── 所有结果按优先级分区（100/95/90/88/85/70/50/40）排序 → 拼接 → 截断
│   └── PlannerAgent.generate_beats(outline, context) → list[Beat]
│       └── LLM.chat_completion([system_prompt, user_prompt]) → _parse_model_list(raw, Beat)
│
├── WriterAgent.write_chapter(3, outline, beats, context, style_guide) → str（正文）
│   └── self._chat(system_prompt, user_prompt) → LLM.chat_completion([system, user]) → .strip()
│
├── [可选] EditorAgent.polish_prose(content, instructions) → str
│   └── if not auto_polish_drafts: 直接返回 content（不调 LLM）
│
├── chapter.update_content(content, status="draft", summary=outline.summary)
│   └── 旧版 → self.history.append(snapshot()); self.version += 1; self.content = new
│
├── _process_chapter_memory(story, chapter)
│   ├── _index_chapter() → SQLite FTS: index_document(doc_id, content)
│   │                    + ChromaDB plot_summaries: add([summary], [metadata], [doc_id])
│   ├── LongformManager.process_new_chapter(story, 3, content)
│   │   ├── MemoryExtractorAgent.extract_chapter_memory() → MemoryExtractionResult
│   │   │   → _apply_extraction() 合并到 Story.characters / Story.world_settings
│   │   ├── SummaryManager.generate_chapter_summary() → ChapterSummary
│   │   │   → story.chapter_summaries[3] = summary
│   │   ├── CausalityTracker.extract_events_from_chapter()
│   │   │   → 先删旧事件 → 提取新事件 → check_conflicts()（前因缺失/未来锚定/因果循环）
│   │   │   → add_event() 写入
│   │   ├── ForeshadowingTracker.analyze_new_chapter()
│   │   │   → LLM/规则检测新伏笔 → register() → _auto_fulfill() 自动回收旧伏笔
│   │   ├── CharacterStateTracker.extract_state_from_chapter()
│   │   │   → LLM/规则提取角色状态 → update_state() 写入 character_states
│   │   ├── PacingAnalyzer.analyze_chapter(content)
│   │   │   → 纯规则统计 4 维度 → 存入 pacing_history
│   │   └── MemoryEngineV2.process_chapter()
│   │       → _upsert_chapter_cards() → update_arc_summary() → update_story_bible() → _trim_cards()
│   ├── _index_extracted_memory() → ChromaDB characters/world + NetworkX 更新节点和边
│   ├── [如有 memory_cards] ChromaDB memory_cards: 批量写入卡片向量
│   └── _audit_processed_chapter() → ContinuityAuditorAgent.audit_chapter()
│       → story.continuity_reports[3] = report
│       → bus.emit("chapter_continuity_audited", {risk_score, passed})
│
├── story.touch()                                        → updated_at = utc_now()
├── repository.save(story)                               → JSON 文件持久化
├── bus.emit("chapter_written", {story_id, chapter: 3})  → WebSocket 推送
│
└── return chapter  → Chapter 对象（含 content/version/status/beats/history/memory）
```

### 13.2 Director Agent 执行 "写好第 3 章并检查质量"

```
1. Engine.run_director_agent("写好第 3 章并检查质量", max_steps=6)
│
├── Step 1: NovelDirectorAgent.decide(story, user_message, step=1, run, tools)
│   ├── 输入: story_state JSON（标题/前提/状态/章节/伏笔/前6步执行记录 last_observations）
│   │        + tools JSON Schema 列表（tool_registry.list_specs()）
│   │        + output_schema（AgentDecision 的字段规范）
│   ├── LLM 决策: selected_tool="auto_write_chapter", tool_args={chapter_index:3},
│   │             reasoning_summary="先通过自动修订写好第3章", should_continue=True
│   └── 返回: AgentDecision(selected_tool, tool_args, reasoning_summary, should_continue)
│
├── Step 1: ToolRegistry.execute("auto_write_chapter", {chapter_index:3})
│   ├── ChapterIndexArgs.model_validate({chapter_index:3}) → Pydantic 校验通过
│   ├── trace_timer 开始计时
│   ├── Engine.auto_write_chapter(3) → AutoRevisor(config).run(3)
│   │   └── 最多 5 轮 review+revise → AutoRevisionReport(passed=True, final_score=8.7)
│   └── 返回: {success: True, observation: "Auto-wrote ch3: score=8.70, passed=True",
│              trace_event: {action, duration_ms, success, ...}}
│
├── (should_continue=True) 继续 → Step 2: decide()
│   ├── 输入: 同上 + last_observations 已包含 step1 结果
│   ├── LLM 决策: selected_tool="audit_continuity", tool_args={chapter_index:3},
│   │             reasoning_summary="自动修订完成，需要做连续性审计", should_continue=False
│   └── 返回: AgentDecision
│
├── Step 2: ToolRegistry.execute("audit_continuity", {chapter_index:3})
│   ├── Engine.audit_chapter_continuity(3)
│   │   └── LongformManager.get_enhanced_context() → ContinuityAuditorAgent.audit_chapter()
│   │       → ContinuityAuditReport(risk_score=2.0, passed=True)
│   └── 返回: {success: True, observation: "Audited chapter 3: risk=2.0, passed=True."}
│
└── (should_continue=False) → run.status = "completed"
    → run.final_summary = "Audited chapter 3: risk=2.0, passed=True."
    → AgentTraceRun 生成完成
    → 可选: export_director_trace_json() / export_director_debug_report() 导出
```

---

## 14. 关键设计决策与取舍

| 决策（Design Decision） | 理由（Rationale) | 代价（Trade-off) |
|---|---|---|
| Multi-Agent（多智能体）而非单 Agent | 规划/写作/审查/修订需要不同思维模式，单 prompt 不可靠 | 增加模块数量和 LLM 调用次数 |
| Agent 间用 Pydantic 模型传数据而非自然语言 | 类型安全（Type Safety）、字段精确、JSON Schema 自动生成 | 增加模型定义工作量 |
| 每个 LLM 调用都有确定性规则 fallback（兜底） | 系统健壮性（Robustness）、Mock 模式可运行完整管线 | fallback 质量必然低于真实 LLM |
| 三层记忆存储（向量/全文/图）而非单一向量库 | 各自解决各自维度的问题，互补而非替代 | 维护三套存储代码 |
| 上下文全局字符串截断（暴力切片） | 简单、确定性强、对 LLM 友好 | 被截断的内容可能丢失关键细节 |
| 单文件全量 JSON 持久化 | 零配置、原子写入（Atomic Write）、Pydantic 一键序列化 | 50+ 章后文件体积增大（估计 1.5MB+） |
| 排序用规则公式而非 LLM | 可复现（Reproducible）、零延迟、零成本、可解释 | 无法感知语义细微差别 |
| 伏笔自动回收用关键词匹配 | 确定性、不增加 LLM 调用 | 复杂伏笔可能误判或漏判 |
| EventBus 同步通知（非异步队列） | 实现简单（22 行）、当前场景订阅者少且处理快 | 高并发下可能阻塞 |
| Director 最多 2 次恢复尝试 | 防止无限循环（Infinite Loop） | 复杂场景可能不够（如需要多步补偿） |
| 角色信息分散在多个存储位置（characters/states/memory_cards/ChromaDB/graph） | 各存储解决不同维度的问题 | 没有单一权威的"角色圣经"——可能产生不一致 |
| MemoryRanker 时间衰减公式（>100 章衰减为 0） | 优先保留近期信息 | 极长篇小说中（100+ 章）早期核心设定可能被遗忘 |

---

## 15. 目录结构与文件职责

```
BookAgent/
├── config.yaml                     # 默认配置（YAML 格式）
├── .env                            # API Key 等密钥（不提交版本控制）
├── pyproject.toml                  # 项目元数据（包名/版本/依赖）
├── requirements.txt                # pip 依赖列表
├── README.md                       # 项目说明文档
├── KNOWLEDGE_BASE.md               # 本文档 —— 完整知识库
│
├── novelforge/                     # 主包
│   ├── __init__.py                 # 版本号字符串
│   ├── __main__.py                 # python -m novelforge 入口（启动 CLI）
│   ├── cli.py                      # cmd2 命令行界面（~30 条命令, 453 行）
│   │
│   ├── core/                       # 核心模块
│   │   ├── config.py               # 配置加载: YAML + env → AppConfig 合并（112 行）
│   │   ├── models.py               # 全部 Pydantic 领域模型 40+ 个类（374 行）
│   │   └── exceptions.py           # 自定义异常: WorkflowError, PersistenceError, ConfigurationError
│   │
│   ├── agents/                     # Agent 智能体层
│   │   ├── base.py                 # BaseAgent 基类: _chat(), _extract_json(), _parse_model()（48 行）
│   │   ├── planner.py              # PlannerAgent: 大纲生成 + 节拍生成（57 行）
│   │   ├── writer.py               # WriterAgent: 正文写作（42 行）
│   │   ├── critic.py               # CriticAgent: 结构化审查 + 质量评分卡 + 记忆快照注入（140 行）
│   │   ├── editor.py               # EditorAgent: 修订 + 润色 + 质量卡修复（三种模式, 59 行）
│   │   ├── supervisor.py           # SupervisorAgent: LLM 任务规划 + 规则兜底 + 补充校验（300 行）
│   │   ├── director.py             # NovelDirectorAgent: LLM 工具编排 + 容错恢复（322 行）
│   │   ├── continuity_auditor.py   # ContinuityAuditorAgent: 连续性审计 + 规则化四项检测（135 行）
│   │   └── memory_extractor.py     # MemoryExtractorAgent: LLM/规则双重记忆提取（168 行）
│   │
│   ├── orchestrator/               # 编排层
│   │   ├── engine.py               # NovelForgeEngine 核心引擎: FSM + 全部操作 + 记忆管线（906 行）
│   │   ├── auto_revisor.py         # AutoRevisor: 迭代质量闭环（205 行）
│   │   ├── tool_registry.py        # ToolRegistry: 10 个工具的注册/校验/执行（231 行）
│   │   ├── tool_schemas.py         # 工具的 Pydantic 参数模型映射（39 行）
│   │   ├── trace.py                # TraceRecorder + 6 类错误分类 + trace_timer（95 行）
│   │   ├── trace_exporter.py       # JSON / Markdown 追踪导出（87 行）
│   │   ├── bus.py                  # EventBus: 发布/订阅同步通知（22 行）
│   │   └── job_registry.py         # 后台任务状态追踪
│   │
│   ├── llm/                        # LLM 抽象层
│   │   ├── base.py                 # LLMClient 抽象基类 ABC（12 行）
│   │   ├── factory.py              # build_llm_client() 工厂函数（25 行）
│   │   ├── mock_client.py          # MockLLMClient: marker 路由分发模拟（267 行）
│   │   └── deepseek_client.py      # DeepSeekClient: OpenAI SDK + 指数退避重试（52 行）
│   │
│   ├── context/                    # 上下文组装
│   │   └── assembler.py            # ContextAssembler: 三库协同 + 优先级分区 + 截断（107 行）
│   │
│   ├── memory/                     # 记忆存储后端
│   │   ├── interfaces.py           # IVectorStore/IGraphStore/IFTSStore 三个抽象基类（58 行）
│   │   ├── vector_store.py         # ChromaVectorStore 实现（4 个 collection）
│   │   ├── graph_store.py          # NetworkXGraphStore 实现（节点 + 边 + ego_network）
│   │   └── text_store.py           # SQLiteFTSStore 实现（FTS5 全文索引）
│   │
│   ├── longform/                   # 长篇一致性子系统
│   │   ├── manager.py              # LongformManager: 7 个子系统的统一门面（201 行）
│   │   ├── foreshadowing.py        # ForeshadowingTracker: 新建 + 自动回收 + 去重（114 行）
│   │   ├── causality.py            # CausalityTracker: 因果图 + DFS 环检测 + 冲突验证（147 行）
│   │   ├── pacing.py               # PacingAnalyzer: 纯规则 4 指标统计 + 趋势预警（53 行）
│   │   ├── character_state.py      # CharacterStateTracker: 情绪/位置/知识提取 + 跨章一致性检查（125 行）
│   │   ├── summaries.py            # SummaryManager: 场景→章→卷→弧 分层摘要 + 滚动上下文（101 行）
│   │   ├── memory_engine.py        # MemoryEngineV2: 确定性记忆卡片 + 圣经 + 弧线 + 修剪（331 行）
│   │   └── ranker.py               # MemoryRanker: 5 维规则评分排序（125 行）
│   │
│   ├── storage/                    # 持久化
│   │   ├── repository.py           # StoryRepository: JSON 读写删 + 报告格式化导出（123 行）
│   │   └── story_state/            # 运行时数据目录: JSON文件 + SQLite + ChromaDB + graph 文件
│   │
│   ├── api/                        # FastAPI Web 服务
│   │   ├── main.py                 # FastAPI 应用入口 + 静态文件挂载 + WebSocket 端点
│   │   ├── routes/                 # stories.py（故事 CRUD）, chapters.py（章节操作）, agents.py（Agent 操作）
│   │   ├── schemas.py              # 请求/响应 Pydantic Schemas
│   │   └── state.py                # Engine 单例管理（应用级全局唯一引擎实例）
│   │
│   ├── dashboard/                  # 故事全景仪表盘
│   │   ├── api.py                  # FastAPI Router（路由）
│   │   ├── data_provider.py        # DashboardDataProvider（仪表盘数据提供者）
│   │   ├── templates/              # Jinja2 HTML 模板
│   │   └── static/                 # CSS / JavaScript 静态资源
│   │
│   ├── workspace/                  # Web 写作工作区
│   │   ├── api.py                  # FastAPI Router
│   │   ├── templates/              # Jinja2 HTML 模板
│   │   └── static/                 # CSS / JS 静态资源
│   │
│   └── agent_trace/                # Agent 执行追踪查看器
│       ├── api.py                  # FastAPI Router
│       └── templates/              # HTML 模板
│
├── evals/                          # 回归评测
│   ├── __init__.py
│   ├── cases.py                    # 4 个评测场景定义（人设矛盾/伏笔逾期/因果冲突/节奏异常）
│   └── run_eval.py                 # 评测运行脚本 + 报告生成
│
├── tests/                          # 单元测试（pytest, 20+ 测试文件）
└── docs/                           # 项目文档
    ├── MEMORY_ENGINE_V2.md         # 记忆引擎 V2 设计文档
    └── PROJECT_MAP.md              # 项目地图
```

---

## 16. 快速上手

### 16.1 安装

```bash
pip install -r requirements.txt
```

### 16.2 Mock 模式运行（不需要 API Key，零成本）

```yaml
# config.yaml
llm:
  provider: mock          # 使用 MockLLMClient 确定性模拟
```

```bash
python -m novelforge      # 启动 CLI
```

进入 CLI 后：
```
/new_story "一个年轻门将在电竞天赋和足球梦想之间挣扎"     # 创建新故事
/outline 10              # 生成 10 章大纲
/auto-write 1            # 自动写第 1 章（Mock 模式下跑完整写+审+改循环）
/review 1                # 审查第 1 章
/export                  # 导出 Markdown 到 novelforge/storage/story_state/
```

### 16.3 DeepSeek 模式（需要 API Key）

```bash
# .env 文件中设置
DEEPSEEK_API_KEY=sk-your-key-here
```

```yaml
# config.yaml
llm:
  provider: deepseek      # 使用 DeepSeekClient 真实 API
  model: deepseek-chat
```

### 16.4 Web 模式

```bash
uvicorn novelforge.api.main:app --reload --host 0.0.0.0 --port 8000
```

浏览器打开：
- 写作工作区：`http://localhost:8000/workspace/`
- 故事仪表盘：`http://localhost:8000/dashboard/`
- API 文档（Swagger）：`http://localhost:8000/docs`

### 16.5 运行测试

```bash
pytest tests/
```

### 16.6 运行回归评测

```bash
python -m evals.run_eval
```
输出报告：`evals/report.md`

---

## 17. 术语表

| 术语（中文） | 英文（代码中的标识符） | 含义 |
|---|---|---|
| 大纲 | `ChapterOutline` | 每章的标题（title）、摘要（summary）、核心冲突（conflict）、视角角色（pov_character） |
| 节拍 | `Beat` | 场景级写作指导：场景描述（description）→ 目标（goal）→ 结果（outcome） |
| 审查报告 | `ReviewReport` | 结构化的逻辑（logic_issues）/人物（character_issues）/节奏（pacing_issues）问题列表 + 建议（suggestions）+ 判断（verdict） |
| 质量评分卡 | `QualityReviewReport` | 5 维度（logic_consistency/character_fidelity/foreshadowing_handling/pacing/style_uniformity）1-10 评分 + 问题列表（RevisionIssue） |
| 自动修订 | Auto Revision | 写→审→改→再审的迭代质量闭环，由 `AutoRevisor` 组件驱动 |
| 故事圣经 | `StoryBible` | 故事核心前提（core_premise）、当前走向（current_direction）、活跃剧情线（active_threads）、角色名册（character_roster）、连续性约束（continuity_constraints）的汇总 |
| 记忆卡片 | `MemoryCard` | 带类型（type）和重要性评分（importance 1-10）的结构化记忆单元 |
| 伏笔 | `Foreshadowing` | 前文暗示的关键线索，有创建章（created_chapter）、目标回收章（target_chapter）和状态（status: pending/fulfilled/abandoned） |
| 因果事件 | `CausalEvent` | 事件的前因后果关系，构成有向图。前因（causes）和后置效果（effects）通过事件 ID 链接 |
| 角色状态 | `CharacterState` | 某章结束时角色的情绪（emotional_state）/位置（location）/获得的知识（knowledge_gained）/关系变化（relationship_changes）快照 |
| 上下文组装 | Context Assembly | 从三库（向量/全文/图）检索并组装写入 LLM prompt 的上下文字符串。由 `ContextAssembler` 负责 |
| 排序器 | `MemoryRanker` | 多维评分规则（向量相似度 ×10 + 类型权重 + 时间衰减 + query 重叠 + 实体匹配）对检索结果重排序 |
| 导演 | `NovelDirectorAgent` | 根据用户自然语言指令和故事状态，自主决策选择工具执行的编排 Agent |
| 调度 | `SupervisorAgent` | 将写作目标拆分为多步任务序列（AgentTask）的规划 Agent |
| 工具注册表 | `ToolRegistry` | 将引擎能力封装为 10 个可调用工具（ToolSpec），提供注册、校验、执行和追踪的统一机制 |
| 连续性审计 | Continuity Audit | 检查长篇一致性风险的自动化过程，由 `ContinuityAuditorAgent` 执行 |
| 长篇管理器 | `LongformManager` | 7 个长篇子系统（伏笔/因果/节奏/角色状态/摘要/记忆引擎/记忆提取）的统一门面（Facade），每章写完后触发 |
| 事件总线 | `EventBus` | 发布/订阅模式（Pub-Sub）的同步消息通知，驱动 WebSocket 实时推送 |
| 追踪记录器 | `TraceRecorder` | 记录每一步 Agent 操作的输入（input_summary）、输出（output_summary）、耗时（duration_ms）、成功/失败（success）、错误类型（error_type） |
| Mock 模式 | Mock Mode | 使用 `MockLLMClient` 确定性模拟器的零 API 成本运行模式 |
| 兜底 | Fallback | 每个 LLM 调用失败时的确定性备选逻辑，保证系统永远能运行 |
| 上下文窗口 | Context Window | LLM 能一次处理的最大 token 数，本项目中通过 `max_context_tokens`（6000）配置 |
| 引擎 | `NovelForgeEngine` | 整个系统的核心协调器，管理 FSM（有限状态机）、所有操作入口和 Agent 调度 |
| 仓储 | `StoryRepository` | 故事的 JSON 文件持久化层，提供 save/load/exists/delete/list_records 操作 |
| 事件 | `AgentTraceEvent` | 每次 Agent 操作的结构化记录：run_id, story_id, chapter_index, stage, action, selected_tool, tool_args, success, error_type, duration_ms |
| 抽象基类 | ABC (Abstract Base Class) | `LLMClient`、`IVectorStore`、`IGraphStore`、`IFTSStore`——定义接口契约，具体实现通过依赖注入替换 |
| 依赖注入 | Dependency Injection | 所有 Agent 的 `__init__` 接收 `LLMClient` 参数，而非硬编码实现 |
| 指数退避 | Exponential Backoff | DeepSeekClient 的重试策略：第 1 次重试等 1s、第 2 次等 2s、第 3 次等 4s |
| 环检测 | Cycle Detection | CausalityTracker 的 `_has_cycle()` 方法使用 DFS 三色标记法（visiting/visited）检测因果图是否形成循环 |
| 力导向图 | Force-Directed Graph | Dashboard 中因果事件的可视化布局算法 |

---

> 本文档覆盖了 NovelForge 项目的完整架构、所有组件、数据模型、API 设计和核心代码逻辑。
> 可以此为基础向其他 AI 或新开发者解释项目，无需额外查阅源码。
