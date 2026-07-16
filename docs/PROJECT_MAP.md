# 项目地图

```text
novelforge/
├── domain/
│   ├── story.py             正式 Story 聚合与一致性规则
│   ├── design.py            作者设计
│   ├── manuscript.py        正式正文与版本
│   ├── knowledge.py         正文派生知识
│   ├── quality.py           当前正式版本的质量证据
│   └── agent_runtime.py     独立运行、步骤、候选与评审类型
├── agents/
│   ├── story_orchestrator.py 目标规划与任务验收
│   └── planner/writer/...    专职创作 Agent
├── orchestrator/
│   ├── runtime.py           Plan–Act–Observe 状态机
│   ├── tools.py             类型化工具和权限边界
│   ├── chapter_composer.py  场景级正文合成
│   └── engine.py            外部用例门面和依赖组装
├── application/             规划、生成、评审、提交、索引用例
├── storage/
│   ├── repository.py        带 revision 的正式 Story 仓储
│   ├── agent_runs.py        运行、候选和修订提案仓储
│   └── artifacts.py         导出制品
├── indexes/                 全文、向量、图投影
├── longform/                知识提取、状态、伏笔、因果和摘要
├── context/                 有时间边界和预算的写作上下文
├── api/                     REST API
├── workspace/               交互式写作与智能体目标入口
└── dashboard/               只读故事数据视图
```

放置规则：

- 业务类型和不变量放 `domain/`；
- 跨领域完成一个确定动作放 `application/`；
- 单项 LLM 能力放 `agents/`；
- 自主计划、工具选择和运行状态机放 `orchestrator/`；
- SQLite、文件与索引实现放基础设施目录；
- 工作过程不得重新放入 `Story` 聚合。
