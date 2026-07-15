# 项目地图

```text
novelforge/
├── domain/          Story 的设计、正文、知识、质量和运行类型
├── application/     完整用例与提交协议
├── agents/          Planner / Writer / Critic / Editor / Auditor
├── longform/        原子知识派生、摘要、状态、伏笔、因果与检索
├── context/         受章节时间边界和预算限制的写作上下文
├── storage/         SQLite 正式仓储与导出制品目录
├── indexes/         可删除的向量、全文和图投影
├── orchestrator/    场景合成器与薄 Engine 门面
├── api/             FastAPI 输入输出适配器
├── workspace/       写作工作区
└── dashboard/       只读全景投影
```

定位规则：

- 数据类型和业务不变量放 `domain/`；
- 跨多个领域对象完成一个用户动作放 `application/`；
- 单次模型能力放 `agents/`；
- 正文到知识的确定性处理放 `longform/`；
- 数据库、文件、索引实现不得进入 `domain/`。
