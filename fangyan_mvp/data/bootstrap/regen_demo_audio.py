"""
使用 Windows 本地 TTS (Microsoft Huihui / zh-CN) 重新生成 demo 音频。

无需 API Key，适合演示场所离线使用。

用法：
    python data/bootstrap/regen_demo_audio.py
    python data/bootstrap/regen_demo_audio.py --count 10   # 每个意图只生成10条

输出：覆盖 data/samples/ 中的静音占位文件，生成真实语音 WAV。
"""
import argparse
import io
import json
import struct
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

try:
    import pyttsx3
except ImportError:
    print("请先安装 pyttsx3：pip install pyttsx3")
    sys.exit(1)

try:
    from pydub import AudioSegment
    PYDUB_AVAILABLE = True
except ImportError:
    PYDUB_AVAILABLE = False

# 演示用四川方言文本（每个意图各10条代表性话术）
DEMO_TEXTS: dict[str, list[str]] = {
    "CALL_NURSE": [
        "帮我喊哈护士嘛",
        "护士小姐在不在哦",
        "麻烦喊个医生来嘛",
        "护士快来一下嘛",
        "喊护士来帮我看哈",
        "快来人哦帮帮忙",
        "来人嘛帮帮忙",
        "有没有人在哦护士",
        "医生来一下嘛",
        "帮我叫下护士",
    ],
    "CALL_FAMILY": [
        "给我儿子打个电话",
        "喊我女儿回来哈",
        "帮我联系下老伴儿",
        "给家里人打个电话嘛",
        "联系一下我儿子",
        "帮我打电话给我女儿",
        "给我老伴儿说一声",
        "让我儿子过来看看嘛",
        "给家人说我在这里",
        "帮我联系一下家里",
    ],
    "HEALTH_ALERT": [
        "我不舒服得很",
        "肚子痛惨了",
        "头晕得慌",
        "心里不舒服",
        "胸口闷得很",
        "我感觉不太好",
        "浑身没力气",
        "呼吸有点困难",
        "肚子痛得很厉害",
        "我有点头晕",
    ],
    "EMERGENCY": [
        "救命啊快来人",
        "我摔倒了痛死了",
        "心脏不得行了快帮忙",
        "救命快来帮我",
        "我倒下了救命",
        "出血了快来人",
        "救命啊我不行了",
        "摔倒了站不起来",
        "胸口痛死了救命",
        "快来快来我不行了",
    ],
}


def _wav_bytes_from_file(path: str) -> bytes:
    """将文件路径的 wav 读取为 bytes。"""
    with open(path, "rb") as f:
        return f.read()


def _convert_to_16k_mono(audio_bytes: bytes) -> bytes:
    """使用 pydub 转换为 16kHz 单声道 PCM WAV。"""
    if not PYDUB_AVAILABLE:
        return audio_bytes  # 无法转换，直接返回原始
    seg = AudioSegment.from_file(io.BytesIO(audio_bytes), format="wav")
    seg = seg.set_frame_rate(16000).set_channels(1).set_sample_width(2)
    buf = io.BytesIO()
    seg.export(buf, format="wav")
    return buf.getvalue()


def generate_audio_pyttsx3(text: str, speech_rate: int = 130) -> bytes:
    """
    使用 pyttsx3 + Microsoft Huihui Desktop 合成中文语音，返回 WAV bytes。
    speech_rate: 语速（默认200，调低到130模拟老年人慢速）
    """
    engine = pyttsx3.init()
    # 选择中文语音
    for voice in engine.getProperty("voices"):
        if "Huihui" in voice.name or "zh" in str(voice.languages).lower():
            engine.setProperty("voice", voice.id)
            break
    engine.setProperty("rate", speech_rate)
    engine.setProperty("volume", 0.9)

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        tmp_path = f.name

    try:
        engine.save_to_file(text, tmp_path)
        engine.runAndWait()
        time.sleep(0.1)  # 确保文件写完
        audio_bytes = _wav_bytes_from_file(tmp_path)
    finally:
        engine.stop()
        Path(tmp_path).unlink(missing_ok=True)

    return _convert_to_16k_mono(audio_bytes)


def main() -> None:
    parser = argparse.ArgumentParser(description="重新生成demo音频（Windows本地TTS）")
    parser.add_argument(
        "--count",
        type=int,
        default=10,
        help="每个意图生成多少条（默认10，最多10条）",
    )
    parser.add_argument(
        "--output",
        type=str,
        default="data/samples",
        help="输出目录（默认 data/samples）",
    )
    parser.add_argument(
        "--rate",
        type=int,
        default=130,
        help="语速（默认130，模拟老年人慢速，正常约200）",
    )
    args = parser.parse_args()

    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)
    count = min(args.count, 10)

    print(f"使用 Windows Microsoft Huihui (zh-CN) 语音合成")
    print(f"语速: {args.rate} | 每意图: {count} 条 | 输出: {output_dir}\n")

    total = 0
    for intent, texts in DEMO_TEXTS.items():
        for i, text in enumerate(texts[:count], 1):
            filename = f"{intent}_{i:03d}.wav"
            out_path = output_dir / filename
            try:
                print(f"  [{intent}] {i:2d}/{count}  \"{text}\"", end="", flush=True)
                audio = generate_audio_pyttsx3(text, args.rate)
                out_path.write_bytes(audio)
                size_kb = len(audio) / 1024
                print(f"  -> {filename} ({size_kb:.0f} KB)")
                total += 1
            except Exception as e:
                print(f"  [错误] {e}")

    print(f"\n完成！共生成 {total} 条音频文件 -> {output_dir.resolve()}")
    print("现在可以在 demo/index.html 中上传这些 WAV 文件进行演示。")


if __name__ == "__main__":
    main()
