import json
from pathlib import Path
from typing import Literal

import ahocorasick

from core.logger import get_logger

logger = get_logger(__name__)

RiskLevel = Literal["LOW", "MEDIUM", "HIGH"]

# 意图到默认风险等级的映射
INTENT_RISK_MAP: dict[str, RiskLevel] = {
    "CALL_NURSE": "LOW",
    "CALL_FAMILY": "LOW",
    "HEALTH_ALERT": "MEDIUM",
    "EMERGENCY": "HIGH",
    "UNKNOWN": "LOW",
}


class RiskController:
    """
    风险控制模块。
    使用 Aho-Corasick 多模式匹配算法高效检测紧急关键词，
    结合意图和置信度判定最终风险等级。

    原则：宁可误报（过度告警），绝不漏报紧急情况。
    """

    def __init__(self, keywords_path: str = "config/emergency_keywords.json"):
        self._keywords: dict[str, list[str]] = {}
        self._automaton = ahocorasick.Automaton()
        self._load_keywords(keywords_path)

    def _load_keywords(self, path: str) -> None:
        kw_file = Path(path)
        if not kw_file.exists():
            logger.warning("emergency_keywords_not_found", path=path)
            return

        with open(kw_file, encoding="utf-8") as f:
            self._keywords = json.load(f)

        # 构建 Aho-Corasick 自动机
        for level, words in self._keywords.items():
            for word in words:
                self._automaton.add_word(word, (level, word))
        self._automaton.make_automaton()

        total = sum(len(v) for v in self._keywords.values())
        logger.info("emergency_keywords_loaded", total=total)

    def assess_risk(
        self,
        text: str,
        intent: str,
        confidence: float,
    ) -> tuple[RiskLevel, list[str]]:
        """
        综合判定风险等级。

        判定优先级：
        1. 文本中包含 critical 紧急词 → HIGH
        2. 意图为 EMERGENCY → HIGH
        3. 文本中包含 urgent 词 → MEDIUM（除非已为 HIGH）
        4. 意图为 HEALTH_ALERT → MEDIUM（除非已更高）
        5. 低置信度 + 任何紧急词 → 升级一级
        6. 其他 → 按意图映射表

        Returns:
            (risk_level, matched_emergency_keywords)
        """
        matched: list[str] = []
        keyword_level: RiskLevel = "LOW"

        if self._automaton:
            for _, (level, word) in self._automaton.iter(text):
                matched.append(word)
                if level == "critical":
                    keyword_level = "HIGH"
                elif level == "urgent" and keyword_level != "HIGH":
                    keyword_level = "MEDIUM"
                elif level == "warning" and keyword_level == "LOW":
                    keyword_level = "LOW"  # 不升级，仅记录

        # 基础风险等级（取关键词等级和意图等级的较高值）
        intent_level = INTENT_RISK_MAP.get(intent, "LOW")
        risk_level = self._max_level(keyword_level, intent_level)

        # 低置信度 + 有匹配词 → 升级一级（宁可误报）
        if confidence < 0.6 and matched:
            risk_level = self._elevate(risk_level)
            logger.warning(
                "risk_elevated_low_confidence",
                intent=intent,
                confidence=confidence,
                matched=matched,
                new_level=risk_level,
            )

        return risk_level, matched

    @staticmethod
    def _max_level(a: RiskLevel, b: RiskLevel) -> RiskLevel:
        order = {"LOW": 0, "MEDIUM": 1, "HIGH": 2}
        return a if order[a] >= order[b] else b

    @staticmethod
    def _elevate(level: RiskLevel) -> RiskLevel:
        if level == "LOW":
            return "MEDIUM"
        if level == "MEDIUM":
            return "HIGH"
        return "HIGH"
