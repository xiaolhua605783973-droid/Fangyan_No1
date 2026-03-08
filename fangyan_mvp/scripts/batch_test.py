#!/usr/bin/env python3
"""
批量测试脚本：对目录中的所有音频文件执行端到端识别，输出结果 JSON。

使用方式：
    python scripts/batch_test.py --audio-dir data/samples/ --output results.json
"""
import argparse
import asyncio
import json
import time
from pathlib import Path

import httpx


async def test_audio(client: httpx.AsyncClient, audio_path: Path) -> dict:
    start = time.time()
    with open(audio_path, "rb") as f:
        files = {"audio": (audio_path.name, f, "audio/wav")}
        try:
            resp = await client.post("/v1/speech/recognize", files=files, timeout=10)
            result = resp.json()
            result["_file"] = audio_path.name
            result["_status_code"] = resp.status_code
            result["_latency_ms"] = int((time.time() - start) * 1000)
        except Exception as e:
            result = {
                "_file": audio_path.name,
                "_error": str(e),
                "_latency_ms": int((time.time() - start) * 1000),
            }
    return result


async def main(audio_dir: str, output: str, base_url: str):
    audio_files = list(Path(audio_dir).glob("*.wav")) + \
                  list(Path(audio_dir).glob("*.mp3")) + \
                  list(Path(audio_dir).glob("*.m4a"))

    if not audio_files:
        print(f"[警告] {audio_dir} 中未找到音频文件")
        return

    print(f"发现 {len(audio_files)} 个音频文件，开始测试...")

    async with httpx.AsyncClient(base_url=base_url) as client:
        tasks = [test_audio(client, f) for f in audio_files]
        results = await asyncio.gather(*tasks)

    with open(output, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    # 统计
    success = [r for r in results if "_error" not in r]
    latencies = [r["_latency_ms"] for r in success]
    avg_latency = sum(latencies) / len(latencies) if latencies else 0

    print(f"\n=== 批量测试结果 ===")
    print(f"总数: {len(results)}")
    print(f"成功: {len(success)}")
    print(f"失败: {len(results) - len(success)}")
    print(f"平均延迟: {avg_latency:.0f}ms")
    print(f"结果已保存至: {output}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--audio-dir", default="data/samples/", help="音频目录")
    parser.add_argument("--output", default="results.json", help="结果输出路径")
    parser.add_argument("--base-url", default="http://localhost:8000", help="API 地址")
    args = parser.parse_args()

    asyncio.run(main(args.audio_dir, args.output, args.base_url))
