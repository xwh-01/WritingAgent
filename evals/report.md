# NovelForge Evaluation Report

- Cases: `4`
- Passed: `4`
- Hit Rate: `100.0%`

| Case | Category | Result | Expected Keywords | Findings |
| --- | --- | --- | --- | --- |
| `causality_conflict` Causality conflict: future cause | causality | **PASS** | 未来章节, 前因 | 事件 ev-early-victory 的前因 ev-final-secret 发生在未来章节。 |
| `character_contradiction` Character contradiction: fear of water | character_state | **PASS** | 怕水, 湖, 过渡 | hero 情绪从 恐惧 到 兴奋，需要过渡或原因。<br>hero 曾被记录为怕水，但本章进入湖相关场景，缺少克服恐惧的过渡。 |
| `foreshadowing_overdue` Foreshadowing overdue | foreshadowing | **PASS** | 伏笔, 第5章, pending | 伏笔 fs-token 计划在第5章回收，但仍为 pending：后羿图案的旧护腕将在第5章决赛揭示真正用途。 |
| `pacing_flat` Pacing flat trend | pacing | **PASS** | 冲突强度偏低, 预警 | 预警：最近三章冲突强度偏低，建议插入明确转折、失败代价或对抗场景。 |
