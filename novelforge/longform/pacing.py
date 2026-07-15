"""Pacing analysis for chapters and recent trends."""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from statistics import mean
from typing import Any


class IPacingAnalyzer(ABC):
    """节奏分析器的抽象接口。"""

    @abstractmethod
    def analyze_chapter(self, content: str) -> dict[str, Any]:
        """分析单个章节的节奏指标，返回包含冲突强度、对话占比等指标的字典。"""
        raise NotImplementedError


class PacingAnalyzer(IPacingAnalyzer):
    """基于规则和统计的节奏分析器，对章节冲突强度、对话密度等进行量化评估。

    使用跨类型通用的信号词表，适用于奇幻、科幻、言情、悬疑、武侠、现实等各类小说。
    """

    # Genre-agnostic conflict words — tension, opposition, stakes, failure.
    conflict_words: tuple[str, ...] = (
        "冲突",
        "怒",
        "战",
        "追",
        "逃",
        "危险",
        "失败",
        "秘密",
        "真相",
        "背叛",
        "受伤",
        "选择",
        "争",
        "夺",
        "杀",
        "死",
        "恨",
        "牺牲",
        "威胁",
        "恐惧",
        "阴谋",
        "fight",
        "battle",
        "conflict",
        "danger",
        "betray",
        "kill",
        "threat",
    )

    # Genre-agnostic action words — physical movement, decisive action.
    action_words: tuple[str, ...] = (
        "冲",
        "跑",
        "扑",
        "击",
        "推",
        "摔",
        "喊",
        "抢",
        "跳",
        "拉",
        "踢",
        "砍",
        "刺",
        "射",
        "挡",
        "爬",
        "rush",
        "strike",
        "push",
        "grab",
        "jump",
        "kick",
        "slash",
        "block",
    )

    def analyze_chapter(self, content: str) -> dict[str, Any]:
        """统计章节中的冲突词、动作词、对话行等，返回五维节奏指标。"""
        lines = [line.strip() for line in content.splitlines() if line.strip()]
        total_lines = max(len(lines), 1)
        dialogue_lines = sum(1 for line in lines if self._is_dialogue(line))
        sentences = [part for part in re.split(r"[。！？!?]+", content) if part.strip()]
        conflict_hits = sum(content.count(word) for word in self.conflict_words)
        action_hits = sum(content.count(word) for word in self.action_words)
        conflict_intensity = min(10, max(1, 1 + conflict_hits + action_hits // 2))
        dialogue_ratio = round(dialogue_lines / total_lines, 2)
        description_density = round(
            sum(len(sentence) for sentence in sentences) / max(len(sentences), 1) / 80, 2
        )
        plot_progress = min(10, max(1, action_hits + conflict_hits + len(sentences) // 8))
        return {
            "conflict_intensity": conflict_intensity,
            "dialogue_ratio": dialogue_ratio,
            "description_density": description_density,
            "plot_progress": plot_progress,
            "line_count": total_lines,
        }

    def check_pacing_trend(self, analyses: list[dict[str, Any]]) -> str:
        """根据最近几章的节奏分析结果判断趋势，返回正常或预警信息。"""
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
        """判断一行文本是否为对话行（以引号开头或包含冒号式对话标记）。

        对中文小说，对话常以 "" 或「」开头。
        对英文小说，对话以 " 或 ' 开头。
        为避免冒号误判（如 "Chapter 3: The Beginning"），
        冒号检测需要前面有非空格的汉字或字母。
        """
        if line.startswith((""", """, '"', "'", "「")):
            return True
        # Colon-style dialogue markers: "某某：..."  or "Name: ..."
        if re.search(r"[一-鿿a-zA-Z]：", line):
            return True
        return False
