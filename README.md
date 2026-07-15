# NovelForge

NovelForge 是一个面向长篇小说的可靠生成与知识管理项目。它把作者设计、正式正文、正文派生知识、质量证据和操作报告分开管理，避免“记忆、正文和缓存混在一起”。

## 核心能力

- 大纲、章节契约与结构化场景规划；
- 候选生成 → 契约校验 → 连续性审计 → 质量评分 → 有限修复；
- 只有通过门禁的候选才能进入正式正文；
- 每次正文修改都有版本历史，知识绑定正文版本与 SHA-256 摘要；
- SQLite 是唯一事实源，向量、全文与图索引均可删除重建；
- AI 修订先形成可审查提案，接受前不会覆盖正文；
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
