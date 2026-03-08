"""
语音采集系统
============
用于收集四川方言老年人语音训练语料。

使用方式：
    python tools/voice_collector.py
    python tools/voice_collector.py --port 8001          # 自定义端口
    python tools/voice_collector.py --output data/collected  # 自定义输出目录
    python tools/voice_collector.py --no-browser         # 不自动打开浏览器

操作流程：
    1. 浏览器打开 http://localhost:8001
    2. 页面逐条显示待朗读文本
    3. 点击录音 → 朗读提示文字 → 停止
    4. 回放确认 → 保存 / 重录 / 跳过
    5. 完成后下载标注汇总 CSV

输出：
    data/collected/CALL_NURSE_001.wav    各意图音频文件
    data/collected/labels.jsonl          标注文件（每行一条JSON）
"""
import argparse
import asyncio
import json
import os
import sys
import time
import threading
import webbrowser
from datetime import datetime
from pathlib import Path

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel

# ──────────────────────────────────────────────
# 路径配置
# ──────────────────────────────────────────────
BASE_DIR = Path(__file__).parent.parent  # fangyan_mvp/
TEMPLATES_FILE = BASE_DIR / "data" / "bootstrap" / "templates.json"

# ──────────────────────────────────────────────
# 加载提示文本
# ──────────────────────────────────────────────

def load_prompts() -> list[dict]:
    """从 templates.json 加载所有提示语，拼合 templates + dialect_variations。"""
    if not TEMPLATES_FILE.exists():
        # 内嵌默认提示，防止文件缺失
        return _default_prompts()

    with open(TEMPLATES_FILE, encoding="utf-8") as f:
        data = json.load(f)

    prompts: list[dict] = []
    for intent, cfg in data.items():
        risk = cfg.get("risk_level", "LOW")
        for text in cfg.get("templates", []):
            prompts.append({"text": text, "intent": intent, "risk_level": risk, "source": "template"})
        for text in cfg.get("dialect_variations", []):
            prompts.append({"text": text, "intent": intent, "risk_level": risk, "source": "dialect"})

    return prompts


def _default_prompts() -> list[dict]:
    return [
        {"text": "帮我喊哈护士嘛", "intent": "CALL_NURSE", "risk_level": "LOW", "source": "default"},
        {"text": "救命啊快来人", "intent": "EMERGENCY", "risk_level": "HIGH", "source": "default"},
        {"text": "我不舒服得很", "intent": "HEALTH_ALERT", "risk_level": "MEDIUM", "source": "default"},
        {"text": "给我儿子打个电话", "intent": "CALL_FAMILY", "risk_level": "LOW", "source": "default"},
    ]


# ──────────────────────────────────────────────
# 全局状态
# ──────────────────────────────────────────────

class CollectionState:
    def __init__(self, output_dir: Path):
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.labels_file = output_dir / "labels.jsonl"
        self.prompts = load_prompts()
        self.current_index = 0
        self.saved_count = 0
        self.skipped_count = 0

        # 每个意图已保存数量（用于文件命名）
        self.intent_counters: dict[str, int] = {}

        # 从已有标注文件恢复计数
        self._restore_from_labels()

    def _restore_from_labels(self):
        """从已有 labels.jsonl 恢复进度，避免重复文件名。"""
        if not self.labels_file.exists():
            return
        with open(self.labels_file, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                    intent = record.get("intent", "UNKNOWN")
                    self.intent_counters[intent] = self.intent_counters.get(intent, 0) + 1
                    self.saved_count += 1
                except json.JSONDecodeError:
                    pass
        print(f"[恢复] 发现已有 {self.saved_count} 条标注记录")

    def next_filename(self, intent: str) -> str:
        n = self.intent_counters.get(intent, 0) + 1
        return f"{intent}_{n:03d}.wav"

    def current_prompt(self) -> dict | None:
        if self.current_index >= len(self.prompts):
            return None
        return self.prompts[self.current_index]

    def progress(self) -> dict:
        return {
            "current": self.current_index + 1,
            "total": len(self.prompts),
            "saved": self.saved_count,
            "skipped": self.skipped_count,
            "percent": round((self.current_index / max(len(self.prompts), 1)) * 100),
        }


state: CollectionState | None = None

# ──────────────────────────────────────────────
# Pydantic Schema
# ──────────────────────────────────────────────

class SaveRequest(BaseModel):
    audio_base64: str   # WAV 数据的 base64
    text: str
    intent: str
    risk_level: str
    duration_ms: int
    speaker_id: str = ""
    notes: str = ""


class SkipRequest(BaseModel):
    reason: str = ""


# ──────────────────────────────────────────────
# FastAPI App
# ──────────────────────────────────────────────

app = FastAPI(title="方言语音采集系统")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/", response_class=HTMLResponse)
async def index():
    return HTMLResponse(content=_html_page())


@app.get("/api/progress")
async def get_progress():
    if state is None:
        raise HTTPException(500, "服务未初始化")
    return state.progress()


@app.get("/api/prompt")
async def get_prompt():
    if state is None:
        raise HTTPException(500, "服务未初始化")
    prompt = state.current_prompt()
    if prompt is None:
        return JSONResponse({"done": True, "saved": state.saved_count, "skipped": state.skipped_count})
    return {**prompt, "done": False, "index": state.current_index, **state.progress()}


@app.post("/api/save")
async def save_audio(req: SaveRequest):
    if state is None:
        raise HTTPException(500, "服务未初始化")

    import base64
    try:
        audio_bytes = base64.b64decode(req.audio_base64)
    except Exception as e:
        raise HTTPException(400, f"音频解码失败: {e}")

    filename = state.next_filename(req.intent)
    audio_path = state.output_dir / filename
    audio_path.write_bytes(audio_bytes)

    # 追加标注
    record = {
        "file": filename,
        "text": req.text,
        "intent": req.intent,
        "risk_level": req.risk_level,
        "duration_ms": req.duration_ms,
        "speaker_id": req.speaker_id,
        "notes": req.notes,
        "collected_at": datetime.now().isoformat(),
    }
    with open(state.labels_file, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")

    # 更新计数
    state.intent_counters[req.intent] = state.intent_counters.get(req.intent, 0) + 1
    state.saved_count += 1
    state.current_index += 1

    return {"ok": True, "saved_as": filename, "total_saved": state.saved_count}


@app.post("/api/skip")
async def skip_prompt(req: SkipRequest):
    if state is None:
        raise HTTPException(500, "服务未初始化")
    state.skipped_count += 1
    state.current_index += 1
    return {"ok": True, "skipped": state.skipped_count}


@app.get("/api/summary")
async def get_summary():
    """返回采集统计摘要。"""
    if state is None:
        raise HTTPException(500, "服务未初始化")
    by_intent: dict[str, int] = {}
    if state.labels_file.exists():
        with open(state.labels_file, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        r = json.loads(line)
                        intent = r.get("intent", "UNKNOWN")
                        by_intent[intent] = by_intent.get(intent, 0) + 1
                    except Exception:
                        pass
    return {
        "total": state.saved_count,
        "by_intent": by_intent,
        "output_dir": str(state.output_dir.resolve()),
        "labels_file": str(state.labels_file.resolve()),
    }


@app.get("/api/export_csv")
async def export_csv():
    """导出 CSV 格式标注文件内容。"""
    if state is None or not state.labels_file.exists():
        return JSONResponse({"csv": "file,text,intent,risk_level,duration_ms,collected_at"})
    lines = ["file,text,intent,risk_level,duration_ms,speaker_id,collected_at"]
    with open(state.labels_file, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    r = json.loads(line)
                    row = ",".join([
                        r.get("file", ""), f'"{r.get("text", "")}"',
                        r.get("intent", ""), r.get("risk_level", ""),
                        str(r.get("duration_ms", 0)), r.get("speaker_id", ""),
                        r.get("collected_at", ""),
                    ])
                    lines.append(row)
                except Exception:
                    pass
    return JSONResponse({"csv": "\n".join(lines)})


# ──────────────────────────────────────────────
# 嵌入式 HTML 页面
# ──────────────────────────────────────────────

def _html_page() -> str:
    return """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>四川方言语音采集系统</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: "Microsoft YaHei", sans-serif; background: #f0f4f8; min-height: 100vh; }

  .header {
    background: linear-gradient(135deg, #1a73e8, #0d47a1);
    color: white; padding: 16px 24px;
    display: flex; align-items: center; justify-content: space-between;
  }
  .header h1 { font-size: 20px; font-weight: 600; }
  .header .stats { font-size: 13px; opacity: 0.9; }

  .progress-bar-wrap { background: #bbdefb; height: 6px; }
  .progress-bar { background: #42a5f5; height: 6px; transition: width 0.3s; }

  .main { max-width: 720px; margin: 32px auto; padding: 0 16px; }

  /* 进度卡片 */
  .progress-card {
    background: white; border-radius: 12px; padding: 20px 24px;
    margin-bottom: 20px; box-shadow: 0 2px 8px rgba(0,0,0,.08);
    display: flex; align-items: center; gap: 16px;
  }
  .progress-circle {
    width: 64px; height: 64px; border-radius: 50%;
    background: #e3f2fd; display: flex; flex-direction: column;
    align-items: center; justify-content: center;
    font-size: 11px; color: #1565c0; font-weight: 600; flex-shrink: 0;
  }
  .progress-circle span { font-size: 22px; line-height: 1; }
  .progress-info h3 { font-size: 15px; color: #333; margin-bottom: 4px; }
  .progress-info p { font-size: 13px; color: #666; }

  /* 提示文字卡片 */
  .prompt-card {
    background: white; border-radius: 12px; padding: 32px;
    margin-bottom: 20px; box-shadow: 0 2px 8px rgba(0,0,0,.08);
    text-align: center;
  }
  .intent-badge {
    display: inline-block; padding: 4px 12px; border-radius: 20px;
    font-size: 12px; font-weight: 600; margin-bottom: 20px;
  }
  .badge-CALL_NURSE    { background: #e3f2fd; color: #1565c0; }
  .badge-CALL_FAMILY   { background: #e8f5e9; color: #2e7d32; }
  .badge-HEALTH_ALERT  { background: #fff3e0; color: #e65100; }
  .badge-EMERGENCY     { background: #ffebee; color: #c62828; }
  .badge-UNKNOWN       { background: #f5f5f5; color: #555; }

  .risk-badge {
    display: inline-block; padding: 2px 8px; border-radius: 10px;
    font-size: 11px; margin-left: 8px;
  }
  .risk-HIGH   { background: #ffcdd2; color: #b71c1c; }
  .risk-MEDIUM { background: #ffe0b2; color: #e65100; }
  .risk-LOW    { background: #c8e6c9; color: #1b5e20; }

  .prompt-text {
    font-size: 42px; font-weight: 700; color: #1a1a2e;
    letter-spacing: 4px; margin: 16px 0 24px;
    line-height: 1.3;
  }
  .prompt-hint { font-size: 14px; color: #888; }

  /* 录音区域 */
  .record-section { text-align: center; }

  .record-btn {
    width: 100px; height: 100px; border-radius: 50%; border: none;
    background: #1a73e8; color: white; cursor: pointer;
    font-size: 36px; transition: all 0.2s;
    box-shadow: 0 4px 16px rgba(26,115,232,.4);
    margin: 0 auto 16px; display: block;
  }
  .record-btn:hover { transform: scale(1.06); box-shadow: 0 6px 24px rgba(26,115,232,.5); }
  .record-btn.recording {
    background: #d32f2f;
    animation: pulse 1s infinite;
    box-shadow: 0 4px 16px rgba(211,47,47,.5);
  }
  @keyframes pulse {
    0%, 100% { box-shadow: 0 0 0 0 rgba(211,47,47,.4); }
    50%       { box-shadow: 0 0 0 16px rgba(211,47,47,0); }
  }
  .record-status { font-size: 15px; color: #555; margin-bottom: 20px; min-height: 24px; }
  .record-timer  { font-size: 32px; font-weight: 300; color: #d32f2f; min-height: 44px; }

  /* 播放和操作按钮 */
  .action-row {
    display: flex; gap: 12px; justify-content: center;
    flex-wrap: wrap; margin-top: 20px;
  }
  .btn {
    padding: 10px 24px; border-radius: 8px; border: none;
    font-size: 15px; cursor: pointer; font-family: inherit;
    font-weight: 500; transition: all 0.15s;
  }
  .btn:disabled { opacity: 0.4; cursor: not-allowed; }
  .btn-primary   { background: #1a73e8; color: white; }
  .btn-primary:hover:not(:disabled)  { background: #1557b0; }
  .btn-success   { background: #2e7d32; color: white; }
  .btn-success:hover:not(:disabled)  { background: #1b5e20; }
  .btn-warning   { background: #f57c00; color: white; }
  .btn-warning:hover:not(:disabled)  { background: #e65100; }
  .btn-ghost     { background: #f5f5f5; color: #444; border: 1px solid #ddd; }
  .btn-ghost:hover:not(:disabled)    { background: #eee; }

  /* 发音人信息  */
  .speaker-row {
    background: white; border-radius: 12px; padding: 16px 24px;
    margin-bottom: 20px; box-shadow: 0 2px 8px rgba(0,0,0,.08);
    display: flex; gap: 16px; align-items: center; flex-wrap: wrap;
  }
  .speaker-row label { font-size: 13px; color: #555; font-weight: 600; }
  .speaker-row input, .speaker-row select {
    border: 1px solid #ddd; border-radius: 6px; padding: 6px 10px;
    font-size: 13px; font-family: inherit; outline: none;
  }
  .speaker-row input:focus, .speaker-row select:focus { border-color: #1a73e8; }

  /* 完成状态 */
  .done-card {
    background: white; border-radius: 12px; padding: 48px 32px;
    text-align: center; box-shadow: 0 2px 8px rgba(0,0,0,.08);
  }
  .done-icon { font-size: 72px; margin-bottom: 16px; }
  .done-card h2 { font-size: 26px; color: #333; margin-bottom: 12px; }
  .done-card p  { font-size: 16px; color: #666; margin-bottom: 8px; }
  .summary-grid {
    display: grid; grid-template-columns: repeat(2, 1fr); gap: 12px;
    margin: 24px 0; text-align: left;
  }
  .summary-item { background: #f5f5f5; border-radius: 8px; padding: 12px 16px; }
  .summary-item .label { font-size: 12px; color: #888; margin-bottom: 4px; }
  .summary-item .value { font-size: 18px; font-weight: 700; color: #333; }

  audio { width: 100%; margin-top: 12px; border-radius: 8px; }

  .toast {
    position: fixed; bottom: 24px; left: 50%; transform: translateX(-50%);
    background: #323232; color: white; padding: 10px 20px;
    border-radius: 8px; font-size: 14px; z-index: 999;
    opacity: 0; transition: opacity 0.3s; pointer-events: none;
  }
  .toast.show { opacity: 1; }

  .no-prompts { text-align: center; padding: 60px 20px; color: #888; font-size: 16px; }
</style>
</head>
<body>

<div class="header">
  <div>
    <h1>🎙 四川方言语音采集系统</h1>
    <div style="font-size:12px;opacity:.75;margin-top:2px">B2B 老年语音基础设施 · 训练语料收集</div>
  </div>
  <div class="stats" id="headerStats">加载中...</div>
</div>
<div class="progress-bar-wrap">
  <div class="progress-bar" id="progressBar" style="width:0%"></div>
</div>

<div class="main">

  <!-- 发音人信息 -->
  <div class="speaker-row">
    <label>发音人编号</label>
    <input type="text" id="speakerId" placeholder="如: S001" style="width:100px">
    <label>年龄段</label>
    <select id="ageGroup">
      <option value="">不填</option>
      <option value="60-70">60-70岁</option>
      <option value="70-80">70-80岁</option>
      <option value="80+">80岁以上</option>
      <option value="staff">工作人员</option>
    </select>
    <label>性别</label>
    <select id="gender">
      <option value="">不填</option>
      <option value="male">男</option>
      <option value="female">女</option>
    </select>
  </div>

  <!-- 主内容区（JS动态渲染） -->
  <div id="mainContent"></div>

</div>

<div class="toast" id="toast"></div>

<script>
// ──────────────────────────────────────
// 状态
// ──────────────────────────────────────
let mediaRecorder = null;
let audioChunks   = [];
let recordedBlob  = null;
let isRecording   = false;
let timerInterval = null;
let timerSeconds  = 0;
let currentPrompt = null;

// ──────────────────────────────────────
// 工具
// ──────────────────────────────────────
function showToast(msg, duration = 2000) {
  const t = document.getElementById('toast');
  t.textContent = msg;
  t.classList.add('show');
  setTimeout(() => t.classList.remove('show'), duration);
}

function intentLabel(intent) {
  const map = {
    CALL_NURSE:   '呼叫护士',
    CALL_FAMILY:  '联系家属',
    HEALTH_ALERT: '健康告警',
    EMERGENCY:    '紧急求救',
    UNKNOWN:      '未知',
  };
  return map[intent] || intent;
}

// ──────────────────────────────────────
// API
// ──────────────────────────────────────
async function fetchPrompt() {
  const r = await fetch('/api/prompt');
  return r.json();
}

async function fetchProgress() {
  const r = await fetch('/api/progress');
  return r.json();
}

async function postSave(payload) {
  const r = await fetch('/api/save', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  return r.json();
}

async function postSkip(reason = '') {
  const r = await fetch('/api/skip', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ reason }),
  });
  return r.json();
}

async function fetchSummary() {
  const r = await fetch('/api/summary');
  return r.json();
}

async function fetchCsv() {
  const r = await fetch('/api/export_csv');
  return r.json();
}

// ──────────────────────────────────────
// 录音
// ──────────────────────────────────────
async function startRecording() {
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    audioChunks = [];
    recordedBlob = null;

    // 优先 audio/wav，回退到 webm/ogg
    const mimeType = MediaRecorder.isTypeSupported('audio/wav') ? 'audio/wav'
                   : MediaRecorder.isTypeSupported('audio/webm') ? 'audio/webm'
                   : 'audio/ogg';

    mediaRecorder = new MediaRecorder(stream, { mimeType });
    mediaRecorder.ondataavailable = e => { if (e.data.size) audioChunks.push(e.data); };
    mediaRecorder.onstop = () => {
      recordedBlob = new Blob(audioChunks, { type: mimeType });
      stream.getTracks().forEach(t => t.stop());
      showPlayback();
    };
    mediaRecorder.start(100);

    isRecording = true;
    timerSeconds = 0;
    document.getElementById('recordBtn').classList.add('recording');
    document.getElementById('recordBtn').textContent = '⏹';
    document.getElementById('recordStatus').textContent = '🔴 正在录音，说完请点停止';
    timerInterval = setInterval(() => {
      timerSeconds++;
      document.getElementById('recordTimer').textContent =
        String(Math.floor(timerSeconds / 60)).padStart(2,'0') + ':' +
        String(timerSeconds % 60).padStart(2,'0');
      // 超过 15 秒自动停止
      if (timerSeconds >= 15) stopRecording();
    }, 1000);

  } catch(e) {
    alert('无法访问麦克风：' + e.message + '\\n请允许浏览器使用麦克风权限。');
  }
}

function stopRecording() {
  if (!isRecording || !mediaRecorder) return;
  clearInterval(timerInterval);
  isRecording = false;
  mediaRecorder.stop();
  document.getElementById('recordBtn').classList.remove('recording');
  document.getElementById('recordBtn').textContent = '🎙';
  document.getElementById('recordStatus').textContent = '录音完成，请回放确认';
}

function toggleRecord() {
  if (isRecording) stopRecording();
  else startRecording();
}

function showPlayback() {
  const url = URL.createObjectURL(recordedBlob);
  const existing = document.getElementById('audioPlayer');
  if (existing) existing.remove();

  const audio = document.createElement('audio');
  audio.id = 'audioPlayer';
  audio.controls = true;
  audio.src = url;
  document.getElementById('playbackArea').appendChild(audio);
  audio.play();

  document.getElementById('btnSave').disabled   = false;
  document.getElementById('btnReRecord').disabled = false;
  showToast('录音完成，请回放确认后点"保存"');
}

function reRecord() {
  recordedBlob = null;
  const existing = document.getElementById('audioPlayer');
  if (existing) existing.remove();
  document.getElementById('recordTimer').textContent = '';
  document.getElementById('recordStatus').textContent = '点击下方按钮开始录音';
  document.getElementById('btnSave').disabled   = true;
  document.getElementById('btnReRecord').disabled = true;
}

// ──────────────────────────────────────
// 保存 / 跳过
// ──────────────────────────────────────
async function saveAudio() {
  if (!recordedBlob || !currentPrompt) return;

  document.getElementById('btnSave').disabled = true;
  document.getElementById('btnSave').textContent = '保存中...';

  // 转 base64
  const arrayBuffer = await recordedBlob.arrayBuffer();
  const uint8 = new Uint8Array(arrayBuffer);
  let binary = '';
  uint8.forEach(b => binary += String.fromCharCode(b));
  const base64 = btoa(binary);

  const speakerId = document.getElementById('speakerId').value.trim();
  const ageGroup  = document.getElementById('ageGroup').value;
  const gender    = document.getElementById('gender').value;
  const notes     = [ageGroup ? '年龄:' + ageGroup : '', gender ? '性别:' + gender : ''].filter(Boolean).join(' ');

  const result = await postSave({
    audio_base64: base64,
    text:         currentPrompt.text,
    intent:       currentPrompt.intent,
    risk_level:   currentPrompt.risk_level,
    duration_ms:  timerSeconds * 1000,
    speaker_id:   speakerId,
    notes:        notes,
  });

  showToast(`✅ 已保存 ${result.saved_as}（共 ${result.total_saved} 条）`);
  reRecord();
  await loadNextPrompt();
}

async function skipPrompt() {
  await postSkip('用户跳过');
  showToast('已跳过');
  reRecord();
  await loadNextPrompt();
}

// ──────────────────────────────────────
// 渲染
// ──────────────────────────────────────
async function loadNextPrompt() {
  const data = await fetchPrompt();
  await updateProgress();

  if (data.done) {
    renderDone(data);
    return;
  }
  currentPrompt = data;
  renderPrompt(data);
}

function renderPrompt(p) {
  const html = `
    <div class="prompt-card">
      <span class="intent-badge badge-${p.intent}">${intentLabel(p.intent)}</span>
      <span class="risk-badge risk-${p.risk_level}">${p.risk_level}</span>
      <div class="prompt-text">${p.text}</div>
      <div class="prompt-hint">请用四川话自然朗读上方文字 · 正常语速说话即可</div>
    </div>

    <div class="prompt-card record-section">
      <div class="record-timer" id="recordTimer"></div>
      <button class="record-btn" id="recordBtn" onclick="toggleRecord()">🎙</button>
      <div class="record-status" id="recordStatus">点击上方麦克风按钮开始录音</div>
      <div id="playbackArea"></div>
      <div class="action-row">
        <button class="btn btn-success" id="btnSave" disabled onclick="saveAudio()">✅ 保存</button>
        <button class="btn btn-warning" id="btnReRecord" disabled onclick="reRecord()">🔄 重录</button>
        <button class="btn btn-ghost" onclick="skipPrompt()">⏭ 跳过</button>
      </div>
    </div>
  `;
  document.getElementById('mainContent').innerHTML = html;
}

async function renderDone(data) {
  const summary = await fetchSummary();
  const byIntent = summary.by_intent || {};
  const rows = Object.entries(byIntent).map(([k, v]) =>
    `<div class="summary-item"><div class="label">${intentLabel(k)}</div><div class="value">${v} 条</div></div>`
  ).join('');

  document.getElementById('mainContent').innerHTML = `
    <div class="done-card">
      <div class="done-icon">🎉</div>
      <h2>采集完成！</h2>
      <p>共保存 <strong>${summary.total}</strong> 条语音，跳过 ${data.skipped} 条</p>
      <div class="summary-grid">${rows}</div>
      <p style="font-size:13px;color:#888;margin-bottom:16px">
        文件保存于：<code>${summary.output_dir}</code>
      </p>
      <div class="action-row">
        <button class="btn btn-primary" onclick="downloadCsv()">⬇ 下载标注 CSV</button>
        <button class="btn btn-ghost"   onclick="location.reload()">🔁 继续采集</button>
      </div>
    </div>
  `;
}

async function downloadCsv() {
  const { csv } = await fetchCsv();
  const blob = new Blob([csv], { type: 'text/csv;charset=utf-8' });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = 'labels_export.csv';
  a.click();
  showToast('CSV 下载中...');
}

async function updateProgress() {
  const p = await fetchProgress();
  const pct = p.percent;
  document.getElementById('progressBar').style.width = pct + '%';
  document.getElementById('headerStats').textContent =
    `进度 ${p.current}/${p.total}  |  已保存 ${p.saved}  |  跳过 ${p.skipped}`;
}

// ──────────────────────────────────────
// 初始化
// ──────────────────────────────────────
(async () => {
  await loadNextPrompt();
})();
</script>
</body>
</html>"""


# ──────────────────────────────────────────────
# 入口
# ──────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="四川方言语音采集系统")
    parser.add_argument("--port",       type=int, default=8001, help="监听端口（默认8001）")
    parser.add_argument("--host",       type=str, default="0.0.0.0", help="监听地址")
    parser.add_argument("--output",     type=str, default="data/collected", help="音频输出目录")
    parser.add_argument("--no-browser", action="store_true", help="不自动打开浏览器")
    return parser.parse_args()


def main():
    args = parse_args()

    output_dir = Path(args.output)
    if not output_dir.is_absolute():
        output_dir = BASE_DIR / args.output

    global state
    state = CollectionState(output_dir)

    print("=" * 55)
    print("  四川方言语音采集系统")
    print("=" * 55)
    print(f"  提示词总数：{len(state.prompts)} 条")
    print(f"  已保存记录：{state.saved_count} 条")
    print(f"  输出目录：  {output_dir.resolve()}")
    print(f"  访问地址：  http://localhost:{args.port}")
    print("  按 Ctrl+C 停止服务")
    print("=" * 55)

    if not args.no_browser:
        def open_browser():
            time.sleep(1.2)
            webbrowser.open(f"http://localhost:{args.port}")
        threading.Thread(target=open_browser, daemon=True).start()

    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
