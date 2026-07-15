# 存储模型

## 唯一事实源

| 类别 | 默认位置 | 权威性 | 恢复方式 |
|---|---|---|---|
| 完整 `Story` 聚合 | `.data/novelforge/novelforge.db` | 唯一事实源 | 数据库备份 |
| 全文、向量、图索引 | `.data/novelforge/indexes/` | 可删除投影 | 从 SQLite 重建 |
| DOCX / Markdown 制品 | `.data/novelforge/artifacts/` | 可删除输出 | 重新导出 |

没有旧 JSON 导入、双写目录或索引反向恢复逻辑。

## 提交协议

```text
Story.assert_consistent()
        ↓
SQLite 事务保存 Story
        ↓
同一事务写 projection_outbox
        ↓
尝试重建派生索引
        ├─ 成功：确认 outbox
        └─ 失败：保留 outbox，正式提交仍成功
```

不能因为索引失败把正文提交报告成失败。否则调用方重试生成会产生多余版本。索引同步状态通过 `GET /stories/{id}/storage` 查看，并可用 `POST /stories/{id}/indexes/rebuild` 恢复。

## 删除

`StoryStorageService.delete_story()` 是“删除一个故事全部数据”的唯一跨存储入口，依次清理索引、制品和正式记录。仓储自身的 `delete()` 只负责 SQLite，不暗中操作其他存储。
