#!/usr/bin/env python3
"""
自动训练流水线 (Auto Training Pipeline)

工作流程（每30分钟执行一次，或单次运行）：
  1. 扫描 data/collected/labels.jsonl 中的真实语料
  2. 运行文本意图评估，计算当前准确率
  3. 准确率 >= 目标阈值 (默认 90%) → 记录指标，本轮结束
  4. 准确率 < 目标阈值 → 分析错误样本，提取高频候选关键词
  5. 候选词出现次数 >= MIN_FREQ（默认 3）才自动合并到 intent_rules.yaml
  6. 合并后重新评估：若准确率提升则保留；否则自动回滚规则文件
  7. 将每轮训练指标写入 data/metrics/（JSON Lines 文件）

运行方式：
  # 单次执行
  python scripts/auto_train.py

  # 守护进程模式（每30分钟执行一次）
  python scripts/auto_train.py --daemon --interval 30

  # 自定义参数
  python scripts/auto_train.py \\
      --data data/collected/labels.jsonl \\
      --rules config/intent_rules.yaml \\
      --target-accuracy 0.90 \\
      --min-freq 3

注意：需在 fangyan_mvp/ 目录下运行
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import yaml

# 确保能 import 项目模块
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.intent_engine import RuleBasedIntentEngine
from core.text_normalizer import ShaoxingDialectNormalizer
from core.risk_control import RiskController
from core.rule_optimizer import extract_candidates, apply_candidates, backup_rules, restore_rules
from core.logger import get_logger

logger = get_logger(__name__)

METRICS_DIR = Path("data/metrics")


# ---------------------------------------------------------------------------
# 核心评估函数（返回数据而非打印）
# ---------------------------------------------------------------------------

def _run_evaluate(labels_file: Path, rules_path: Path) -> tuple[float, list[dict]]:
    """
    对 labels_file 中的文本样本运行意图评估。

    返回：
        (accuracy, errors_list)
        - accuracy:    意图准确率（0.0-1.0）
        - errors_list: 错误样本列表，每条含 text/ground_truth/predicted/confidence
    """
    normalizer = ShaoxingDialectNormalizer("config/dialect_dict.json")
    # enable_watch=False，因为我们在循环中频繁重建实例
    intent_engine = RuleBasedIntentEngine(str(rules_path), enable_watch=False)
    risk_controller = RiskController("config/emergency_keywords.json")

    total = correct = 0
    errors: list[dict] = []

    with open(labels_file, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                continue

            raw_text = data.get("text", "")
            ground_intent = data.get("intent", "")
            if not raw_text or not ground_intent:
                continue

            normalized = normalizer.normalize(raw_text)
            result = intent_engine.recognize(normalized)

            total += 1
            if result.intent == ground_intent:
                correct += 1
            else:
                errors.append({
                    "text": raw_text,
                    "ground_truth": ground_intent,
                    "predicted": result.intent,
                    "confidence": round(result.confidence, 4),
                })

    accuracy = correct / total if total > 0 else 0.0
    return accuracy, errors


# ---------------------------------------------------------------------------
# 指标持久化
# ---------------------------------------------------------------------------

def _save_metrics(
    run_ts: str,
    labels_file: Path,
    before_acc: float,
    after_acc: float | None,
    added_kws: int,
    rolled_back: bool,
    total_samples: int,
) -> None:
    """将本轮训练指标追加写入 data/metrics/train_metrics.jsonl"""
    METRICS_DIR.mkdir(parents=True, exist_ok=True)
    record = {
        "run_at": run_ts,
        "labels_file": str(labels_file),
        "total_samples": total_samples,
        "before_accuracy": round(before_acc, 4),
        "after_accuracy": round(after_acc, 4) if after_acc is not None else None,
        "keywords_added": added_kws,
        "rolled_back": rolled_back,
        "improved": (after_acc > before_acc) if after_acc is not None else False,
    }
    metrics_file = METRICS_DIR / "train_metrics.jsonl"
    with open(metrics_file, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
    logger.info("metrics_saved", path=str(metrics_file), **record)


# ---------------------------------------------------------------------------
# 单轮训练主逻辑
# ---------------------------------------------------------------------------

def run_once(
    labels_file: Path,
    rules_path: Path,
    target_accuracy: float,
    min_freq: int,
    dry_run: bool = False,
) -> dict:
    """
    执行一轮评估+优化。

    返回本轮结果摘要 dict。
    """
    run_ts = datetime.now(timezone.utc).isoformat()

    if not labels_file.exists():
        logger.warning("auto_train_labels_not_found", path=str(labels_file))
        return {"status": "skipped", "reason": "labels_file_not_found"}

    # --- Step 1: 基准评估 ---
    before_acc, errors = _run_evaluate(labels_file, rules_path)
    total_samples = sum(
        1 for line in labels_file.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("//")
    )

    print(f"\n[{run_ts}] 本轮评估：准确率 {before_acc:.1%}  样本数 {total_samples}  错误 {len(errors)}")

    if before_acc >= target_accuracy:
        print(f"  ✓ 已达目标 {target_accuracy:.0%}，无需优化")
        _save_metrics(run_ts, labels_file, before_acc, None, 0, False, total_samples)
        return {
            "status": "target_met",
            "accuracy": before_acc,
            "errors": len(errors),
        }

    print(f"  ✗ 未达目标 {target_accuracy:.0%}（差 {target_accuracy - before_acc:.1%}），开始分析错误…")

    # --- Step 2: 提取候选关键词 ---
    candidates = extract_candidates(errors, rules_path, min_freq=min_freq)
    if not candidates:
        print(f"  ⚠ 未找到满足条件（频率≥{min_freq}）的候选关键词，等待更多语料")
        _save_metrics(run_ts, labels_file, before_acc, None, 0, False, total_samples)
        return {
            "status": "no_candidates",
            "accuracy": before_acc,
            "errors": len(errors),
        }

    print(f"  → 候选关键词 {len(candidates)} 个：")
    by_intent: dict[str, list[str]] = defaultdict(list)
    for cand in candidates:
        by_intent[cand.intent].append(f"{cand.keyword}({cand.freq}次)")
    for intent, kws in by_intent.items():
        print(f"       {intent}: {', '.join(kws)}")

    if dry_run:
        print("  [dry-run] 跳过实际写入")
        return {"status": "dry_run", "candidates": len(candidates)}

    # --- Step 3: 备份规则 + 应用候选词 ---
    backup_path = backup_rules(rules_path)
    added = apply_candidates(candidates, rules_path)

    if added == 0:
        print("  ⚠ 所有候选词已存在于规则文件，无新增")
        _save_metrics(run_ts, labels_file, before_acc, None, 0, False, total_samples)
        return {"status": "no_new_keywords", "accuracy": before_acc}

    print(f"  → 已新增 {added} 个关键词到 {rules_path}")

    # --- Step 4: 重新评估 ---
    after_acc, after_errors = _run_evaluate(labels_file, rules_path)
    print(f"  → 更新后准确率: {before_acc:.1%} → {after_acc:.1%}")

    rolled_back = False
    if after_acc <= before_acc:
        # 规则更新没有带来改善，回滚
        restore_rules(backup_path, rules_path)
        rolled_back = True
        print(f"  ✗ 准确率未提升（{after_acc:.1%} <= {before_acc:.1%}），已回滚规则文件")
        final_acc = before_acc
    else:
        final_acc = after_acc
        if after_acc >= target_accuracy:
            print(f"  ✓ 准确率已达目标 {target_accuracy:.0%} !")
        else:
            print(f"  → 准确率改善 +{(after_acc - before_acc):.1%}，继续收集更多语料")

    _save_metrics(
        run_ts, labels_file, before_acc,
        after_acc if not rolled_back else before_acc,
        added if not rolled_back else 0,
        rolled_back, total_samples,
    )

    return {
        "status": "rolled_back" if rolled_back else "improved",
        "before_accuracy": before_acc,
        "after_accuracy": final_acc,
        "keywords_added": added if not rolled_back else 0,
    }


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="自动训练流水线：根据收集语料自动优化意图规则"
    )
    parser.add_argument(
        "--data",
        default="data/collected/labels.jsonl",
        help="标注数据文件路径（默认：data/collected/labels.jsonl）",
    )
    parser.add_argument(
        "--rules",
        default="config/intent_rules.yaml",
        help="意图规则文件路径（默认：config/intent_rules.yaml）",
    )
    parser.add_argument(
        "--target-accuracy",
        type=float,
        default=0.90,
        help="目标准确率阈值（默认：0.90）",
    )
    parser.add_argument(
        "--min-freq",
        type=int,
        default=3,
        help="候选关键词最小出现次数（默认：3）",
    )
    parser.add_argument(
        "--daemon",
        action="store_true",
        help="守护进程模式：周期性执行",
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=30,
        help="守护进程模式下每轮间隔时间（分钟，默认：30）",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="试运行：仅显示候选词，不修改规则文件",
    )
    args = parser.parse_args()

    labels_file = Path(args.data)
    rules_path = Path(args.rules)

    print("=" * 60)
    print("  自动训练流水线启动")
    print(f"  语料文件:  {labels_file}")
    print(f"  规则文件:  {rules_path}")
    print(f"  目标准确率: {args.target_accuracy:.0%}")
    print(f"  最小词频:  {args.min_freq}")
    if args.daemon:
        print(f"  运行模式:  守护进程（每 {args.interval} 分钟）")
    else:
        print(f"  运行模式:  单次执行")
    print("=" * 60)

    if args.daemon:
        interval_secs = args.interval * 60
        print(f"\n守护进程已启动，按 Ctrl+C 退出\n")
        while True:
            try:
                run_once(labels_file, rules_path, args.target_accuracy, args.min_freq, args.dry_run)
            except Exception as exc:
                logger.error("auto_train_error", error=str(exc), exc_info=True)
                print(f"\n[错误] {exc}，将在 {args.interval} 分钟后重试")
            print(f"\n下次执行时间: {datetime.now(timezone.utc).isoformat()} + {args.interval}min\n")
            time.sleep(interval_secs)
    else:
        result = run_once(
            labels_file, rules_path,
            args.target_accuracy, args.min_freq, args.dry_run,
        )
        print(f"\n执行完成: {result}")


if __name__ == "__main__":
    main()
