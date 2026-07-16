# NovelForge

NovelForge 是一个受约束的多智能体长篇创作系统。Story Orchestrator 能够理解用户目标、拆解任务、选择专职 Agent 和工具、观察结果并有限重规划；确定性应用层负责质量门禁、版本控制和正式提交。

## 核心能力

- 大纲、章节契约与结构化场景规划；
- `StoryOrchestratorAgent` 自主规划、工具选择、任务验收与失败重规划；
- Planner、Writer、Critic、Editor、Continuity Auditor 等专职 Agent 协作；
- 候选生成 → 契约校验 → 连续性审计 → 质量评分 → 有限修复；
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
```

## 数据目录

```text
.data/novelforge/
├── novelforge.db
├── artifacts/
└── indexes/
```

索引目录可以整体删除；正式故事只能从 SQLite 读取。
