# elderly_dialect_speech_infrastructure

> 将四川方言老年人语音转换为结构化业务意图的 **B2B 语音基础设施层**

## 快速开始

### 1. 配置环境变量

```bash
cd fangyan_mvp
cp .env.example .env
# 编辑 .env，填写 ALIYUN_ACCESS_KEY 和 ALIYUN_ACCESS_SECRET
```

### 2. 激活虚拟环境并安装依赖

```bash
python -m venv .venv
.venv\Scripts\activate        # Windows
# source .venv/bin/activate   # Linux/macOS
pip install -r requirements.txt
```

### 3. 启动服务

```bash
# 开发模式
uvicorn api.main:app --reload

# 生产部署（Docker）
cd deploy && bash deploy.sh
```

### 4. 测试接口

```bash
# 健康检查
curl http://localhost:8000/health

# 上传音频识别
curl -X POST http://localhost:8000/v1/speech/recognize \
  -F "audio=@tests/fixtures/call_nurse_01.wav"
```

### 5. 运行测试

```bash
pytest tests/ -v --cov=core --cov=api

# 评估意图准确率（基于文本标注数据）
python scripts/evaluate.py data/labels.jsonl

# 批量测试（需本地服务运行中）
python scripts/batch_test.py --audio-dir data/samples/
```

### 6. 生成测试数据集

```bash
# 离线模式（静音占位，不消耗 TTS API）
python data/bootstrap/generate_dataset.py --count 200 --offline

# 在线模式（调用阿里云 TTS，需配置 .env）
python data/bootstrap/generate_dataset.py --count 200 --add-noise
```

## API 文档

启动服务后访问：http://localhost:8000/docs

### 接口：`POST /v1/speech/recognize`

**请求：** `multipart/form-data`，字段 `audio`（WAV/MP3/M4A，2-8秒）

**响应：**

```json
{
  "intent": "CALL_NURSE",
  "slots": {},
  "confidence": 0.87,
  "risk_level": "LOW",
  "raw_text": "帮我喊哈护士嘛",
  "metadata": {
    "duration_ms": 1200,
    "matched_keywords": ["护士"]
  }
}
```

| 字段 | 说明 |
|------|------|
| `intent` | `CALL_NURSE` / `CALL_FAMILY` / `HEALTH_ALERT` / `EMERGENCY` / `UNKNOWN` |
| `risk_level` | `LOW` / `MEDIUM` / `HIGH` |
| `confidence` | 0.0 ~ 1.0，低于 0.6 返回 UNKNOWN |

## 项目结构

```
fangyan_mvp/
├── api/          # FastAPI 路由和 Schema
├── core/         # 核心业务逻辑
├── adapters/     # ASR 具体实现（阿里云、Whisper）
├── config/       # 意图规则、方言词典、紧急词库
├── db/           # 数据库模型
├── tests/        # pytest 测试
├── scripts/      # 批量测试和评估
└── deploy/       # Docker 部署
```

## 性能目标

| 指标 | 目标 | 验收月份 |
|------|------|---------|
| 意图准确率 | ≥ 85% | Month 2 |
| 端到端延迟 | < 2秒 | Month 1 |
| HIGH风险召回率 | ≥ 90% | Month 2 |
