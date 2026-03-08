"""
规则优化器 (Rule Optimizer)

功能：
  - 分析意图识别错误样本，提取高频候选关键词
  - 安全更新 config/intent_rules.yaml（自动备份 + 出错回滚）
  - 支持只读的候选词建议模式（不修改文件）

依赖：仅标准库 + PyYAML（项目已有）
"""
from __future__ import annotations

import re
import shutil
from collections import Counter, defaultdict
from pathlib import Path
from typing import NamedTuple

import yaml

from core.logger import get_logger

logger = get_logger(__name__)

# 停用词：单字、纯数字、标点等，不作为候选关键词
_STOPWORDS: set[str] = {
    "啊", "哦", "嗯", "呢", "吧", "嘛", "呀", "哇", "哎", "哟",
    "的", "了", "在", "是", "有", "我", "你", "他", "她", "它",
    "要", "去", "来", "说", "看", "到", "把", "被", "让", "给",
    "一", "二", "三", "四", "五", "六", "七", "八", "九", "十",
}
_MIN_GRAM_LEN = 2   # 最短候选词长度（字符数）
_MAX_GRAM_LEN = 6   # 最长候选词长度


class Candidate(NamedTuple):
    keyword: str
    intent: str
    freq: int       # 在该意图的错误样本中出现次数


def _extract_ngrams(text: str) -> list[str]:
    """从中文短文本中提取所有长度为 2-6 的子串作为候选词"""
    # 过滤掉非中文/字母字符
    cleaned = re.sub(r"[^\u4e00-\u9fffA-Za-z]", "", text)
    grams: list[str] = []
    for length in range(_MIN_GRAM_LEN, _MAX_GRAM_LEN + 1):
        for i in range(len(cleaned) - length + 1):
            gram = cleaned[i : i + length]
            # 排除全停用词（包含单字停用词的短语本身不排除，只过滤纯停用词组合）
            if gram and gram not in _STOPWORDS:
                grams.append(gram)
    return grams


def _get_existing_keywords(rules: dict) -> set[str]:
    """提取规则文件中所有已有关键词（用于去重）"""
    existing: set[str] = set()
    for config in rules.values():
        for kw in config.get("keywords", []):
            existing.add(str(kw))
    return existing


def extract_candidates(
    errors: list[dict],
    rules_path: Path,
    min_freq: int = 3,
) -> list[Candidate]:
    """
    从错误样本中提取候选新关键词。

    参数：
        errors:    错误样本列表，每条格式 {"text": ..., "ground_truth": ..., "predicted": ..., ...}
        rules_path: intent_rules.yaml 路径
        min_freq:  候选词在同一意图错误样本中最少出现次数

    返回：
        按频次降序排列的 Candidate 列表
    """
    with open(rules_path, encoding="utf-8") as f:
        rules: dict = yaml.safe_load(f) or {}

    existing_kws = _get_existing_keywords(rules)

    # 按意图分组收集错误文本
    intent_errors: dict[str, list[str]] = defaultdict(list)
    for err in errors:
        ground = err.get("ground_truth", "")
        text = err.get("text", "")
        if ground and ground != "UNKNOWN" and text:
            intent_errors[ground].append(text)

    candidates: list[Candidate] = []

    for intent, texts in intent_errors.items():
        if intent not in rules:
            logger.warning("rule_optimizer_unknown_intent", intent=intent)
            continue

        # 统计每个 n-gram 出现在多少条不同的错误文本里
        gram_counter: Counter = Counter()
        for text in texts:
            # 每条文本中的 gram 只计一次（避免同一条文本多个出现被夸大）
            unique_grams = set(_extract_ngrams(text))
            gram_counter.update(unique_grams)

        for gram, freq in gram_counter.items():
            if freq >= min_freq and gram not in existing_kws:
                candidates.append(Candidate(keyword=gram, intent=intent, freq=freq))

    # 按频次降序，按意图字母序次排
    candidates.sort(key=lambda c: (-c.freq, c.intent, c.keyword))

    logger.info(
        "rule_optimizer_candidates_extracted",
        total=len(candidates),
        by_intent={i: len([c for c in candidates if c.intent == i]) for i in intent_errors},
    )
    return candidates


def backup_rules(rules_path: Path) -> Path:
    """备份规则文件，返回备份文件路径"""
    backup_path = rules_path.with_suffix(".yaml.bak")
    shutil.copy2(rules_path, backup_path)
    logger.info("rules_backed_up", backup=str(backup_path))
    return backup_path


def restore_rules(backup_path: Path, rules_path: Path) -> None:
    """从备份恢复规则文件"""
    shutil.copy2(backup_path, rules_path)
    logger.info("rules_restored_from_backup", backup=str(backup_path))


def apply_candidates(
    candidates: list[Candidate],
    rules_path: Path,
) -> int:
    """
    将候选关键词写入 intent_rules.yaml。

    返回：实际新增的关键词数量
    """
    if not candidates:
        return 0

    with open(rules_path, encoding="utf-8") as f:
        rules: dict = yaml.safe_load(f) or {}

    existing_kws = _get_existing_keywords(rules)
    added = 0

    for cand in candidates:
        intent = cand.intent
        if intent not in rules:
            continue
        if cand.keyword in existing_kws:
            continue
        rules[intent].setdefault("keywords", []).append(cand.keyword)
        existing_kws.add(cand.keyword)
        added += 1
        logger.info(
            "rule_optimizer_keyword_added",
            keyword=cand.keyword,
            intent=intent,
            freq=cand.freq,
        )

    if added > 0:
        with open(rules_path, "w", encoding="utf-8") as f:
            yaml.dump(rules, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
        logger.info("rules_file_updated", added=added, path=str(rules_path))

    return added
