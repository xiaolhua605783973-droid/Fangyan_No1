#!/usr/bin/env python
"""快速测试 API 端点（音频上传）"""
import http.client
import json
import sys
from pathlib import Path

def test_audio(filepath: str, host: str = "localhost", port: int = 8002):
    audio_data = Path(filepath).read_bytes()
    filename = Path(filepath).name
    
    boundary = "----TestBoundary123456"
    body = (
        f"--{boundary}\r\n"
        f"Content-Disposition: form-data; name=\"audio\"; filename=\"{filename}\"\r\n"
        "Content-Type: audio/wav\r\n\r\n"
    ).encode() + audio_data + f"\r\n--{boundary}--\r\n".encode()

    conn = http.client.HTTPConnection(host, port, timeout=30)
    conn.request(
        "POST",
        "/v1/speech/recognize",
        body=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    resp = conn.getresponse()
    data = resp.read().decode("utf-8", errors="replace")
    conn.close()
    return resp.status, data


if __name__ == "__main__":
    test_files = [
        ("data/collected/CALL_NURSE_002.wav", "CALL_NURSE (WebM)"),
        ("data/collected/EMERGENCY_001.wav",  "EMERGENCY (WebM)"),
        ("data/samples/CALL_FAMILY_001.wav",  "CALL_FAMILY (真WAV)"),
    ]
    
    for filepath, label in test_files:
        if not Path(filepath).exists():
            print(f"[SKIP] {label}: 文件不存在")
            continue
        try:
            status, body = test_audio(filepath)
            print(f"[{status}] {label}: {body[:200]}")
        except Exception as e:
            print(f"[ERR] {label}: {e}")
