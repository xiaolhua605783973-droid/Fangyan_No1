"""
rule_optimizer 单元测试
"""
import json
import shutil
import tempfile
from pathlib import Path

import yaml
import pytest

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.rule_optimizer import extract_candidates, apply_candidates, backup_rules, restore_rules


# ---------------------------------------------------------------------------
# 夹具
# ---------------------------------------------------------------------------

@pytest.fixture()
def tmp_rules(tmp_path: Path) -> Path:
    """创建一份临时 intent_rules.yaml，用于测试（不污染真实规则文件）"""
    rules = {
        "CALL_NURSE": {
            "keywords": ["护士", "医生"],
            "patterns": [".*护士.*"],
            "weight": 1.0,
            "min_confidence": 0.6,
        },
        "EMERGENCY": {
            "keywords": ["救命", "摔倒"],
            "patterns": [".*救命.*"],
            "weight": 1.2,
            "min_confidence": 0.5,
        },
    }
    rules_file = tmp_path / "intent_rules.yaml"
    with open(rules_file, "w", encoding="utf-8") as f:
        yaml.dump(rules, f, allow_unicode=True)
    return rules_file


# ---------------------------------------------------------------------------
# extract_candidates 测试
# ---------------------------------------------------------------------------

class TestExtractCandidates:
    def test_returns_empty_when_no_errors(self, tmp_rules: Path) -> None:
        candidates = extract_candidates([], tmp_rules, min_freq=1)
        assert candidates == []

    def test_extracts_high_freq_keyword(self, tmp_rules: Path) -> None:
        # "大白褂" 在 CALL_NURSE 的 3 条错误样本中均出现
        errors = [
            {"text": "大白褂快来", "ground_truth": "CALL_NURSE", "predicted": "UNKNOWN"},
            {"text": "大白褂帮帮我", "ground_truth": "CALL_NURSE", "predicted": "UNKNOWN"},
            {"text": "我要找大白褂", "ground_truth": "CALL_NURSE", "predicted": "UNKNOWN"},
        ]
        candidates = extract_candidates(errors, tmp_rules, min_freq=3)
        kws = [c.keyword for c in candidates]
        assert "大白褂" in kws

    def test_skips_existing_keywords(self, tmp_rules: Path) -> None:
        # "护士" 已在规则中，不应出现在候选词里
        errors = [
            {"text": "护士啊快来", "ground_truth": "CALL_NURSE", "predicted": "UNKNOWN"},
            {"text": "护士帮帮我", "ground_truth": "CALL_NURSE", "predicted": "UNKNOWN"},
            {"text": "在找护士", "ground_truth": "CALL_NURSE", "predicted": "UNKNOWN"},
        ]
        candidates = extract_candidates(errors, tmp_rules, min_freq=3)
        existing = [c.keyword for c in candidates if c.keyword == "护士"]
        assert existing == []

    def test_min_freq_filter(self, tmp_rules: Path) -> None:
        # "小护工" 只出现一次，min_freq=3 时不应被提取
        errors = [
            {"text": "小护工来一下", "ground_truth": "CALL_NURSE", "predicted": "UNKNOWN"},
            {"text": "帮我喊护士", "ground_truth": "CALL_NURSE", "predicted": "UNKNOWN"},
        ]
        candidates = extract_candidates(errors, tmp_rules, min_freq=3)
        kws = [c.keyword for c in candidates]
        assert "小护工" not in kws

    def test_skips_unknown_intent(self, tmp_rules: Path) -> None:
        errors = [
            {"text": "帮帮我", "ground_truth": "UNKNOWN", "predicted": "CALL_NURSE"},
        ]
        candidates = extract_candidates(errors, tmp_rules, min_freq=1)
        intents = [c.intent for c in candidates]
        assert "UNKNOWN" not in intents


# ---------------------------------------------------------------------------
# apply_candidates + backup/restore 测试
# ---------------------------------------------------------------------------

class TestApplyCandidates:
    def test_adds_new_keywords(self, tmp_rules: Path) -> None:
        from core.rule_optimizer import Candidate
        candidates = [
            Candidate(keyword="呼叫护工", intent="CALL_NURSE", freq=4),
        ]
        added = apply_candidates(candidates, tmp_rules)
        assert added == 1

        with open(tmp_rules, encoding="utf-8") as f:
            rules = yaml.safe_load(f)
        assert "呼叫护工" in rules["CALL_NURSE"]["keywords"]

    def test_returns_zero_when_empty(self, tmp_rules: Path) -> None:
        added = apply_candidates([], tmp_rules)
        assert added == 0

    def test_backup_and_restore(self, tmp_rules: Path) -> None:
        original_content = tmp_rules.read_text(encoding="utf-8")
        backup_path = backup_rules(tmp_rules)
        assert backup_path.exists()

        # 修改原文件
        tmp_rules.write_text("modified: true", encoding="utf-8")
        assert tmp_rules.read_text(encoding="utf-8") == "modified: true"

        # 恢复
        restore_rules(backup_path, tmp_rules)
        assert tmp_rules.read_text(encoding="utf-8") == original_content
