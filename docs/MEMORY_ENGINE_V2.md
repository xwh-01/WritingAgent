# Memory Engine v2

NovelForge now includes a long-novel memory layer designed for 1000-chapter scale experiments.

## What It Stores

- `memory_cards`: durable retrieval units for chapter summaries, causal events, foreshadowing, and character states.
- `arc_summaries`: rolling 20-chapter arc summaries for medium-range continuity.
- `story_bible`: global premise, active threads, character roster, current direction, and continuity constraints.
- `characters`: automatically maintained character registry.
- `world_settings`: automatically maintained world and rule registry.
- `relationships.json`: graph-backed character relationship memory.

## Memory Extractor Agent

After a chapter is written or revised, `MemoryExtractorAgent` extracts:

- new or updated characters
- world facts and rule settings
- relationship changes
- continuity constraints

The extracted facts are applied to the Story model, indexed into Chroma `characters` and `world`
collections, and written into the NetworkX relationship graph. This turns each generated chapter into
structured memory, not just prose.

## Retrieval Sources

Before writing or reviewing a chapter, NovelForge can assemble context from:

- structured Story JSON
- Chroma `plot_summaries`
- Chroma `memory_cards`
- SQLite full-text search
- NetworkX relationship graph
- Memory Engine v2 context pack

## Memory Ranker

Retrieved memories are reranked before they enter the prompt. The ranker combines:

- vector similarity
- memory type priority
- chapter recency
- query term overlap
- active character/entity overlap
- explicit importance on structured memory cards

This avoids stuffing every retrieved item into the prompt and makes later chapters more likely to see the most relevant continuity facts.

## Continuity Auditor

After a chapter is written or revised, NovelForge runs a continuity audit and stores the report in
`story.continuity_reports`. The auditor checks:

- story bible and continuity constraint violations
- overdue foreshadowing
- character-state contradictions
- causal or location transitions
- chapter-goal mismatch

The report is available through `GET /chapters/{chapter_index}/report` and is shown in the workspace quality panel.

## Chapter Context Pack

The context pack is built for one target chapter and may include:

- global story bible
- current arc summary
- current volume summary
- recent chapter summaries
- current character states
- open foreshadowing
- causal threads
- retrieved memory cards
- continuity constraints

This moves NovelForge from basic chapter-summary RAG toward hierarchical long-form memory. It still does not make 1000 chapters magically easy, but it gives the system the right memory shape: global, arc-level, recent, entity-level, and retrieval-level state.
