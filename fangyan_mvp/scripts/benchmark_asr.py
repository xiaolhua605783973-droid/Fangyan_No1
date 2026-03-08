"""
scripts/benchmark_asr.py
Month 3 — Whisper CPU 基准测试脚本

对比阿里云ASR、Whisper-medium INT8、Whisper-small INT8 三个方案，输出基准报告。

用法示例:
    python scripts/benchmark_asr.py --mock --labels data/labels.jsonl
    python scripts/benchmark_asr.py --mock --output reports/asr_benchmark.json
"""

import argparse
import asyncio
import json
import random
import sys
from pathlib import Path
from typing import Optional

from pydantic import BaseModel

# 将 fangyan_mvp/ 加入 sys.path（支持从项目根目录或 scripts/ 直接运行）
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import logging

import structlog

from core.logger import get_logger


def _configure_script_logging() -> None:
    """为脚本配置兼容 PrintLoggerFactory 的 structlog（不使用 add_logger_name）"""
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.dev.ConsoleRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
        logger_factory=structlog.PrintLoggerFactory(sys.stderr),
    )


logger = get_logger(__name__)


# ─── Pydantic v2 Schemas ───────────────────────────────────────────────────────

class LabelSample(BaseModel):
    """标注数据样本（兼容 labels.jsonl 中的扩展字段）"""

    id: Optional[str] = None
    audio_file: Optional[str] = None
    text: str
    intent: str
    risk_level: str
    synthesized: Optional[bool] = None
    offline: Optional[bool] = None
    created_at: Optional[str] = None


class ProviderStats(BaseModel):
    """单个 ASR 提供商的测试统计"""

    provider: str
    sample_count: int
    avg_wer: float
    p50_latency_ms: float
    p95_latency_ms: float
    monthly_cost_note: str


class BenchmarkReport(BaseModel):
    """完整基准测试报告"""

    sample_count: int
    providers: list[ProviderStats]
    recommendation: str
    mock_mode: bool


# ─── 常量 ──────────────────────────────────────────────────────────────────────

# mock 模式下各提供商的延迟范围 (ms)
MOCK_LATENCY_RANGES: dict[str, tuple[int, int]] = {
    "aliyun":         (500, 1500),
    "whisper-medium": (1000, 3000),
    "whisper-small":  (500, 2000),
}

ALIYUN_PRICE_PER_HOUR_CNY: float = 3.5   # 阿里云实时语音识别单价（元/小时）
AVG_AUDIO_DURATION_SEC: float = 3.0      # 假设平均每条音频时长（秒）
CALLS_PER_MONTH: int = 10_000            # 月请求量基准
WHISPER_SERVER_COST_CNY: int = 300       # 自托管 Whisper 月固定服务器成本（元）


# ─── 数据加载 ──────────────────────────────────────────────────────────────────

def load_labels(labels_path: Path) -> list[LabelSample]:
    """从 JSONL 文件加载标注样本"""
    samples: list[LabelSample] = []
    with labels_path.open(encoding="utf-8") as fh:
        for lineno, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
                samples.append(LabelSample(**data))
            except Exception as exc:
                logger.warning(
                    "label_parse_error", lineno=lineno, error=str(exc)
                )
    logger.info("labels_loaded", count=len(samples), path=str(labels_path))
    return samples


# ─── Mock 测试逻辑 ─────────────────────────────────────────────────────────────

async def mock_benchmark_provider(
    provider: str,
    samples: list[LabelSample],
) -> tuple[list[float], list[float]]:
    """
    模拟单个 ASR 提供商的测试。
    每条样本给予随机 WER（0-0.3）和随机延迟（按提供商范围）。
    实际 sleep 缩放为延迟值的 5%，避免测试过慢。

    Returns:
        (wer_list, latency_ms_list)
    """
    lo, hi = MOCK_LATENCY_RANGES[provider]
    wer_list: list[float] = []
    latency_list: list[float] = []

    for _sample in samples:
        # 模拟异步 I/O（极短 sleep 仅保持协程切换语义，不真实等待延迟）
        await asyncio.sleep(0)

        wer = round(random.uniform(0.0, 0.30), 4)
        latency_ms = random.uniform(lo, hi)
        wer_list.append(wer)
        latency_list.append(latency_ms)

    logger.info(
        "mock_provider_done", provider=provider, samples=len(samples)
    )
    return wer_list, latency_list


# ─── 真实测试预留接口 ──────────────────────────────────────────────────────────

async def real_benchmark_provider(
    provider: str,
    samples: list[LabelSample],
    whisper_model_size: str,
) -> tuple[list[float], list[float]]:
    """
    真实调用 ASR 适配器进行基准测试（Month 4 完整实现）。
    当前仅提供骨架，调用时抛出 NotImplementedError。
    """
    raise NotImplementedError(
        f"真实 ASR 基准测试暂未实现（提供商: {provider}）。"
        "请添加 --mock 参数使用 mock 模式。"
    )


# ─── 统计计算 ──────────────────────────────────────────────────────────────────

def compute_stats(
    provider: str,
    wer_list: list[float],
    latency_list: list[float],
) -> ProviderStats:
    """计算单个提供商的 WER、P50/P95 延迟及月成本估算"""
    n = len(latency_list)
    sorted_lat = sorted(latency_list)

    p50 = sorted_lat[int(n * 0.50)]
    p95 = sorted_lat[min(int(n * 0.95), n - 1)]
    avg_wer = sum(wer_list) / len(wer_list) if wer_list else 0.0

    # 月成本估算
    if provider == "aliyun":
        total_hours = (CALLS_PER_MONTH * AVG_AUDIO_DURATION_SEC) / 3600
        cost_cny = total_hours * ALIYUN_PRICE_PER_HOUR_CNY
        cost_note = f"{cost_cny:.0f}元"
    else:
        cost_note = f"{WHISPER_SERVER_COST_CNY}元(服务器)"

    return ProviderStats(
        provider=provider,
        sample_count=n,
        avg_wer=round(avg_wer, 4),
        p50_latency_ms=round(p50, 1),
        p95_latency_ms=round(p95, 1),
        monthly_cost_note=cost_note,
    )


# ─── 决策建议生成 ──────────────────────────────────────────────────────────────

def generate_recommendation(stats_list: list[ProviderStats]) -> str:
    """基于测试数据生成 Year 2 ASR 路线选择建议"""
    by_name = {s.provider: s for s in stats_list}
    aliyun = by_name.get("aliyun")
    medium = by_name.get("whisper-medium")
    small = by_name.get("whisper-small")

    lines: list[str] = []

    if aliyun and small:
        wer_diff = aliyun.avg_wer - small.avg_wer
        if abs(wer_diff) < 0.05:
            lines.append(
                f"Whisper-small INT8 平均WER（{small.avg_wer:.2f}）与"
                f"阿里云ASR（{aliyun.avg_wer:.2f}）相差不足5%，"
                f"但月成本仅需 {small.monthly_cost_note}（vs. 阿里云 {aliyun.monthly_cost_note}），"
                "建议 Year 2 迁移至自托管 Whisper-small，降低 API 依赖与成本。"
            )
        elif small.avg_wer < aliyun.avg_wer:
            lines.append(
                f"Whisper-small INT8 平均WER（{small.avg_wer:.2f}）优于"
                f"阿里云ASR（{aliyun.avg_wer:.2f}），且月成本更低，"
                "强烈推荐 Year 2 切换至 Whisper-small 自托管方案。"
            )
        else:
            lines.append(
                f"阿里云ASR 平均WER（{aliyun.avg_wer:.2f}）优于"
                f"Whisper-small（{small.avg_wer:.2f}），"
                "建议继续使用阿里云API，同时收集真实方言音频以微调 Whisper 模型。"
            )

    if medium and small:
        lat_diff = medium.p50_latency_ms - small.p50_latency_ms
        if lat_diff > 200:
            lines.append(
                f"Whisper-small P50延迟（{small.p50_latency_ms:.0f}ms）比"
                f"medium（{medium.p50_latency_ms:.0f}ms）快约 {lat_diff:.0f}ms，"
                "实时交互场景优先选择 small 模型。"
            )

    if not lines:
        lines.append(
            "当前测试基于 mock 数据，建议收集真实方言音频后重新运行基准测试以获取准确决策依据。"
        )
    else:
        lines.append(
            "注意：当前结果为 mock 模式，生产决策需基于真实方言音频的实测数据。"
        )

    return " ".join(lines)


# ─── 报告打印 ──────────────────────────────────────────────────────────────────

def print_report(report: BenchmarkReport) -> None:
    """格式化打印基准报告至 stdout"""
    col_provider = 20
    col_wer = 12
    col_p50 = 13
    col_p95 = 13

    header = (
        f"{'提供商':<{col_provider}}"
        f"{'平均WER':<{col_wer}}"
        f"{'P50延迟(ms)':<{col_p50}}"
        f"{'P95延迟(ms)':<{col_p95}}"
        f"月成本估算(1万次)"
    )
    divider = (
        f"{'-' * col_provider}  "
        f"{'-' * 10}  "
        f"{'-' * 11}  "
        f"{'-' * 11}  "
        f"{'-' * 16}"
    )

    out = sys.stdout
    out.write("\n=== ASR 基准测试报告 ===\n")
    out.write(f"测试样本数: {report.sample_count}\n")
    if report.mock_mode:
        out.write("（mock 模式 — 数据为模拟值，仅供流程验证）\n")
    out.write("\n")
    out.write(header + "\n")
    out.write(divider + "\n")

    for p in report.providers:
        out.write(
            f"{p.provider:<{col_provider}}"
            f"{p.avg_wer:<{col_wer}.2f}"
            f"{p.p50_latency_ms:<{col_p50}.0f}"
            f"{p.p95_latency_ms:<{col_p95}.0f}"
            f"{p.monthly_cost_note}\n"
        )

    out.write("\n=== 决策建议 ===\n")
    out.write(report.recommendation + "\n\n")
    out.flush()


# ─── 主流程 ────────────────────────────────────────────────────────────────────

async def run_benchmark(
    labels_path: Path,
    mock: bool,
    whisper_model_size: str,
    output_path: Optional[Path],
) -> BenchmarkReport:
    """执行全部提供商的基准测试并返回报告"""
    samples = load_labels(labels_path)
    if not samples:
        logger.error("no_samples_found", path=str(labels_path))
        raise SystemExit(1)

    providers = ["aliyun", "whisper-medium", "whisper-small"]
    stats_list: list[ProviderStats] = []

    for provider in providers:
        logger.info("benchmarking_provider", provider=provider, mock=mock)
        if mock:
            wer_list, latency_list = await mock_benchmark_provider(
                provider, samples
            )
        else:
            wer_list, latency_list = await real_benchmark_provider(
                provider, samples, whisper_model_size
            )
        stats_list.append(compute_stats(provider, wer_list, latency_list))

    recommendation = generate_recommendation(stats_list)
    report = BenchmarkReport(
        sample_count=len(samples),
        providers=stats_list,
        recommendation=recommendation,
        mock_mode=mock,
    )

    if output_path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            report.model_dump_json(indent=2), encoding="utf-8"
        )
        logger.info("report_saved", path=str(output_path))

    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="ASR 基准测试：阿里云 vs Whisper-medium INT8 vs Whisper-small INT8"
    )
    parser.add_argument(
        "--labels",
        default="data/labels.jsonl",
        help="标注文件路径（默认: data/labels.jsonl）",
    )
    parser.add_argument(
        "--mock",
        action="store_true",
        help="mock 模式，不调用真实 API（适用于 CI 环境）",
    )
    parser.add_argument(
        "--whisper-model",
        default="medium",
        choices=["small", "medium", "large"],
        dest="whisper_model",
        help="Whisper 模型大小（默认: medium）",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="输出 JSON 报告路径（可选）",
    )
    return parser.parse_args()


def main() -> None:
    _configure_script_logging()
    args = parse_args()

    labels_path = Path(args.labels)
    output_path = Path(args.output) if args.output else None

    if not labels_path.exists():
        logger.error("labels_file_not_found", path=str(labels_path))
        raise SystemExit(f"标注文件不存在: {labels_path}")

    report = asyncio.run(
        run_benchmark(
            labels_path=labels_path,
            mock=args.mock,
            whisper_model_size=args.whisper_model,
            output_path=output_path,
        )
    )
    print_report(report)


if __name__ == "__main__":
    main()
