# 正文知识管线

本项目不再使用含义模糊的 `memory` 容器。“知识”专指从已经提交的正文中派生、并能追溯到正文版本的结构化数据。

## 类型

| 类型 | 含义 |
|---|---|
| `KnowledgeSource` | 来源章节、正文版本、SHA-256 摘要、处理时间 |
| `CharacterObservation` | 正文支持的角色观察，不修改作者角色设定 |
| `WorldFact` | 正文支持的世界事实，不修改作者世界设定 |
| `RelationshipFact` | 某章中实际成立的角色关系 |
| `CharacterFact` | 带生效范围、来源和置信度的角色事实 |
| `CharacterState` | 某章结束时角色的位置、情绪、知识与关系变化 |
| `TimelineEvent` | 带因果引用的关键事件 |
| `Foreshadowing` | 伏笔建立、目标章节和状态 |
| `ChapterSummary` / `VolumeSummary` / `ArcSummary` | 分层摘要 |
| `RetrievalNote` | 用于检索的紧凑规范输入，不包含向量 |

`StoryKnowledge.sources[chapter]` 必须与 `Manuscript.chapters[chapter]` 的版本和正文摘要完全一致，否则聚合禁止保存。

## 替换语义

章节被重写时，知识不是继续追加：

1. 在深拷贝上删除该章旧的全部知识投影；
2. 对新的正式版本执行所有提取器；
3. 形成完整 `ChapterKnowledgeDelta`；
4. 全部成功后一次性替换 `StoryKnowledge`；
5. 保存前再次验证版本和 SHA-256 摘要。

任何一步失败，正式 `Story` 都不会出现“摘要是新版、人物状态还是旧版”的混合状态。

## 生成可见范围

生成第 N 章只可见：

- 作者明确设定的全部设计数据；
- 第 N 章之前的正式正文知识；
- 第 N 章的验收契约与场景计划。

不可见：旧的第 N 章正文、第 N 章旧知识、未来正文和未来派生知识。向量与全文检索同样限制到 `N - 1`。
