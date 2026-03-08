"""
数据集生成主脚本
生成200条四川方言合成音频 + 对应标注文件（JSON Lines）

用法：
    # 生成200条样本（需要阿里云凭证）
    python data/bootstrap/generate_dataset.py --count 200 --add-noise

    # 离线模式：只生成文本标注，音频用静音占位（不消耗 API）
    python data/bootstrap/generate_dataset.py --count 200 --offline

    # 指定输出目录
    python data/bootstrap/generate_dataset.py --output data/samples --labels data/labels.jsonl

输出：
    data/samples/CALL_NURSE_001.wav  ...  各意图音频文件
    data/labels.jsonl               标注文件，每行一条 JSON
"""
import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path

# 让脚本在 fangyan_mvp/ 根目录下运行时能找到其他模块
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from data.bootstrap.text_generator import TextGenerator
from data.bootstrap.audio_synthesizer import AudioSynthesizer, generate_silent_wav


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="生成四川方言测试数据集")
    parser.add_argument(
        "--count",
        type=int,
        default=200,
        help="总生成条数（默认200，每个意图各50条）",
    )
    parser.add_argument(
        "--output",
        type=str,
        default="data/samples",
        help="音频文件输出目录（默认 data/samples）",
    )
    parser.add_argument(
        "--labels",
        type=str,
        default="data/labels.jsonl",
        help="标注文件路径（默认 data/labels.jsonl）",
    )
    parser.add_argument(
        "--add-noise",
        action="store_true",
        help="叠加背景噪声模拟真实环境",
    )
    parser.add_argument(
        "--offline",
        action="store_true",
        help="离线模式：跳过 TTS API，用静音 WAV 占位（节省 API 成本）",
    )
    parser.add_argument(
        "--voice",
        type=str,
        default="xiaoyun",
        help="阿里云 TTS 音色（默认 xiaoyun）",
    )
    return parser.parse_args()


async def generate(args: argparse.Namespace) -> None:
    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)
    labels_path = Path(args.labels)
    labels_path.parent.mkdir(parents=True, exist_ok=True)

    per_intent = args.count // 4  # 4 个意图均分

    # 初始化文本生成器
    generator = TextGenerator(
        templates_path=str(Path(__file__).parent / "templates.json")
    )

    # 初始化 TTS（在线模式需要凭证）
    synthesizer: AudioSynthesizer | None = None
    if not args.offline:
        access_key = os.environ.get("ALIYUN_ACCESS_KEY", "")
        access_secret = os.environ.get("ALIYUN_ACCESS_SECRET", "")
        if not access_key or not access_secret:
            print(
                "[ERROR] 需要设置环境变量 ALIYUN_ACCESS_KEY 和 ALIYUN_ACCESS_SECRET，"
                "或使用 --offline 模式"
            )
            sys.exit(1)
        synthesizer = AudioSynthesizer(
            access_key=access_key,
            access_secret=access_secret,
            voice=args.voice,
            speech_rate=-200,  # 老年语速
            add_noise=args.add_noise,
        )

    # 统计
    total = 0
    intent_counts: dict[str, int] = {}
    errors = 0

    print(f"\n开始生成数据集（目标：{args.count} 条，每意图 {per_intent} 条）")
    print(f"模式：{'离线（静音占位）' if args.offline else '在线 TTS'}")
    print(f"输出目录：{output_dir.absolute()}")
    print(f"标注文件：{labels_path.absolute()}\n")

    with open(labels_path, "w", encoding="utf-8") as label_file:
        for text, intent, risk_level in generator.iter_all_texts(
            target_per_intent=per_intent
        ):
            intent_counts.setdefault(intent, 0)
            idx = intent_counts[intent] + 1
            audio_filename = f"{intent}_{idx:03d}.wav"
            audio_path = output_dir / audio_filename

            # 生成音频
            try:
                if args.offline or synthesizer is None:
                    # 离线：写入 2-4 秒随机时长静音
                    import random
                    duration_ms = random.randint(2000, 4000)
                    audio_bytes = generate_silent_wav(duration_ms=duration_ms)
                else:
                    audio_bytes = await synthesizer.synthesize(text)
                    # 避免 TTS API 限速（QPS=10）
                    await asyncio.sleep(0.12)

                audio_path.write_bytes(audio_bytes)

            except Exception as e:
                print(f"  [WARN] 音频生成失败: {text[:20]}... | {e}")
                errors += 1
                # 写入静音占位，保证标注完整性
                audio_bytes = generate_silent_wav()
                audio_path.write_bytes(audio_bytes)

            # 写入标注
            record = {
                "id": f"{intent}_{idx:03d}",
                "audio_file": str(audio_path),
                "text": text,
                "intent": intent,
                "risk_level": risk_level,
                "synthesized": True,
                "offline": args.offline or synthesizer is None,
                "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            }
            label_file.write(json.dumps(record, ensure_ascii=False) + "\n")

            intent_counts[intent] += 1
            total += 1

            if total % 20 == 0:
                print(f"  进度：{total}/{args.count} 条")

    # 输出报告
    print(f"\n{'='*50}")
    print(f"生成完成！共 {total} 条（失败 {errors} 条）")
    print("各意图分布：")
    for intent, count in intent_counts.items():
        print(f"  {intent}: {count} 条")
    print(f"\n标注文件：{labels_path}")
    print(f"音频目录：{output_dir}")
    if errors > 0:
        print(f"\n[注意] {errors} 条音频生成失败，已用静音占位，标注仍有效")


def main() -> None:
    args = parse_args()
    asyncio.run(generate(args))


if __name__ == "__main__":
    main()
