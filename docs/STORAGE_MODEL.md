# 存储模型

NovelForge 在同一个 SQLite 文件中使用相互独立的正式表和运行表，同时把检索索引放在可删除的投影存储中。

## 存储分类

| 分类 | 数据 | 权威性 |
|---|---|---|
| 正式状态 | `stories.state_json` + `revision` | 故事唯一事实源 |
| 智能体运行 | `agent_runs`、`agent_steps` | 工作过程，可独立归档或删除 |
| 候选内容 | `chapter_candidates`、`candidate_evaluations` | 非正式内容，不参与故事事实判断 |
| 修订审批 | `revision_proposals` | 操作数据，接受前不修改正文 |
| 同步事件 | `projection_outbox` | 正式状态到索引的可靠通知 |
| 检索投影 | 全文、向量、图索引 | 可从正式状态重建 |
| 导出制品 | Markdown、DOCX | 可重新导出 |

## 正式提交

```text
Story.assert_consistent()
 → 检查 expected revision
 → revision + 1
 → SQLite 保存 Story
 → 同事务写 projection_outbox
 → 提交成功
 → 尝试重建索引
```

若 revision 已经变化，旧快照不能保存。若索引失败，正式状态仍然成功，outbox 保持未处理。

## Agent 运行

```text
agent_runs                 一次用户目标
  └─ agent_steps           每次决策和工具执行
      └─ chapter_candidates 生成或修订候选稿
          └─ candidate_evaluations  每次质量门禁证据
```

Run 保存状态、计划、当前步骤、最大步骤、模型、故事版本和结果。Step 保存工具输入输出、耗时、错误和结构化决策摘要。候选稿通过门禁之前绝不会进入 `Story.manuscript`。

## 检索投影

- 全文索引：当前正式章节正文、知识检索笔记和结构化人物事实；
- 向量索引：章节摘要、知识检索笔记、人物描述和世界事实；
- 图索引：人物节点与关系边；
- 所有投影使用 story ID 和稳定文档 ID，可以按故事删除并重建。

索引中不得存在无法从 SQLite 正式状态恢复的独有故事事实。

## 删除

`StoryStorageService.delete_story()` 统一删除该故事的索引、制品、Agent 运行、修订提案和正式 Story。Repository 自身的 `delete()` 只处理正式表，不隐式操作外部索引。
