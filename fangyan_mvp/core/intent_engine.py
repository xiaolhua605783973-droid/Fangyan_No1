import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml

from core.logger import get_logger

try:
    from watchdog.observers import Observer
    from watchdog.events import FileSystemEventHandler
    _WATCHDOG_AVAILABLE = True
except ImportError:
    _WATCHDOG_AVAILABLE = False

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
    规则配置来自 config/intent_rules.yaml，支持热更新（可选 watchdog）。
    """

    def __init__(self, rules_path: str = "config/intent_rules.yaml", enable_watch: bool = False):
        self._rules_path = Path(rules_path)
        self._rules: dict = {}
        self._observer: Optional[object] = None
        self._load_rules()
        if enable_watch:
            self._start_watch()

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
        logger.info("intent_rules_hot_reloaded")

    def _start_watch(self) -> None:
        """启动 watchdog 文件监听，config/intent_rules.yaml 修改时自动热更新"""
        if not _WATCHDOG_AVAILABLE:
            logger.warning("watchdog_not_installed", hint="pip install watchdog>=4.0.0")
            return

        rules_file = self._rules_path.resolve()
        engine_ref = self  # 闭包引用，避免循环引用

        class _RulesFileHandler(FileSystemEventHandler):
            def on_modified(self, event) -> None:  # type: ignore[override]
                if Path(event.src_path).resolve() == rules_file:
                    engine_ref.reload_rules()

        observer = Observer()
        observer.schedule(_RulesFileHandler(), str(rules_file.parent), recursive=False)
        observer.start()
        self._observer = observer
        logger.info("intent_rules_watch_started", path=str(rules_file))

    def stop_watch(self) -> None:
        """停止 watchdog 文件监听（测试结束或服务关闭时调用）"""
        if self._observer is not None:
            self._observer.stop()  # type: ignore[union-attr]
            self._observer.join()  # type: ignore[union-attr]
            self._observer = None
            logger.info("intent_rules_watch_stopped")

    # 风险优先级（值越小风险越高），置信度相同时高风险意图优先
    _RISK_PRIORITY: dict[str, int] = {
        "EMERGENCY": 0,
        "HEALTH_ALERT": 1,
        "CALL_NURSE": 2,
        "CALL_FAMILY": 3,
    }

    def _is_better(self, candidate: "IntentResult", current_best: "IntentResult") -> bool:
        """比较两个识别结果：置信度更高则优先；置信度相同时，风险等级更高（值更小）则优先。"""
        if candidate.confidence > current_best.confidence:
            return True
        if candidate.confidence == current_best.confidence:
            cand_prio = self._RISK_PRIORITY.get(candidate.intent, 99)
            best_prio = self._RISK_PRIORITY.get(current_best.intent, 99)
            return cand_prio < best_prio
        return False

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

            # 归一化置信度（基准分母=1.5：1关键词=0.67 可达0.6阈值，2关键词=1.0满分）
            confidence = min(score / 1.5, 1.0)
            min_conf = config.get("min_confidence", MIN_CONFIDENCE)

            if confidence >= min_conf:
                candidate = IntentResult(
                    intent=intent,
                    confidence=confidence,
                    matched_keywords=matched_kw,
                    matched_patterns=matched_pat,
                )
                if best is None or self._is_better(candidate, best):
                    best = candidate

        return best or IntentResult(intent="UNKNOWN", confidence=0.0)
