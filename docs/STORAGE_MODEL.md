# Storage Model

## Data ownership

`novelforge/storage/novelforge.db` is the sole canonical source for a story. It contains the complete transactional Story document, including chapters, versions, contracts, facts, Director runs, plans, questions, evaluations, and revision proposals.

The following are derived data and must never be used to recover or overwrite canonical state:

- `storage/indexes/fts.sqlite3`: full-text retrieval index
- `storage/chroma_data/`: vector retrieval index
- `storage/graph_data/`: relationship graph index

`storage/artifacts/` contains non-canonical renderings: trace exports, Markdown reports, and document exports.

## Write rules

```text
API / Workspace / CLI
  -> Engine application method
  -> StoryRepository.save() transaction
  -> storage_events outbox entry
  -> derived index synchronization or rebuild
```

- Agents produce decisions, plans, reports, and candidate text. They do not write files or databases directly.
- ToolRegistry validates arguments and invokes Engine methods; it does not persist domain state itself.
- Engine methods are the application write boundary. A state change ends with `save_state()`, which writes one canonical SQLite transaction.
- Indexes are disposable. Use `POST /stories/{story_id}/indexes/rebuild` to recreate them from SQLite.

## Legacy migration

On startup, `StoryRepository` imports any unseen `storage/story_state/{story_id}.json` files once and records a `legacy_json_imported` event. Legacy JSON is retained as a read-only recovery copy; all subsequent writes go only to `novelforge.db`.

## Artifact layout

```text
storage/artifacts/stories/{story_id}/
  traces/{run_id}.json
  traces/{run_id}.debug.md
  reports/chapter-{chapter_index}-auto-revision.md
  exports/{title}.md
  exports/{title}.docx
```
