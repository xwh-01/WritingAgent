"""Shared utility functions used across the codebase.

These eliminate the prior duplication of extract_json, compress, dedupe, and
stable_digest scattered through agents/ and longform/ subsystems.
"""

from __future__ import annotations

import json
import re
from hashlib import sha1
from typing import Any

# ---------------------------------------------------------------------------
# JSON extraction from LLM responses
# ---------------------------------------------------------------------------


def extract_json(text: str) -> Any:
    """从 LLM 返回的文本中提取 JSON 对象。

    三层容错策略：
    1. 匹配 ```json ... ``` 或 ``` ... ``` 代码块
    2. 直接 json.loads() 解析整段文本
    3. 正则提取首个 {...} 或 [...] 后解析

    所有失败时抛出原始异常给调用方。
    """
    text = text.strip()
    # 1. Code-fence extraction
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fenced:
        text = fenced.group(1).strip()
    # 2. Direct parse
    direct_error: json.JSONDecodeError | None = None
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        direct_error = exc
    # 3. Scan for the first independently valid JSON value. A greedy regular
    # expression treats a valid object followed by model commentary or another
    # object as one invalid blob, which used to make otherwise recoverable LLM
    # responses fail with JSONDecodeError.
    decoder = json.JSONDecoder()
    for offset, char in enumerate(text):
        if char not in "[{":
            continue
        try:
            value, _ = decoder.raw_decode(text[offset:])
            return value
        except json.JSONDecodeError:
            continue
    raise direct_error or ValueError("No JSON value found in response.")


# ---------------------------------------------------------------------------
# Text utilities
# ---------------------------------------------------------------------------


def compress(text: str, limit: int) -> str:
    """压缩多余空白字符并截断到指定长度。"""
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit]


def dedupe(values: list[str]) -> list[str]:
    """去除列表中的空白项和重复项，保持原始出现顺序。"""
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        key = value.strip()
        if not key or key in seen:
            continue
        seen.add(key)
        result.append(key)
    return result


def stable_digest(*parts: str) -> str:
    """生成稳定的 SHA1 摘要（前 10 位），用于构建确定性标识符。"""
    raw = "|".join(parts).encode("utf-8")
    return sha1(raw).hexdigest()[:10]


def int_or_none(value: Any) -> int | None:
    """安全地将任意值转为 int，失败时返回 None。"""
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def terms(text: str) -> set[str]:
    """提取文本中长度 >= 2 的中英文词条集合（小写）。"""
    return {term.lower() for term in re.findall(r"[\w一-鿿]{2,}", text)}


# ---------------------------------------------------------------------------
# Common Chinese-language stop words (for character / entity filtering)
# ---------------------------------------------------------------------------

_STOP_WORDS: set[str] = {
    "一个",
    "什么",
    "怎么",
    "为什么",
    "这个",
    "那个",
    "不是",
    "可以",
    "没有",
    "已经",
    "还是",
    "或者",
    "因为",
    "所以",
    "如果",
    "虽然",
    "但是",
    "而且",
    "然后",
    "之后",
    "以前",
    "以后",
    "总是",
    "不要",
    "一定",
    "可能",
    "应该",
    "真的",
    "觉得",
    "知道",
    "看到",
    "听到",
    "起来",
    "下来",
    "过来",
    "回去",
    "出来",
    "进去",
    "突然",
    "终于",
    "于是",
    "接着",
    "最后",
    "开始",
    "继续",
    "准备",
    "打算",
    "决定",
}


def is_stop_word(word: str) -> bool:
    """判断是否为常见中文停用词。"""
    return word in _STOP_WORDS or len(word) < 2
