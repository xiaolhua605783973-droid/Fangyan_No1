import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml

from core.logger import get_logger

logger = get_logger(__name__)

MIN_CONFIDENCE = 0.6  # 低于此阈值返回 UNKNOWN


@dataclass
class IntentResult:
    intent: str
    confidence: float
    matched_keywords: list[str] = field(default_factory=list)
    matched_patterns: list[str] = field(default_factory=list)


class RuleBasedIntentEngine:
    """
    基于关键词 + 正则的规则意图识别引擎。
    规则配置来自 config/intent_rules.yaml，支持热更新。
    """

    def __init__(self, rules_path: str = "config/intent_rules.yaml"):
        self._rules_path = Path(rules_path)
        self._rules: dict = {}
        self._load_rules()

    def _load_rules(self) -> None:
        if not self._rules_path.exists():
            logger.warning("intent_rules_not_found", path=str(self._rules_path))
            return
        with open(self._rules_path, encoding="utf-8") as f:
            self._rules = yaml.safe_load(f) or {}
        logger.info("intent_rules_loaded", intents=list(self._rules.keys()))

    def reload_rules(self) -> None:
        """热更新规则，无需重启服务"""
        self._load_rules()
        logger.info("intent_rules_reloaded")

    def recognize(self, text: str) -> IntentResult:
        """
        对规范化后的文本进行意图识别。

        Returns:
            IntentResult，置信度低于阈值时返回 UNKNOWN
        """
        if not text or not self._rules:
            return IntentResult(intent="UNKNOWN", confidence=0.0)

        best: Optional[IntentResult] = None

        for intent, config in self._rules.items():
            score = 0.0
            matched_kw: list[str] = []
            matched_pat: list[str] = []

            # 关键词匹配（每个命中 +1.0）
            for keyword in config.get("keywords", []):
                if keyword in text:
                    score += 1.0
                    matched_kw.append(keyword)

            # 正则匹配（每个命中 +0.5）
            for pattern in config.get("patterns", []):
                if re.search(pattern, text):
                    score += 0.5
                    matched_pat.append(pattern)

            # 权重加成
            score *= config.get("weight", 1.0)

            # 归一化置信度（基准分母=2：1关键词+1正则 = 0.75 可达阈值）
            confidence = min(score / 2.0, 1.0)
            min_conf = config.get("min_confidence", MIN_CONFIDENCE)

            if confidence >= min_conf:
                if best is None or confidence > best.confidence:
                    best = IntentResult(
                        intent=intent,
                        confidence=confidence,
                        matched_keywords=matched_kw,
                        matched_patterns=matched_pat,
                    )

        return best or IntentResult(intent="UNKNOWN", confidence=0.0)
