# NovelForge 架构

NovelForge 的核心原则只有三条：正式正文必须经过明确的提交边界；知识必须能追溯到正文的精确版本；SQLite 是唯一事实源。

## 聚合内的五个边界

`Story` 是唯一聚合根，数据按所有权拆成五块：

| 边界 | 类型 | 唯一职责 |
|---|---|---|
| 作者意图 | `StoryDesign` | 角色设定、世界设定、大纲、章节验收契约 |
| 正式正文 | `Manuscript` | 章节、场景计划、版本历史 |
| 正文知识 | `StoryKnowledge` | 从正式正文派生的观察、事实、状态、事件、伏笔和摘要 |
| 质量证据 | `StoryQuality` | 生成尝试、门禁结果、评审、连续性报告、修订提案 |
| 操作报告 | `StoryRuns` | 批量写作结果，不参与故事事实判断 |

设计数据和派生知识不会互相覆盖。正文中出现的新角色只会成为 `CharacterObservation`；只有作者或明确的设计用例才能把它提升为 `StoryDesign.characters`。

## 可靠生成链路

```text
StoryDesign + 第 N 章之前的正式历史
                  ↓
             候选 Chapter
                  ↓
      契约校验 + 连续性审计 + 质量评分
                  ↓
          修复（最多 max_repairs 次）
                  ↓
       接受 ─────────────── 拒绝
        ↓                    ↓
  提交 Manuscript       只保存失败报告
        ↓
  原子派生 StoryKnowledge
        ↓
  SQLite 正式提交
        ↓
  重建可删除索引
```

候选正文不在 `Manuscript` 中暂存。重写第 N 章时，`Story.generation_view(N)` 会隐藏旧的第 N 章正文、所有未来正文和相应知识，避免旧版本泄漏与自我抄写。

## 分层与依赖方向

```text
API / CLI / Workspace
        ↓
orchestrator/engine.py      薄门面：组装依赖、转发用例
        ↓
application/               规划、生成、评审、修订、批量、提交协议
        ↓
domain/                    无基础设施依赖的业务类型和不变量
        ↑
agents/ + longform/         LLM 能力与确定性知识处理
        ↓
storage/ + indexes/         SQLite 事实源与可重建投影
```

约束：

- Agent 只返回结果，不写数据库；
- `ChapterWorkflow` 是机器生成正文进入正式稿的唯一入口；
- `ChapterKnowledgePipeline` 是正文变成知识的唯一入口；
- `StoryCommitCoordinator` 在保存前检查聚合一致性；
- 索引失败不会回滚已经成功的正式提交，也不会诱导调用方重复生成。

## 核心应用服务

| 服务 | 职责 |
|---|---|
| `StoryPlanningService` | 创建故事、大纲、契约和场景计划 |
| `ChapterGenerationPipeline` | 候选生成、评估和有限修复，不提交 |
| `ChapterWorkflow` | 接受候选、知识派生、正式提交 |
| `ChapterReviewService` | 只读正文并保存质量证据 |
| `ChapterEditingService` | 人工编辑与审批式 AI 修订 |
| `BatchWritingService` | 顺序复用同一个单章可靠用例 |
| `StoryStorageService` | 跨正式库、索引和制品的删除与状态查询 |
