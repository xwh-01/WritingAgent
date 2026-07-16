# NovelForge 架构

NovelForge 是一个受约束的多智能体长篇创作系统。自主智能体负责理解目标、拆分任务、选择工具和观察结果；确定性的应用层负责事务、版本、质量门禁和正式提交。

## 总体结构

```text
用户目标
   ↓
StoryOrchestratorAgent
   ├─ 生成可验证计划
   ├─ 选择专职 Agent 工具
   ├─ 观察结构化结果
   ├─ 失败后有限重规划
   └─ 等待人工批准 / 完成 / 失败
   ↓
StoryAgentRuntime
   ├─ 步骤预算
   ├─ 运行状态机
   ├─ Run / Step / Candidate 记录
   └─ 权限与审批边界
   ↓
Application Services
   ├─ Planner / Writer / Critic / Editor
   ├─ 契约验证与连续性审计
   ├─ 正文提交与知识派生
   └─ 索引投影
   ↓
Domain + SQLite
```

## 三种数据生命周期

| 数据 | 所有者 | 说明 |
|---|---|---|
| 正式事实 | `Story` | 作者设计、正式正文、正文知识、当前版本质量证据 |
| 智能体工作 | `AgentRunRepository` | 目标、计划、步骤、候选稿、候选评审、修订提案 |
| 检索投影 | `DerivedIndexService` | 全文、向量和图索引，可删除重建 |

`Story` 不保存 Agent 运行记录或修订候选。候选内容只有通过门禁并由 `ChapterWorkflow` 提交后，才进入 `Manuscript` 并派生正式知识。

## 智能体循环

```text
Goal
 → Plan
 → Select Tool
 → Execute
 → Observe
 → Evaluate
 ├─ Continue
 ├─ Replan（最多一次）
 ├─ Wait for approval
 └─ Complete / Fail
```

Orchestrator 不能访问 Repository，只能调用工具目录中的结构化用例。每次运行有最大步骤数；模型不返回或保存隐藏思维链，只记录任务描述、工具选择、结构化观察和验收证据。

## 可靠写章

```text
正式历史视图
 → 场景规划
 → Writer 候选稿
 → 契约检查 + 连续性检查 + 质量评分
 → 有限修复
 → Candidate 运行存储
 ├─ 拒绝：保留证据，不修改 Story
 └─ 接受：正文 + 知识原子提交，Candidate 标记 committed
```

`Story.generation_view(N)` 隐藏旧的第 N 章正文、未来正文及相应知识，避免旧版本和未来信息污染模型。

## 并发与一致性

每次 Story 保存都会递增 `revision`。更新语句要求调用方持有当前 revision；旧快照保存时抛出 `ConcurrentUpdateError`，从而避免多个请求或 Agent 互相覆盖。

正式 Story 与 `projection_outbox` 在同一 SQLite 事务写入。索引失败不回滚正文，事件保持 pending，之后可以重建。

## 依赖规则

- `domain/` 不依赖 application、storage 或 indexes；
- Agent 负责判断与生成，不直接写数据库；
- 工具层把 Agent 决策转换成应用用例；
- `ChapterWorkflow` 是机器候选进入正式正文的唯一入口；
- `ChapterKnowledgePipeline` 是正文派生知识的唯一入口；
- 检索结果只用于定位，SQLite 正式状态决定事实。
