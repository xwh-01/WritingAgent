# NovelForge Project Map

这份文档只负责帮你快速读懂仓库，不描述夸张能力，也不替代 README。

## 先看这 6 个文件

1. `README.md`
   - 项目定位、演示路径、运行方式。

2. `novelforge/orchestrator/engine.py`
   - 核心工作流入口。
   - 串起新建故事、大纲、细纲、写作、审查、修订、导出、Director Agent。

3. `novelforge/agents/`
   - 各类 Agent 实现。
   - 重点看 `planner.py`、`writer.py`、`critic.py`、`editor.py`、`director.py`。

4. `novelforge/core/models.py`
   - 主要数据模型。
   - 故事、章节、大纲、审查报告、自动修订报告、Agent Trace 都在这里。

5. `novelforge/orchestrator/tool_registry.py`
   - Director Agent 能调用哪些工具。
   - 工具参数校验、结构化错误、Trace 记录都从这里进入。

6. `tests/test_agent_engineering_p0.py`
   - 最适合面试前快速确认工程亮点的测试。
   - 覆盖 Trace、工具参数校验、失败恢复、自动修订 Trace、Eval 报告。

## 目录职责

```text
novelforge/
  agents/          Agent 实现：规划、写作、审查、修订、Director、记忆抽取、连续性审查
  api/             FastAPI 路由和请求响应模型
  cli.py           交互式命令行入口
  context/         写作上下文组装，负责召回记忆和长篇上下文
  core/            配置、异常、核心 Pydantic 模型
  dashboard/       故事全景仪表盘
  longform/        长篇一致性能力：伏笔、因果、节奏、角色状态、摘要
  llm/             LLM Provider 抽象和 mock/deepseek 实现
  memory/          向量、全文检索、图谱存储抽象与实现
  orchestrator/    工作流编排、自动修订、工具注册、Trace
  storage/         本地运行时数据目录
  workspace/       Web 创作工作台

tests/             自动化测试
evals/             长篇一致性评测用例和报告生成器
docs/              面试/阅读辅助文档
```

## 核心流程

```text
输入故事设定
  -> PlannerAgent 生成大纲
  -> PlannerAgent 生成章节细纲
  -> ContextAssembler 组装上下文
  -> WriterAgent 写初稿
  -> CriticAgent 审查
  -> EditorAgent 修订
  -> LongformManager 更新记忆和一致性数据
  -> Trace / Report 记录过程
```

写作上下文具有章节时间边界：旧章节版本会在重新索引时被替换，角色状态、伏笔、因果事件、全文和向量召回不会读取当前章之后的数据。

`longform/fact_ledger.py` 是人物硬事实入口。自动提取事实带来源和生效区间；用户确认项具有更高优先级，并直接进入 Writer 和连续性审计使用的增强上下文。

Workspace 的“章节合同”和“人物事实账本”是当前主要控制面；普通创作不需要直接编辑 JSON，高级 JSON 只保留给知识边界和调试场景。

合同验收由 `validation/contract.py` 统一执行：规则结果与 LLM 语义结果一致且置信度足够时才通过；冲突或低置信度结果进入人工复核，并携带证据段落进入 Workspace 和自动修订报告。

Director Agent 是另一条入口：

```text
自然语言任务
  -> NovelDirectorAgent 决策工具
  -> ToolRegistry 校验参数并执行工具
  -> Trace 记录每一步
  -> 可恢复错误时反思并重试/补前置步骤
```

## 面试讲法

可以按这条线讲：

1. **不是通用 Agent 平台**
   - 这是一个垂直写作工作流，边界清楚，适合展示工程能力。

2. **Agent 有明确分工**
   - Planner 负责结构，Writer 负责生成，Critic 负责质量检查，Editor 负责修订，Director 负责自然语言调度。

3. **可观测性**
   - Director Trace 和 Auto-Revisor Trace 记录工具选择、参数、结果、错误类型、耗时、记忆命中等。

4. **失败可恢复**
   - 工具参数错误、缺少大纲/细纲、质量门槛失败等场景不会直接崩溃，而是进入结构化错误和恢复分支。

5. **长篇写作不是单次生成**
   - 项目维护伏笔、因果、角色状态、章节摘要、节奏指标，解决长篇内容容易忘前文的问题。

6. **测试不依赖真实 LLM**
   - 默认 mock provider 可跑完整流程，`pytest` 可以稳定验证核心能力。

## 常用命令

```bash
python -m novelforge
```

```bash
uvicorn novelforge.api.main:app --reload
```

```bash
pytest
```

```bash
python -m evals.run_eval
```

## 当前需要注意

- `novelforge/storage/` 是运行时输出目录，里面的 docx、Markdown、数据库、索引数据不应该作为源码阅读重点。
- `evals/report.md` 是评测报告，可以保留作为展示材料；`evals/report.json` 是机器输出，已被 `.gitignore` 忽略。
- `workspace/` 前端改动较大，适合单独验收 UI，不建议和后端 Trace 逻辑混在一起讲。
