#!/usr/bin/env python3
"""
意图识别准确率评估脚本。

使用方式：
    python scripts/evaluate.py data/labels.jsonl
    python scripts/evaluate.py results.json --has-ground-truth

labels.jsonl 格式（每行一个 JSON）：
    {"audio_file": "xxx.wav", "text": "...", "intent": "CALL_NURSE", "risk_level": "LOW"}
"""
import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.intent_engine import RuleBasedIntentEngine
from core.text_normalizer import ShaoxingDialectNormalizer
from core.risk_control import RiskController


def evaluate_text_pipeline(labels_file: str):
    normalizer = ShaoxingDialectNormalizer("config/dialect_dict.json")
    intent_engine = RuleBasedIntentEngine("config/intent_rules.yaml")
    risk_controller = RiskController("config/emergency_keywords.json")

    total = correct_intent = correct_risk = 0
    confusion: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    errors = []

    with open(labels_file, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            data = json.loads(line)

            raw_text = data.get("text", "")
            ground_intent = data.get("intent", "")
            ground_risk = data.get("risk_level", "")

            normalized = normalizer.normalize(raw_text)
            intent_result = intent_engine.recognize(normalized)
            risk_level, _ = risk_controller.assess_risk(
                normalized, intent_result.intent, intent_result.confidence
            )

            total += 1
            confusion[ground_intent][intent_result.intent] += 1

            if intent_result.intent == ground_intent:
                correct_intent += 1
            else:
                errors.append({
                    "text": raw_text,
                    "ground_truth": ground_intent,
                    "predicted": intent_result.intent,
                    "confidence": round(intent_result.confidence, 3),
                })

            if risk_level == ground_risk:
                correct_risk += 1

    if total == 0:
        print("没有找到标注数据")
        return

    intent_acc = correct_intent / total
    risk_acc = correct_risk / total

    print(f"\n=== 评估结果（共 {total} 条）===")
    print(f"意图准确率: {intent_acc:.1%}  {'[PASS]' if intent_acc >= 0.90 else '[FAIL]'} (目标 >=90%)")
    print(f"风险准确率: {risk_acc:.1%}")

    print(f"\n=== 混淆矩阵 ===")
    intents = ["CALL_NURSE", "CALL_FAMILY", "HEALTH_ALERT", "EMERGENCY", "UNKNOWN"]
    header = f"{'真实\\预测':<15}" + "".join(f"{i:<15}" for i in intents)
    print(header)
    for gt in intents:
        row = f"{gt:<15}" + "".join(f"{confusion[gt][pred]:<15}" for pred in intents)
        print(row)

    if errors:
        print(f"\n=== 错误样例（前10条）===")
        for e in errors[:10]:
            print(f"  文本: {e['text']}")
            print(f"  真实: {e['ground_truth']}  预测: {e['predicted']}  置信度: {e['confidence']}")
            print()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("labels_file", help="标注数据文件路径（JSON Lines格式）")
    args = parser.parse_args()
    evaluate_text_pipeline(args.labels_file)
