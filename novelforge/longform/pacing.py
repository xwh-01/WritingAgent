"""Pacing analysis for chapters and recent trends."""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from statistics import mean
from typing import Any


class IPacingAnalyzer(ABC):
    @abstractmethod
    def analyze_chapter(self, content: str) -> dict[str, Any]:
        raise NotImplementedError


class PacingAnalyzer(IPacingAnalyzer):
    conflict_words = ("冲突", "怒", "战", "追", "逃", "危险", "失败", "秘密", "真相", "背叛", "受伤", "选择")
    action_words = ("冲", "跑", "扑", "射", "挡", "击", "推", "摔", "喊", "抢", "扑救")

    def analyze_chapter(self, content: str) -> dict[str, Any]:
        lines = [line.strip() for line in content.splitlines() if line.strip()]
        total_lines = max(len(lines), 1)
        dialogue_lines = sum(1 for line in lines if self._is_dialogue(line))
        sentences = [part for part in re.split(r"[。！？!?]+", content) if part.strip()]
        conflict_hits = sum(content.count(word) for word in self.conflict_words)
        action_hits = sum(content.count(word) for word in self.action_words)
        conflict_intensity = min(10, max(1, 1 + conflict_hits + action_hits // 2))
        dialogue_ratio = round(dialogue_lines / total_lines, 2)
        description_density = round(sum(len(sentence) for sentence in sentences) / max(len(sentences), 1) / 80, 2)
        plot_progress = min(10, max(1, action_hits + conflict_hits + len(sentences) // 8))
        return {
            "conflict_intensity": conflict_intensity,
            "dialogue_ratio": dialogue_ratio,
            "description_density": description_density,
            "plot_progress": plot_progress,
            "line_count": total_lines,
        }

    def check_pacing_trend(self, analyses: list[dict[str, Any]]) -> str:
        if not analyses:
            return "暂无节奏数据。"
        recent = analyses[-3:]
        avg_conflict = mean(item.get("conflict_intensity", 1) for item in recent)
        avg_dialogue = mean(item.get("dialogue_ratio", 0) for item in recent)
        if len(recent) >= 3 and avg_conflict <= 3:
            return "预警：最近三章冲突强度偏低，建议插入明确转折、失败代价或对抗场景。"
        if avg_dialogue >= 0.7:
            return "预警：对话占比过高，建议增加行动、场景压力或可视化冲突。"
        return "节奏趋势正常。"

    def _is_dialogue(self, line: str) -> bool:
        return line.startswith(("“", "\"", "「", "'")) or "：" in line or ":" in line
