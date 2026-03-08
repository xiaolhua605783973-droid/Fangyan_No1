import pytest

from core.intent_engine import RuleBasedIntentEngine
from core.risk_control import RiskController
from core.text_normalizer import ShaoxingDialectNormalizer


@pytest.fixture
def normalizer():
    return ShaoxingDialectNormalizer(dict_path="config/dialect_dict.json")


@pytest.fixture
def intent_engine():
    return RuleBasedIntentEngine(rules_path="config/intent_rules.yaml")


@pytest.fixture
def risk_controller():
    return RiskController(keywords_path="config/emergency_keywords.json")


# ── 文本规范化测试 ────────────────────────────────────────────

class TestTextNormalizer:
    def test_dialect_replacement(self, normalizer):
        # 绍兴话 "勿" 应被替换为 "不"
        assert "不" in normalizer.normalize("我勿舒服")

    def test_filler_removal(self, normalizer):
        # 吴语语气助词 哉/伐 应被去除（绍兴话特有）
        result = normalizer.normalize("身体勿好受哉伐")
        assert "哉" not in result
        assert "伐" not in result

    def test_degree_normalization(self, normalizer):
        # 绍兴话 "蛮" 应被替换为 "很"
        result = normalizer.normalize("肚皮蛮痛")
        assert "很" in result

    def test_protect_medical_terms(self, normalizer):
        result = normalizer.normalize("头晕得很")
        assert "头晕" in result


# ── 意图识别测试 ──────────────────────────────────────────────

class TestIntentEngine:
    def test_call_nurse(self, intent_engine):
        result = intent_engine.recognize("帮我叫一下护士")
        assert result.intent == "CALL_NURSE"
        assert result.confidence >= 0.6

    def test_call_family(self, intent_engine):
        result = intent_engine.recognize("给我儿子打电话")
        assert result.intent == "CALL_FAMILY"

    def test_health_alert(self, intent_engine):
        result = intent_engine.recognize("我头晕非常难受")
        assert result.intent == "HEALTH_ALERT"

    def test_emergency(self, intent_engine):
        result = intent_engine.recognize("救命啊快来人")
        assert result.intent == "EMERGENCY"

    def test_unknown_low_confidence(self, intent_engine):
        result = intent_engine.recognize("今天天气怎么样")
        assert result.intent == "UNKNOWN"


# ── 风险控制测试 ──────────────────────────────────────────────

class TestRiskController:
    def test_emergency_keywords_trigger_high(self, risk_controller):
        level, kws = risk_controller.assess_risk("救命啊", "UNKNOWN", 0.8)
        assert level == "HIGH"
        assert len(kws) > 0

    def test_emergency_intent_forces_high(self, risk_controller):
        level, _ = risk_controller.assess_risk("快来", "EMERGENCY", 0.9)
        assert level == "HIGH"

    def test_health_alert_gives_medium(self, risk_controller):
        level, _ = risk_controller.assess_risk("我不舒服", "HEALTH_ALERT", 0.8)
        assert level == "MEDIUM"

    def test_low_confidence_elevates_risk(self, risk_controller):
        level, _ = risk_controller.assess_risk("摔倒了", "UNKNOWN", 0.4)
        assert level in ("MEDIUM", "HIGH")

    def test_call_nurse_is_low(self, risk_controller):
        level, _ = risk_controller.assess_risk("叫护士来", "CALL_NURSE", 0.85)
        assert level == "LOW"

    def test_no_miss_critical(self, risk_controller):
        """关键原则：紧急词必须触发 HIGH，不能漏报"""
        critical_texts = ["救命", "呼吸困难", "心脏不行了", "昏迷了"]
        for text in critical_texts:
            level, _ = risk_controller.assess_risk(text, "UNKNOWN", 0.9)
            assert level == "HIGH", f"'{text}' 应触发 HIGH，实际为 {level}"
