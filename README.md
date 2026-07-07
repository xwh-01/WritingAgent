# NovelForge

## Read This Repo First

If you just want to understand the project quickly, start with `docs/PROJECT_MAP.md`.
It explains the reading order, directory responsibilities, core workflow, and interview talking points.

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
3. Generate chapter beats: `POST /chapters/1/beats?story_id={story_id}`
4. Write chapter: `POST /chapters/1/write?story_id={story_id}`
5. Run automatic review: `POST /chapters/1/review?story_id={story_id}`
6. Run automatic repair loop: `POST /chapters/1/auto-write?story_id={story_id}`
7. Update long-form memory: automatically happens after chapter write/revision, or through the Director `update_memory` tool
8. Run Director Agent: `POST /stories/{story_id}/agent/run`
9. View trace JSON: `GET /stories/{story_id}/agent/runs/{run_id}/trace.json`
10. View debug report: `GET /stories/{story_id}/agent/runs/{run_id}/debug.md`
11. Run evals: `python -m evals.run_eval`

The debug report explains each stage/action/tool, observations, memory hits, review score changes, and structured errors.

NovelForge 是一个面向长篇小说创作的半自动 Agent 引擎，支持多智能体协作、分层记忆、工作流编排、版本控制、CLI 和 REST API。

当前版本提供一个可运行的 MVP：即使没有 DeepSeek API key，也能通过 `mock` LLM 完整走通“规划 -> 细纲 -> 写作 -> 审查 -> 修改”的核心流程。

新增长篇增强子系统：

- 伏笔管理器：追踪 pending / fulfilled / abandoned 状态和计划回收章节
- 因果事件图：记录重大事件的前因后果，检查未来前因、因果循环等问题
- 分层滚动记忆：生成场景摘要、章摘要、卷摘要，并在写作上下文中注入最近摘要
- 节奏分析器：估算冲突强度、对话占比、描写密度、情节推进量
- 人物状态机：跟踪角色每章后的情绪、位置、知识变化和关系变化

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
POST /stories/{story_id}/outline
POST /stories/{story_id}/batch-write
GET /chapters/{chapter_index}/?story_id=<story_id>
POST /chapters/{chapter_index}/beats?story_id=<story_id>
POST /chapters/{chapter_index}/write?story_id=<story_id>
POST /chapters/{chapter_index}/review?story_id=<story_id>
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
WebSocket /ws/{story_id}
GET /dashboard/
GET /dashboard/data/{story_id}
GET /dashboard/stories
GET /workspace/
```

## Director Agent and Agent Trace

NovelForge now exposes two different agent entry points:

- `/agent <natural language task>` is the natural-language Director Agent in the CLI. It reads the current story state, asks the LLM to choose the next tool, executes that tool, records an `AgentTraceRun`, and prints each tool step.
- `/agentic-run` is the existing batch/task orchestration flow. It is best for planned multi-chapter writing runs such as outlining, drafting, revising, auditing, and memory updates across a chapter range.
- Agent Trace shows the Director Agent's step-by-step tool choices and execution results: `selected_tool`, `reasoning_summary`, `tool_args`, `observation`, `success/error`, and `final_summary`.

Useful endpoints:

```text
POST /stories/{story_id}/agent/run
GET /stories/{story_id}/agent/runs
GET /stories/{story_id}/agent/runs/{run_id}
GET /stories/{story_id}/agent/runs/{run_id}/trace.json
GET /stories/{story_id}/agent/runs/{run_id}/debug.md
GET /agent-trace/
```

## Web 创作工作台

工作台是 NovelForge 的主界面，打开后可以完成：

- 创建和加载故事
- 生成章节大纲和场景细纲
- 写作章节正文
- 批量生成多章草稿或自动修订稿
- 手动编辑并保存章节
- 触发审查和自动修订
- 查看质量报告、伏笔/事件/摘要数量
- 跳转故事全景仪表盘

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
NOVELFORGE_SQLITE_PATH=./novelforge/storage/story_state/fts.sqlite3
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
