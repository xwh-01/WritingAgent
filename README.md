# NovelForge

NovelForge 是一个受约束的多智能体长篇创作系统。Story Orchestrator 能够理解用户目标、拆解任务、选择专职 Agent 和工具、观察结果并有限重规划；确定性应用层负责质量门禁、版本控制和正式提交。

## 核心能力

- 大纲、章节契约与结构化场景规划；
- `StoryOrchestratorAgent` 自主规划、工具选择、任务验收与失败重规划；
- Planner、Writer、Critic、Editor、Continuity Auditor 等专职 Agent 协作；
- `ChapterContract` 会编译为场景义务并提前发现“既要求又禁止”等不可执行冲突；
- 每条合同义务都保留正文证据跨度、失败分类和目标场景；失败时只修补命中的场景；
- 候选生成 → 合同义务验收 → 统一质量/连续性/人物风险审查 → 有限修复；
- 所有 AI 修订均以带来源摘要的 `ScenePatch` 执行，正文始终由场景正文重建；
- 高风险场景才会生成受约束备选稿：先过硬约束门禁，再以盲标识质量选择器选稿，并复审相邻场景交接；
- 每章生成路径有调用数与 token 硬预算，预算使用和候选选择证据随生成报告保存；
- 合同失败会延后昂贵的全文审查；重复候选复用审查缓存，减少重复调用与上下文传输；
- 只有通过门禁的候选才能进入正式正文；
- 每次正文修改都有版本历史，知识绑定正文版本与 SHA-256 摘要；
- SQLite 是唯一事实源，向量、全文与图索引均可删除重建；
- AI 修订先形成可审查提案，接受前不会覆盖正文；
- Agent Run、Step、候选稿和评审证据独立存储，支持追踪和审批恢复；
- Story 乐观版本控制，旧快照不能覆盖新事实；
- CLI、REST API、写作工作区与全景数据页共用同一组应用用例。

完整设计见 [架构](docs/ARCHITECTURE.md)、[知识管线](docs/KNOWLEDGE_PIPELINE.md)、[存储模型](docs/STORAGE_MODEL.md) 和 [项目地图](docs/PROJECT_MAP.md)。

## 启动

```bash
python -m pip install -r requirements.txt
python -m uvicorn novelforge.api.main:app --reload
```

打开：

- 写作区：`http://127.0.0.1:8000/workspace/`
- API 文档：`http://127.0.0.1:8000/docs`
- 全景数据：`http://127.0.0.1:8000/dashboard/`

命令行：

```bash
python -m novelforge
```

加载故事后可使用自然语言目标：

```text
novelforge> agent 继续写第 3 章，但主角不能提前知道凶手身份
```

## 配置

默认使用 `mock` 模型，便于本地运行。使用 DeepSeek 时在 `.env` 中设置：

```dotenv
DEEPSEEK_API_KEY=...
NOVELFORGE_LLM_PROVIDER=deepseek
```

生成可靠性由 `config.yaml` 的 `generation` 段控制：

```yaml
generation:
  min_quality_score: 7.5
  max_repairs: 2
  require_contract_pass: true
  require_continuity_pass: true
  max_generation_calls: 16
  max_generation_tokens: 42000
  quality_search_enabled: true
  quality_search_max_scenes: 1
  quality_search_candidates: 2
```

## 真实效果评测

`evals/run_eval.py` 只用于快速、确定性的规则回归，不能证明真实模型写作质量。
需要验证实际效果时，使用真实供应商运行盲测 A/B：

```bash
python -m evals.live_quality --repetitions 3
```

该评测目前覆盖现实悬疑、奇幻、都市情感、科幻和现实主义等 6 个案例；在同一故事、大纲
和章节合同下比较“单次直写”与完整 NovelForge 流程，并交换 A/B 顺序复评。正文、硬指标、
模型、请求、内部质量门禁和评审证据写入 `evals/live_results/`（本地忽略，不进入 Git）。
`summary.json` 会汇总质量胜率、基线/流程的硬约束通过率，以及调用数、token、耗时和相对差值。
默认每例运行 3 次；少于 3 次重复实验，或交换顺序后结论不一致时，只报告 `insufficient_evidence`，不会宣称升级成功。评测记录还会保留 v0.4 的预算消耗、候选选择和局部补丁复审证据。

## 数据目录

```text
.data/novelforge/
├── novelforge.db
├── artifacts/
└── indexes/
```

索引目录可以整体删除；正式故事只能从 SQLite 读取。
