# Memory Engine v2

NovelForge now includes a long-novel memory layer designed for 1000-chapter scale experiments.

## What It Stores

- `memory_cards`: durable retrieval units for chapter summaries, causal events, foreshadowing, and character states.
- `arc_summaries`: rolling 20-chapter arc summaries for medium-range continuity.
- `story_bible`: global premise, active threads, character roster, current direction, and continuity constraints.

## Retrieval Sources

Before writing or reviewing a chapter, NovelForge can assemble context from:

- structured Story JSON
- Chroma `plot_summaries`
- Chroma `memory_cards`
- SQLite full-text search
- NetworkX relationship graph
- Memory Engine v2 context pack

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
