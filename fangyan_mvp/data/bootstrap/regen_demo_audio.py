"""
使用 Windows 本地 TTS (Microsoft Huihui / zh-CN) 重新生成 demo 音频。

无需 API Key，适合演示场所离线使用。文本为绍兴方言（吴语）话术。

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

# 演示用绍兴方言（吴语）文本（每个意图各10条代表性话术）
DEMO_TEXTS: dict[str, list[str]] = {
    "CALL_NURSE": [
        "护士啊快来看看",
        "阿有护士在",
        "帮我叫护士来",
        "医生来看看伐",
        "护士侬过来一下",
        "快来人啊有没有人",
        "叫个医生来看看",
        "阿有人在啊",
        "护士快来一下",
        "帮我叫一下医生",
    ],
    "CALL_FAMILY": [
        "拨我儿子打个电话",
        "帮我联系一下家里",
        "叫我女儿来一下",
        "给我打电话给老伴",
        "联系一下我儿子",
        "帮我打电话给家里人",
        "叫我孙子来看看",
        "通知我家属来",
        "联系我女儿过来",
        "帮我拨电话给儿子",
    ],
    "HEALTH_ALERT": [
        "我勿舒服",
        "肚皮蛮痛",
        "头蛮晕",
        "身体勿好受",
        "感觉交关难受",
        "头痛得厉害",
        "胸口闷得很",
        "肚子痛得厉害",
        "腰蛮痛",
        "浑身没力气",
    ],
    "EMERGENCY": [
        "救命啊快来人",
        "我跌倒了快来",
        "心脏勿来事了快帮忙",
        "救命救命快来",
        "我倒下了快来人",
        "帮帮我快点来",
        "我出血了救命",
        "我要死哉快救我",
        "动不了了快来帮忙",
        "快来快来我勿来事了",
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
