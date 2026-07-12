# NovelForge

## Read This Repo First

If you just want to understand the project quickly, start with `docs/PROJECT_MAP.md`.
It explains the reading order, directory responsibilities, core workflow, and interview talking points.

For data ownership, write boundaries, derived-index rebuilding, and legacy migration, read `docs/STORAGE_MODEL.md`.

The persisted Story model is grouped as `content`, `memory`, `quality`, and `agent_runs`; the API returns this explicit domain structure.

## Project Positioning

NovelForge is a vertical Agentic Workflow / Agent Engineering project for long-form fiction writing. It focuses on one bounded domain: planning, drafting, reviewing, revising, and remembering a serialized novel.

It is intentionally **not**:

- a general-purpose multi-agent platform
- an MCP tool ecosystem
- a production-grade observability platform
- a complete version-control system
- a generic Agent Studio

The engineering goal is to show a credible bounded-agent system: typed tools, recoverable Director decisions, long-form memory, review/revision loops, unified trace, and regression evals for a writing workflow.

## Interview Golden Demo

Use the mock LLM path for a deterministic demo:

```bash
uvicorn novelforge.api.main:app --reload
```

Golden path:

1. Create a story: `POST /stories/`
2. Generate outline: `POST /stories/{story_id}/outline`
3. Generate and confirm the chapter contract: `GET/PUT /chapters/1/contract?story_id={story_id}`
4. Generate chapter beats: `POST /chapters/1/beats?story_id={story_id}`
5. Write chapter: `POST /chapters/1/write?story_id={story_id}`
6. Run automatic review: `POST /chapters/1/review?story_id={story_id}`
7. Run automatic repair loop: `POST /chapters/1/auto-write?story_id={story_id}`
8. Update long-form memory: automatically happens after chapter write/revision, or through the Director `update_memory` tool
9. Run Director Agent: `POST /stories/{story_id}/agent/run`
10. View trace JSON: `GET /stories/{story_id}/agent/runs/{run_id}/trace.json`
11. View debug report: `GET /stories/{story_id}/agent/runs/{run_id}/debug.md`
12. Run evals: `python -m evals.run_eval`

When Director revises an existing chapter, it now creates a reviewed revision proposal instead of overwriting the chapter. The run pauses at `awaiting_approval`; accept, reject, or request another revision from the Workspace before the official chapter and long-form memory are updated.

The debug report explains each stage/action/tool, observations, memory hits, review score changes, and structured errors.

NovelForge 是一个面向长篇小说创作的半自动 Agent 引擎，支持多智能体协作、分层记忆、工作流编排、版本控制、CLI 和 REST API。

当前版本提供一个可运行的 MVP：即使没有 DeepSeek API key，也能通过 `mock` LLM 完整走通“规划 -> 细纲 -> 写作 -> 审查 -> 修改”的核心流程。

新增长篇增强子系统：

- 伏笔管理器：追踪 pending / fulfilled / abandoned 状态和计划回收章节
- 因果事件图：记录重大事件的前因后果，检查未来前因、因果循环等问题
- 分层滚动记忆：生成场景摘要、章摘要、卷摘要，并在写作上下文中注入最近摘要
- 节奏分析器：估算冲突强度、对话占比、描写密度、情节推进量
- 人物状态机：跟踪角色每章后的情绪、位置、知识变化和关系变化

记忆正确性规则：

- 同一章节重新写作或修订时，全文和章节摘要索引只保留当前有效版本
- 为第 N 章组装上下文时，只允许召回第 N 章及之前的数据，未来章节不会进入提示词
- 角色状态、伏笔、因果事件和记忆卡使用相同的章节时间边界
- SQLite 全文索引使用线程锁保护后台任务与同步请求的并发读写

人物事实账本：

- 从人物状态生成带生效章节区间的 location、emotional_state、knowledge 和 relationship 事实
- 用户可以通过 `GET/POST /stories/{story_id}/facts` 查看或确认事实
- 用户确认事实优先于自动提取结果，但只在设定的章节区间内生效
- Workspace 会展示当前章有效事实，并允许新增人工纠正项

Workspace 控制界面：

- 章节合同使用结构化表单编辑 POV、时间地点、必需/禁止事件、人物目标、故事线和结尾钩子
- 高级 JSON 折叠区只用于维护知识边界或调试完整合同
- 人物事实以表格展示，可通过人物、事实类型、有效章节范围和备注表单新增纠正项
- 用户确认事实可以直接从表格删除，自动提取事实保持只读

## 安装

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

## 快速开始

```bash
python -m novelforge
```

交互式命令示例：

```text
/new_story 一个失忆铸剑师发现自己曾经锻造过弑神之刃
/outline 3
/beats 1
/write 1
/review 1
/revise 1
/show 1
/foreshadowing list
/pacing check
/summary show
/dashboard
/auto-write 1
/batch-write 1 5
/report 1
/export markdown
```

## 使用说明

第一次使用建议走 Web 工作台，不需要先理解 Director、Agent Trace、向量库或其他内部模块。

### 1. 选择模型

默认配置使用 `mock`，无需 API Key，适合确认安装和体验完整流程：

```yaml
llm:
  provider: mock
```

要使用 DeepSeek 生成真实内容，复制 `.env.example` 为 `.env`，至少修改：

```text
NOVELFORGE_LLM_PROVIDER=deepseek
DEEPSEEK_API_KEY=你的_API_Key
```

修改后需要重新启动服务。不要把包含真实 Key 的 `.env` 提交到 Git。

### 2. 启动工作台

```bash
uvicorn novelforge.api.main:app --reload
```

浏览器打开：

```text
http://127.0.0.1:8000/workspace/
```

如果端口被占用，可以改用：

```bash
uvicorn novelforge.api.main:app --reload --port 8001
```

对应访问 `http://127.0.0.1:8001/workspace/`。

### 3. 创建故事和大纲

1. 在左侧填写标题、故事前提和类型，点击“新建”。
2. 点击顶部“大纲”，输入计划章节数。
3. 在章节列表或章节大纲条中选择准备创作的章节。

故事前提应尽量包含主角、目标、主要阻力和核心悬念。例如：

```text
失忆铸剑师林默为了寻找妹妹进入封锁城，却发现自己曾锻造过导致城市毁灭的武器；
他必须在恢复记忆前判断妹妹和追捕者谁在说谎。
```

### 4. 确认章节合同

选择章节后，在右侧“章节合同”中检查：

- POV、时间和地点
- 必须发生的情节
- 禁止发生的情节
- 人物目标和需要推进的故事线
- 结尾钩子和文风要求

合同为空时，第一次点击“保存章节合同”会根据章节大纲生成默认合同。检查和修改表单后再次保存，再进入正文写作。

“高级 JSON / 知识边界”用于维护完整合同字段。普通使用不需要编辑 JSON；如果手动修改，必须保持合法 JSON 格式。

### 5. 生成细纲和正文

1. 点击右侧“细纲”，生成本章场景节拍。
2. 点击顶部“写作”，根据大纲、合同、细纲和历史记忆生成正文。
3. 在中间编辑器中人工修改正文。
4. 点击“保存”，保存当前版本并更新长篇记忆。

保存或修订章节时，系统会更新章节版本、摘要、人物状态、人物事实、伏笔、因果事件和检索索引。重新保存同一章时，召回索引只保留当前有效版本。

### 6. 审查章节

正文存在后点击“审查”。系统会同时执行：

- 普通逻辑、人设和节奏审查
- 章节合同规则检查
- LLM 合同语义检查
- 原文证据和段落定位

合同项可能出现三种状态：

| 状态 | 含义 | 建议操作 |
| --- | --- | --- |
| `passed` | 规则与语义判断一致，要求已满足 | 无需处理 |
| `failed` | 规则与语义判断一致，要求未满足 | 修改对应段落 |
| `review_required` | 两种判断冲突或语义置信度不足 | 阅读证据并人工判断 |

`review_required` 属于硬门槛，不会被较高的文笔或节奏分数抵消。

### 7. 修正人物事实

写作和保存章节后，“人物事实账本”会展示当前章有效的人物状态。自动提取事实保持只读；发现错误时，可以新增一条用户确认事实：

1. 选择人物和事实类型。
2. 填写正确的事实值。
3. 设置生效章节和可选的失效章节。
4. 填写纠正原因，点击“确认人物事实”。

用户确认事实在有效期内优先于自动提取结果。删除确认项后，系统恢复使用对应的自动事实。

### 8. 自动修订和报告

正文存在后点击“自修”，系统进入多轮流程：

```text
质量评分 + 合同验收 + 连续性检查
  -> 未通过时修订
  -> 再次审查
  -> 达到门槛或达到最大轮数
```

点击“报告”可以查看各轮分数、合同证据、连续性问题和残留问题。只有质量分达到阈值，并且合同硬约束与高严重度连续性检查均通过，章节才会标记为通过。

### 9. 导出和数据位置

点击顶部“导出”可以生成 DOCX。SQLite 是故事、章节、人物事实、Director 运行和候选稿的唯一事实源；向量、图谱和全文检索是可删除并重建的派生索引：

```text
novelforge/storage/novelforge.db          # 唯一事实源
novelforge/storage/artifacts/             # Trace、报告和导出物
novelforge/storage/indexes/fts.sqlite3    # 全文检索索引
novelforge/storage/chroma_data/           # 向量索引
novelforge/storage/graph_data/            # 关系图索引
```

不要手动编辑索引来修改故事内容；正文、人物事实和审批状态必须通过工作台或 API 更新。索引损坏时可从 `novelforge.db` 重建。

### 10. 推荐的单章操作顺序

```text
选择章节
  -> 检查并保存章节合同
  -> 生成细纲
  -> 生成正文
  -> 人工编辑并保存
  -> 审查合同和连续性
  -> 修正人物事实
  -> 自动或人工修订
  -> 查看报告
  -> 进入下一章
```

## REST API

```bash
uvicorn novelforge.api.main:app --reload
```

打开 API 文档：

```text
http://127.0.0.1:8000/docs
```

Web 创作工作台：

```text
http://127.0.0.1:8000/workspace/
http://127.0.0.1:8000/workspace/?story_id=<story_id>
```

故事全景仪表盘：

```text
http://127.0.0.1:8000/dashboard/
http://127.0.0.1:8000/dashboard/?story_id=<story_id>
```

主要端点：

```text
POST /stories/
GET /stories/{story_id}/
GET /stories/{story_id}/storage
POST /stories/{story_id}/outline
POST /stories/{story_id}/batch-write
GET /chapters/{chapter_index}/?story_id=<story_id>
POST /chapters/{chapter_index}/beats?story_id=<story_id>
GET /chapters/{chapter_index}/contract?story_id=<story_id>
PUT /chapters/{chapter_index}/contract?story_id=<story_id>
POST /chapters/{chapter_index}/write?story_id=<story_id>
POST /chapters/{chapter_index}/review?story_id=<story_id>
POST /chapters/{chapter_index}/validate-contract?story_id=<story_id>
PUT /chapters/{chapter_index}/revise?story_id=<story_id>
PUT /chapters/{chapter_index}/content?story_id=<story_id>
POST /chapters/{chapter_index}/auto-write?story_id=<story_id>
POST /chapters/{chapter_index}/auto-write?story_id=<story_id>&background=true
GET /chapters/auto/status?story_id=<story_id>
GET /chapters/auto/status?story_id=<story_id>&job_id=<job_id>
POST /chapters/auto/stop?story_id=<story_id>
POST /chapters/auto/stop?story_id=<story_id>&job_id=<job_id>
GET /chapters/{chapter_index}/report?story_id=<story_id>
GET /chapters/{chapter_index}/report.md?story_id=<story_id>
GET /stories/{story_id}/facts?chapter_index=<chapter_index>
POST /stories/{story_id}/facts
DELETE /stories/{story_id}/facts/{fact_id}
POST /stories/{story_id}/indexes/rebuild
WebSocket /ws/{story_id}
GET /dashboard/
GET /dashboard/data/{story_id}
GET /dashboard/stories
GET /workspace/
```

## Director Agent and Agent Trace

Director Agent 是目标驱动的自然语言任务入口：

- Director 会先生成带依赖关系和成功标准的完整计划，再逐项调用专业 Agent 工具。
- `TaskEvaluatorAgent` 会根据可观察证据验收每一步；工具返回成功不再自动等于任务完成。
- 验收失败时会在次数限制内重试或补充前置任务；步数耗尽会保存 `paused` 检查点，可继续同一次运行。
- 信息不足时进入 `needs_user_input`；用户回答后根据原目标、问题和答案重新规划。
- 修改正文只生成经过 Critic 验收的候选稿，进入 `awaiting_approval`；接受后才更新正文、版本历史和长篇记忆，并继续剩余计划。
- Director 支持跨章节角色弧线任务：先审计人物的情绪、地点、知识和关系轨迹，再仅为有证据的问题章节生成修订候选稿。
- `/agentic-run` / Supervisor 流程已经弃用，仅为兼容旧调用保留；新流程使用章节合同配合普通写作或 `batch-write`。
- Agent Trace 展示目标、成功标准、任务依赖、尝试次数、验收结果、工具观察、追问、检查点和审批状态。

相关端点：

```text
POST /stories/{story_id}/agent/run
GET /stories/{story_id}/agent/runs
GET /stories/{story_id}/agent/runs/{run_id}
POST /stories/{story_id}/agent/runs/{run_id}/resume
POST /stories/{story_id}/agent/runs/{run_id}/continue
GET /stories/{story_id}/agent/runs/{run_id}/trace.json
GET /stories/{story_id}/agent/runs/{run_id}/debug.md
GET /stories/{story_id}/revision-proposals/{proposal_id}
POST /stories/{story_id}/revision-proposals/{proposal_id}/accept
POST /stories/{story_id}/revision-proposals/{proposal_id}/reject
POST /stories/{story_id}/revision-proposals/{proposal_id}/revise
GET /agent-trace/
```

## Web 创作工作台

工作台是 NovelForge 的主要创作入口。推荐按下面的阶段推进，而不是直接运行 Agent 批量生成正文：

```text
故事设定
  -> 章节大纲
  -> 确认章节合同
  -> 生成场景细纲
  -> 写作正文
  -> 合同/连续性/质量验收
  -> 自动或人工修订
  -> 更新人物事实与长篇记忆
```

### 章节合同

章节合同是正文生成和验收共同使用的控制面。工作台提供结构化表单，可以设置：

- POV、时间和地点
- 必须发生与禁止发生的事件
- 人物目标和需要推进的故事线
- 章节结尾钩子
- 文风要求和补充备注

知识边界等完整字段仍可在折叠的高级 JSON 区域维护。若合同尚不存在，系统可以根据本章大纲生成默认合同；正式写作前建议先检查并保存合同。

### 人物事实账本

事实账本展示当前章节有效的人物硬事实，包括位置、情绪、知识、身份、生存状态、身体状态和物品等。每条事实都带有生效区间和来源：

- 自动提取事实来自已经处理的章节，在工作台中保持只读
- 用户确认事实具有更高优先级，可以设置生效章、失效章和备注
- 用户确认项可以删除，删除后恢复使用对应的自动提取事实

### 正文与验收

工作台还可以完成：

- 创建和加载故事
- 生成章节大纲、合同和场景细纲
- 生成、手动编辑并保存章节正文
- 执行合同硬约束、连续性和质量审查
- 运行多轮自动修订并查看残留问题
- 查看当前人物事实、伏笔、事件、摘要和质量报告

批量写作适合合同和事实已经稳定的章节范围。Director、Agent Trace 和故事全景仪表盘属于高级调度、调试和观察能力，不是完成单章创作的必要步骤。

合同验收采用两层判断：确定性规则负责稳定回归，LLM 负责识别同义表达、隐含完成和语义违约。每项检查会返回原文证据、段落位置和置信度；两层判断冲突或语义置信度低于阈值时，状态为 `review_required`，不会自动通过质量门。

启动服务：

```bash
uvicorn novelforge.api.main:app --reload
```

访问：

```text
http://127.0.0.1:8000/workspace/
```

## 故事全景仪表盘

启动 API：

```bash
uvicorn novelforge.api.main:app --reload
```

打开 `/dashboard/` 后可以选择本地故事状态文件。仪表盘包含：

- 伏笔追踪表：显示待回收、已回收、逾期伏笔
- 角色状态时间轴：展示角色情绪和位置变化
- 章节节奏图：展示冲突强度、对话密度和行动密度
- 事件因果链：以力导向图展示事件节点和因果边

CLI 也提供摘要：

```text
/dashboard
```

## 自主审查修复闭环

NovelForge 支持“写作 -> 多轮审查 -> 自动修订 -> 再审查 -> 生成报告”的闭环：

```text
/auto-write <chapter>
/auto-status
/auto-stop
/report <chapter>
/report <chapter> export
```

每轮都会生成质量评分卡：

- 逻辑一致性
- 人设忠实度
- 伏笔处理
- 叙事节奏
- 风格统一

最终报告会记录每轮评分、发现的问题、修改摘要、最终分数和残留问题。Dashboard 的“质量闭环趋势”也会显示自动审查每轮得分。

API 支持后台任务模式，适合长时间运行：

```text
POST /stories/<story_id>/batch-write
POST /chapters/1/auto-write?story_id=<story_id>&background=true
GET /chapters/auto/status?story_id=<story_id>&job_id=<job_id>
POST /chapters/auto/stop?story_id=<story_id>&job_id=<job_id>
```

CLI 支持一次性生成多章：

```text
/batch-write 1 10        # 批量写作并自动审查修订
/batch-write 1 10 draft  # 只生成草稿
```

自动修订报告可以导出为 Markdown，作为“漏洞发现与修复”的可展示产物：

```text
/report 1 export
GET /chapters/1/report.md?story_id=<story_id>
```

## 长篇一致性评测集

项目内置可复现 evals，用来证明 Agent 能发现长篇小说中的典型问题：

```bash
python -m evals.run_eval
```

当前覆盖：

- 人设矛盾：角色怕水却无过渡跳湖
- 伏笔逾期：计划回收章节已过但仍 pending
- 因果冲突：当前事件引用未来章节作为前因
- 节奏平淡：连续多章冲突强度过低

运行后会生成：

```text
evals/report.md
```

## 架构

```text
CLI / FastAPI
      |
NovelForgeEngine
      |
PlannerAgent -> WriterAgent -> CriticAgent -> EditorAgent
      |
ContextAssembler
      |
VectorStore / GraphStore / SQLiteFTS
      |
LLMClient: mock / deepseek
```

## 配置

默认配置在 `config.yaml`。环境变量可以覆盖关键项：

```text
NOVELFORGE_LLM_PROVIDER=mock
DEEPSEEK_API_KEY=
NOVELFORGE_CHROMA_DIR=./novelforge/storage/chroma_data
NOVELFORGE_GRAPH_DIR=./novelforge/storage/graph_data
NOVELFORGE_DATABASE_PATH=./novelforge/storage/novelforge.db
NOVELFORGE_ARTIFACT_DIR=./novelforge/storage/artifacts
NOVELFORGE_SQLITE_PATH=./novelforge/storage/indexes/fts.sqlite3
```

要使用 DeepSeek：

```text
NOVELFORGE_LLM_PROVIDER=deepseek
DEEPSEEK_API_KEY=your_key
```

## 开发说明

模块边界：

- `core/`: Pydantic 数据模型、配置、异常
- `llm/`: 大模型适配层
- `agents/`: Planner、Writer、Critic、Editor
- `memory/`: Chroma、NetworkX、SQLite FTS 抽象与实现
- `context/`: 写作上下文组装器
- `orchestrator/`: 有限状态机和事件总线
- `longform/`: 伏笔、因果、摘要、节奏、人物状态等长篇增强模块
- `dashboard/`: 故事全景仪表盘的数据提供层、FastAPI 路由和前端页面
- `workspace/`: Web 创作工作台页面、样式和前端交互
- `storage/`: 故事仓库和自动修订报告导出
- `evals/`: 长篇一致性评测用例、运行器和报告
- `api/`: FastAPI 路由
- `cli.py`: 交互式命令行

## 长篇命令

```text
/foreshadowing list
/foreshadowing add <created_chapter> "伏笔描述" [target_chapter]
/causality show [event_id]
/pacing check
/state <character_id_or_name>
/summary update
/summary show
/dashboard
/auto-write <chapter>
/batch-write <start> <end> [draft]
/auto-status
/auto-stop
/report <chapter> [export]
/stories
```

章节写作、修订和定稿时会自动调用长篇管理器，更新章节摘要、因果事件、伏笔、人物状态和节奏指标。后续章节写作时，`ContextAssembler` 会把上一章摘要、当前卷概览、未回收伏笔和角色当前状态注入上下文。

运行测试：

```bash
pytest
```
