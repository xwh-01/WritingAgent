"""Extract a typed knowledge proposal from committed chapter text."""

from __future__ import annotations

import json
import re

from pydantic import BaseModel, Field

from novelforge.agents.base import BaseAgent
from novelforge.core.utils import is_stop_word, stable_digest
from novelforge.domain import Character, Story, WorldSetting
from novelforge.llm.base import LLMClient

# ---------------------------------------------------------------------------
# Generic signal-word tables — genre-agnostic, work across all story types
# ---------------------------------------------------------------------------

# Common Chinese surnames (百家姓 top ~60) used for NER-style character discovery.
_COMMON_SURNAMES: set[str] = {
    "王",
    "李",
    "张",
    "刘",
    "陈",
    "杨",
    "黄",
    "赵",
    "周",
    "吴",
    "徐",
    "孙",
    "马",
    "朱",
    "胡",
    "郭",
    "何",
    "高",
    "林",
    "罗",
    "郑",
    "梁",
    "谢",
    "宋",
    "唐",
    "韩",
    "曹",
    "许",
    "邓",
    "萧",
    "冯",
    "曾",
    "程",
    "蔡",
    "彭",
    "潘",
    "袁",
    "董",
    "余",
    "苏",
    "叶",
    "卢",
    "蒋",
    "蔡",
    "贾",
    "丁",
    "魏",
    "薛",
    "阎",
    "雷",
    "白",
    "崔",
    "康",
    "毛",
    "邱",
    "秦",
    "江",
    "史",
    "顾",
    "侯",
}

# Role / title suffixes that hint at a character mention.
_TITLE_SUFFIXES: set[str] = {
    "教练",
    "老师",
    "队长",
    "医生",
    "掌门",
    "长老",
    "师兄",
    "师姐",
    "师父",
    "师傅",
    "经理",
    "老板",
    "教授",
    "警官",
    "侦探",
    "将军",
    "统帅",
    "领主",
    "国王",
    "王子",
    "公主",
    "剑圣",
    "法师",
    "门主",
    "帮主",
    "会长",
    "局长",
    "司长",
    "总编",
    "导演",
    "船长",
    "舰长",
}

# Location indicators — words that often precede or describe a place.
_LOCATION_MARKERS: set[str] = {
    "在",
    "去",
    "来到",
    "进入",
    "离开",
    "穿过",
    "前往",
    "返回",
    "抵达",
    "到达",
    "经过",
    "回",
    "往",
    "到",
}

# Category detection patterns: (category_name, template_text, signal_words)
_WORLD_CATEGORY_PATTERNS: list[tuple[str, str, tuple[str, ...]]] = [
    (
        "location",
        "A recurring location in the story.",
        (
            "城",
            "镇",
            "村",
            "山",
            "湖",
            "海",
            "河",
            "林",
            "塔",
            "殿",
            "宫",
            "阁",
            "楼",
            "院",
            "街",
            "广场",
            "岛",
            "堡",
            "庙",
            "寺",
            "洞",
            "谷",
            "原",
            "沙漠",
            "沼泽",
            "草原",
            "森林",
            "山脉",
        ),
    ),
    (
        "faction",
        "A faction, organization, or group.",
        (
            "门",
            "派",
            "帮",
            "会",
            "教",
            "族",
            "国",
            "联盟",
            "帝国",
            "王朝",
            "部落",
            "公会",
            "军团",
            "卫队",
            "组织",
            "集团",
            "家族",
        ),
    ),
    (
        "ability_system",
        "A power system, skill, technique, or ability.",
        (
            "功",
            "法",
            "术",
            "技",
            "诀",
            "式",
            "能",
            "力",
            "天赋",
            "异能",
            "魔法",
            "仙术",
            "武技",
            "秘籍",
            "心法",
            "招式",
        ),
    ),
    (
        "artifact",
        "A significant object, weapon, or artifact.",
        (
            "剑",
            "刀",
            "枪",
            "弓",
            "杖",
            "锤",
            "斧",
            "盾",
            "戒",
            "印",
            "符",
            "鼎",
            "珠",
            "镜",
            "炉",
            "索",
            "神器",
            "法宝",
            "武器",
        ),
    ),
    (
        "rule",
        "A world rule, law, or constraint.",
        (
            "规则",
            "法则",
            "定律",
            "禁忌",
            "诅咒",
            "契约",
            "预言",
            "天劫",
            "因果",
            "天道",
            "命运",
            "誓约",
            "血誓",
        ),
    ),
    (
        "custom",
        "A cultural custom, ritual, or tradition.",
        (
            "仪式",
            "节日",
            "典礼",
            "试炼",
            "考核",
            "比试",
            "大比",
            "成",
            "礼",
            "婚",
            "葬",
            "祭",
            "典",
            "宴",
        ),
    ),
]

# Universal narrative constraint signal words — genre-agnostic.
_CONSTRAINT_SIGNALS: list[tuple[str, str]] = [
    # (signal_words → constraint template)
    (
        "秘密|隐瞒|不能说|真相|揭开|藏|瞒|隐情",
        "Unresolved secret or concealed truth needs a reveal chapter.",
    ),
    (
        "伤|病|中毒|诅咒|虚弱|感染|发作|复发",
        "Track this condition/injury across later chapters until recovery is shown.",
    ),
    (
        "承诺|约定|发誓|誓言|保证|答应|必须还|欠",
        "Unfulfilled promise or oath — follow through in a later chapter.",
    ),
    (
        "威胁|追杀|通缉|敌人|仇|报复|埋伏|暗算",
        "Pending threat or enemy — resolve or escalate in a subsequent chapter.",
    ),
    (
        "分手|决裂|背叛|出卖|误会|翻脸|反目",
        "Relationship rupture — track whether it heals or deepens across chapters.",
    ),
    (
        "还差|未完成|尚未|还没|仍要|还要|仍需",
        "Unfinished task or goal — ensure it is addressed before being dropped.",
    ),
    (
        "新|变化|改变|突破|觉醒|升级|进阶|领悟",
        "Character growth or power change — keep consistent with this new baseline.",
    ),
]


class ExtractedRelationship(BaseModel):
    """提取出的角色关系。"""

    source: str
    target: str
    relation: str = "related"


class ChapterKnowledgeExtraction(BaseModel):
    """记忆提取结果，包含角色、世界观设定、关系与连续性约束。"""

    characters: list[Character] = Field(default_factory=list)
    world_settings: list[WorldSetting] = Field(default_factory=list)
    relationships: list[ExtractedRelationship] = Field(default_factory=list)
    continuity_constraints: list[str] = Field(default_factory=list)


class KnowledgeExtractorAgent(BaseAgent):
    """记忆提取 Agent，从章节文本中提取结构化长期记忆。"""

    name = "knowledge_extractor"

    def __init__(self, llm: LLMClient | None) -> None:
        """初始化记忆提取器，LLM 可选（为 None 时走规则兜底）。"""
        self.llm = llm

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def extract_chapter_knowledge(
        self, story: Story, chapter_index: int, content: str
    ) -> ChapterKnowledgeExtraction:
        """从章节内容中提取角色、世界观、关系和连续性约束。优先用 LLM，失败则规则兜底。"""
        if self.llm is None:
            return self._rule_extract(story, chapter_index, content)

        system = (
            "You extract durable story knowledge from approved prose. Extract continuity facts "
            "from a chapter. "
            "Return strict JSON matching this schema: "
            "{characters:[Character], world_settings:[WorldSetting], "
            "relationships:[{source,target,relation}], continuity_constraints:[string]}. "
            "Only include facts supported by the chapter."
        )
        user = (
            "knowledge_extract\n"
            f"chapter={chapter_index}\n"
            f"story={json.dumps({'title': story.title, 'premise': story.premise}, ensure_ascii=False)}\n"
            f"existing_characters={json.dumps([c.model_dump() for c in story.design.characters.values()], ensure_ascii=False)}\n"
            f"content={content[:12000]}"
        )
        try:
            return self._chat_model(system, user, ChapterKnowledgeExtraction)
        except Exception:
            return self._rule_extract(story, chapter_index, content)

    # ------------------------------------------------------------------
    # Rule-based fallback
    # ------------------------------------------------------------------

    def _rule_extract(
        self, story: Story, chapter_index: int, content: str
    ) -> ChapterKnowledgeExtraction:
        """基于规则的记忆提取兜底方案。完全不依赖特定故事领域知识。"""
        characters = self._extract_characters(story, content)
        world_settings = self._extract_world_settings(story, chapter_index, content)
        relationships = self._extract_relationships(characters, content)
        constraints = self._extract_constraints(content)
        return ChapterKnowledgeExtraction(
            characters=characters,
            world_settings=world_settings,
            relationships=relationships,
            continuity_constraints=constraints,
        )

    # ------------------------------------------------------------------
    # Character extraction
    # ------------------------------------------------------------------

    def _extract_characters(self, story: Story, content: str) -> list[Character]:
        """从内容中提取角色。

        策略：
        1. 匹配 story 中已存在的角色（按 name / id 搜索）。
        2. 用通用中文姓名模式发现新角色。
        3. 用英文大写专名发现外文角色。
        """
        found: dict[str, Character] = {}

        # 1. Match characters already known to the story.
        for character in story.design.characters.values():
            if character.name and (character.name in content or character.id in content):
                found[character.id] = character

        # 2. Detect new characters via generic Chinese name patterns.
        self._discover_chinese_characters(content, found)

        # 3. Detect English-name characters (fallback for translated / mixed-genre).
        self._discover_english_characters(content, found)

        return list(found.values())

    def _discover_chinese_characters(self, content: str, found: dict[str, Character]) -> None:
        """Use common surname + given-name patterns to find new Chinese characters."""
        # Pattern: common surname + 1-2 Chinese chars (most Chinese names)
        surname_alt = "|".join(_COMMON_SURNAMES)
        for match in re.finditer(
            rf"(?:^|[。！？，,\n\s])([{surname_alt}])([一-鿿]{{1,2}})(?:[，。！？、\n\s]|$|的|说|道|想|在|去|来|到|要|从|把|被|给|向|与|和|跟|对|让|就|都|也|却|还|便|却|将|已|正|刚|才|又|再)",
            content,
        ):
            name = match.group(1) + match.group(2)
            if is_stop_word(name):
                continue
            character_id = self._slug(name)
            if character_id not in found:
                found[character_id] = Character(
                    id=character_id,
                    name=name,
                    personality=self._infer_trait_from_context(name, content),
                    motivation=self._infer_motivation_from_context(name, content),
                )
            if len(found) >= 12:
                return

        # Pattern: role/title suffix — 陈教练, 李老师, 张掌门, etc.
        titles_alt = "|".join(_TITLE_SUFFIXES)
        for match in re.finditer(
            rf"([{''.join(_COMMON_SURNAMES)}]?\w{{1,3}}?)(?:{titles_alt})", content
        ):
            raw = match.group(0)
            name = raw.rstrip("，。！？、\n ")
            character_id = self._slug(name)
            if is_stop_word(name) or character_id in found:
                continue
            found[character_id] = Character(
                id=character_id,
                name=name,
                personality="",
                motivation="",
            )
            if len(found) >= 12:
                return

    def _discover_english_characters(self, content: str, found: dict[str, Character]) -> None:
        """Detect English proper names as potential characters."""
        for match in re.findall(r"\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)?\b", content):
            name = match
            if name.lower() in {
                "chapter",
                "knowledge",
                "agent",
                "the",
                "this",
                "that",
                "with",
                "from",
            }:
                continue
            character_id = self._slug(name)
            if character_id not in found:
                found[character_id] = Character(id=character_id, name=name)
            if len(found) >= 12:
                return

    def _infer_trait_from_context(self, name: str, content: str) -> str:
        """从角色名周围的上下文推断性格特征（通用启发式）。"""
        # Collect adjectives / descriptors near the character's name mentions.
        descriptors: list[str] = []
        trait_signals = {
            "冷静": "沉着",
            "勇敢": "勇敢",
            "聪明": "聪明",
            "善良": "善良",
            "果断": "果断",
            "谨慎": "谨慎",
            "冲动": "冲动",
            "狡猾": "狡猾",
            "坚毅": "坚毅",
            "敏锐": "敏锐",
            "温柔": "温柔",
            "冷酷": "冷酷",
            "倔强": "倔强",
            "固执": "固执",
            "开朗": "开朗",
            "内敛": "内敛",
            "孤傲": "孤傲",
            "隐忍": "隐忍",
            "狂妄": "狂妄",
            "胆小": "胆小",
            "忠诚": "忠诚",
            "正直": "正直",
            "阴险": "阴险",
            "贪婪": "贪婪",
            "沉默": "沉默寡言",
            "幽默": "幽默",
            "乐观": "乐观",
            "悲观": "悲观",
        }
        sentences = re.split(r"[。！？\n]+", content)
        for sentence in sentences:
            if name not in sentence:
                continue
            for signal, trait in trait_signals.items():
                if signal in sentence and trait not in descriptors:
                    descriptors.append(trait)
            if len(descriptors) >= 3:
                break
        return "、".join(descriptors) if descriptors else ""

    def _infer_motivation_from_context(self, name: str, content: str) -> str:
        """从角色名周围的上下文推断动机（通用启发式）。"""
        motivation_signals = [
            ("保护", "保护重要的人"),
            ("报仇", "复仇"),
            ("变强", "变强"),
            ("寻找", "寻找真相"),
            ("逃", "逃离/生存"),
            ("证明", "证明自己"),
            ("守护", "守护珍视之物"),
            ("成为", "追求卓越"),
            ("阻止", "阻止灾难"),
            ("得到", "获得渴望之物"),
            ("赢", "赢得胜利"),
            ("救", "救赎"),
            ("学到", "学习/成长"),
            ("推翻", "推翻压迫"),
            ("建立", "建立新秩序"),
        ]
        sentences = re.split(r"[。！？\n]+", content)
        for sentence in sentences:
            if name not in sentence:
                continue
            for signal, motivation in motivation_signals:
                if signal in sentence:
                    return motivation
        return ""

    # ------------------------------------------------------------------
    # World-settings extraction
    # ------------------------------------------------------------------

    def _extract_world_settings(
        self, story: Story, chapter_index: int, content: str
    ) -> list[WorldSetting]:
        """从内容中提取世界观设定（通用方式）。

        策略：
        1. 扫描频次较高的有意义名词短语。
        2. 用通用类别模式做分类（location / faction / ability_system / artifact / rule / custom）。
        3. 已存在于 story.design.world_settings 的跳过。
        """
        settings: list[WorldSetting] = []
        existing_content = {item.content for item in story.design.world_settings}

        # Scan for category matches.
        for category, template_text, signal_words in _WORLD_CATEGORY_PATTERNS:
            for word in signal_words:
                if word not in content:
                    continue
                # Find the phrase containing this signal word for a meaningful description.
                phrase = self._extract_phrase_around(content, word, max_len=40)
                if not phrase or phrase in existing_content:
                    continue
                setting = WorldSetting(
                    id=f"world-{category}-{stable_digest(phrase, str(chapter_index))}",
                    category=category,
                    content=f"[{category}] {phrase}",
                    metadata={"chapter": chapter_index, "detected_via": word},
                )
                settings.append(setting)
                existing_content.add(phrase)
                if len(settings) >= 10:
                    return settings

        # Also try to detect locations that don't match the category patterns above.
        self._detect_locations(content, chapter_index, settings, existing_content)

        return settings[:10]

    @staticmethod
    def _extract_phrase_around(content: str, keyword: str, max_len: int = 40) -> str:
        """Extract a short phrase surrounding *keyword* in *content*."""
        idx = content.find(keyword)
        if idx == -1:
            return ""
        # Expand left to a sentence boundary or space.
        start = max(0, idx - 15)
        # Try to start at a Chinese punctuation boundary for cleaner phrases.
        for sep in ("。", "！", "？", "，", "、", "\n", " "):
            candidate = content.rfind(sep, start, idx)
            if candidate != -1:
                start = candidate + 1
                break
        end = min(len(content), idx + len(keyword) + 15)
        for sep in ("。", "！", "？", "，", "、", "\n"):
            candidate = content.find(sep, idx + len(keyword), end)
            if candidate != -1:
                end = candidate
                break
        phrase = content[start:end].strip()
        return phrase[:max_len]

    def _detect_locations(
        self,
        content: str,
        chapter_index: int,
        settings: list[WorldSetting],
        existing_content: set[str],
    ) -> None:
        """使用位置指示词检测可能的地点名。"""
        location_alt = "|".join(_LOCATION_MARKERS)
        for match in re.finditer(rf"(?:{location_alt})([一-鿿]{{2,6}})", content):
            candidate = match.group(1)
            if candidate in existing_content or len(candidate) < 2:
                continue
            # Avoid matching common non-location words.
            if candidate in {
                "这里",
                "那里",
                "哪里",
                "外面",
                "里面",
                "前面",
                "后面",
                "上面",
                "下面",
            }:
                continue
            setting = WorldSetting(
                id=f"world-location-{stable_digest(candidate, str(chapter_index))}",
                category="location",
                content=f"[location] {candidate} is a scene location.",
                metadata={"chapter": chapter_index, "detected_via": "location_marker"},
            )
            settings.append(setting)
            existing_content.add(candidate)
            if len(settings) >= 10:
                return

    # ------------------------------------------------------------------
    # Relationship extraction
    # ------------------------------------------------------------------

    def _extract_relationships(
        self, characters: list[Character], content: str
    ) -> list[ExtractedRelationship]:
        """从同时出现在内容中的角色对推断关系。

        用通用关系信号词做细化分类：教练/师傅/老师/上级 → "mentor_student",
        队友/同伴 → "ally", 敌人/对手 → "rival", 否则 "related".
        """
        if len(characters) < 2:
            return []
        relations: list[ExtractedRelationship] = []
        for left in characters:
            for right in characters:
                if left.id == right.id:
                    continue
                if left.name not in content or right.name not in content:
                    continue

                relation = self._classify_relation(left.name, right.name, content)
                relations.append(
                    ExtractedRelationship(source=left.id, target=right.id, relation=relation)
                )
                if len(relations) >= 8:
                    return relations
        return relations

    @staticmethod
    def _classify_relation(name_a: str, name_b: str, content: str) -> str:
        """根据上下文中的关系信号词判断关系类型。"""
        mentor_signals = {"教练", "老师", "师父", "师傅", "导师", "掌门", "长老", "mentor"}
        ally_signals = {"队友", "同伴", "朋友", "兄弟", "姐妹", "搭档", "盟友", "ally"}
        rival_signals = {"敌人", "对手", "仇", "敌", "rival", "enemy"}
        family_signals = {
            "父",
            "母",
            "兄",
            "弟",
            "姐",
            "妹",
            "儿",
            "女",
            "夫",
            "妻",
            "父女",
            "母子",
        }

        # Look for the sentence where both names co-occur.
        sentences = re.split(r"[。！？\n]+", content)
        for sentence in sentences:
            if name_a not in sentence or name_b not in sentence:
                continue
            if any(s in sentence for s in family_signals):
                return "family"
            if any(s in sentence for s in mentor_signals):
                return "mentor_student"
            if any(s in sentence for s in rival_signals):
                return "rival"
            if any(s in sentence for s in ally_signals):
                return "ally"
        return "related"

    # ------------------------------------------------------------------
    # Continuity-constraint extraction
    # ------------------------------------------------------------------

    def _extract_constraints(self, content: str) -> list[str]:
        """从内容中提取连续性约束（通用叙事信号）。

        完全基于通用叙事模式——秘密、伤病、承诺、威胁、关系破裂、未竟之事、成长变化——
        这些在任何类型（仙侠/科幻/言情/悬疑/现实）的小说中都会出现。
        """
        constraints: list[str] = []
        for signal_pattern, template in _CONSTRAINT_SIGNALS:
            if re.search(signal_pattern, content):
                constraints.append(template)
        return constraints

    # ------------------------------------------------------------------
    # Utility helpers
    # ------------------------------------------------------------------

    def _slug(self, value: str) -> str:
        """将字符串转换为 URL 安全的标识符。"""
        slug = re.sub(r"\W+", "-", value.strip().lower()).strip("-")
        return slug or f"entity-{stable_digest(value)}"
