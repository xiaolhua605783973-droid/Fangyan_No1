# 老年人方言语音基础设施 MVP 开发计划

**项目名称：** elderly_dialect_speech_infrastructure  
**版本：** v1.0 MVP  
**文档日期：** 2026-03-03  
**计划周期：** 3个月（12周）

---

## 一、项目概述

### 1.1 核心定位

将绍兴方言（吴语）老年人语音转换为结构化业务意图，服务于养老 SaaS 和智能硬件厂商的 **B2B 语音基础设施层**。

**一句话定义：**
> We are not building an elderly AI assistant.  
> We are building the infrastructure that allows elderly users to access AI.

### 1.2 MVP 范围

- **方言覆盖：** 绍兴方言（吴语）老年人语音变体
- **应用场景：** 老年人呼叫场景（养老院/居家）
- **核心意图：** 4个（CALL_NURSE, CALL_FAMILY, HEALTH_ALERT, EMERGENCY）
- **输出形式：** 结构化 JSON（意图 + 置信度 + 风险等级）

### 1.3 技术策略（基于现实约束）

| 维度 | 策略选择 | 原因 |
|------|---------|------|
| **ASR引擎** | 商业API优先（阿里云/腾讯云） | 无真实数据，自研风险高 |
| **意图识别** | 规则引擎（关键词+正则） | 场景受限，可控性强 |
| **部署环境** | 私有化 CPU 服务器 | 客户需求，需极致优化 |
| **数据策略** | 合成数据 bootstrap + 逐步获取真实数据 | 暂无养老机构渠道 |
| **成本控制** | Redis缓存 + 去重 + 降级策略 | 预算有限（ASR API按量计费） |

---

## 二、技术架构

### 2.1 系统架构图

```
┌─────────────────────────────────────────────────┐
│  客户端层（养老硬件/SaaS系统）                      │
│  - 录音设备  - 移动端  - Web端                     │
└────────────┬────────────────────────────────────┘
             │ HTTP POST /v1/speech/recognize
             │ (WAV/MP3/M4A, 2-8秒)
             ▼
┌─────────────────────────────────────────────────┐
│  语音中间层（核心项目范围）                         │
│  ┌──────────────────────────────────────────┐   │
│  │ 1. API层 (FastAPI)                        │   │
│  │    - 音频格式检测/转换                      │   │
│  │    - 请求去重（基于音频哈希）               │   │
│  │    - 日志追踪                              │   │
│  └───────────────┬──────────────────────────┘   │
│                  ▼                               │
│  ┌──────────────────────────────────────────┐   │
│  │ 2. ASR适配器                              │   │
│  │    - 阿里云/腾讯云 API（Month 1-2）        │   │
│  │    - Whisper + 量化（Month 3预研）         │   │
│  │    - Redis缓存层                          │   │
│  └───────────────┬──────────────────────────┘   │
│                  ▼                               │
│  ┌──────────────────────────────────────────┐   │
│  │ 3. 文本规范化                             │   │
│  │    - 绍兴方言词汇映射                      │   │
│  │    - 口语化简化                           │   │
│  └───────────────┬──────────────────────────┘   │
│                  ▼                               │
│  ┌──────────────────────────────────────────┐   │
│  │ 4. 意图识别引擎                           │   │
│  │    - 规则匹配（关键词+正则）               │   │
│  │    - 置信度计算                           │   │
│  └───────────────┬──────────────────────────┘   │
│                  ▼                               │
│  ┌──────────────────────────────────────────┐   │
│  │ 5. 风险控制模块                           │   │
│  │    - 紧急词检测（Aho-Corasick）           │   │
│  │    - 风险等级判定                          │   │
│  └───────────────┬──────────────────────────┘   │
│                  ▼                               │
│  ┌──────────────────────────────────────────┐   │
│  │ 6. 结构化输出                             │   │
│  │    {intent, confidence, risk_level, ...}  │   │
│  └──────────────────────────────────────────┘   │
└─────────────────────────────────────────────────┘
             │
             ▼
┌─────────────────────────────────────────────────┐
│  数据层                                          │
│  - PostgreSQL（结果存储）                         │
│  - Redis（ASR缓存 + 去重）                        │
│  - 文件日志（结构化JSON）                          │
└─────────────────────────────────────────────────┘
```

### 2.2 技术栈选型

#### 核心组件

| 组件 | 技术选型 | 版本/备注 |
|------|---------|----------|
| **Web框架** | FastAPI | 0.100+ (异步高性能) |
| **ASR引擎** | 阿里云智能语音/腾讯云ASR | 支持吴语方言模型 |
| **数据验证** | Pydantic | v2 (类型安全) |
| **音频处理** | FFmpeg + pydub | 格式转换、降噪 |
| **缓存** | Redis | 7.0+ (ASR结果缓存) |
| **数据库** | PostgreSQL | 14+ (结果存储) |
| **日志** | structlog | 结构化JSON日志 |
| **容器化** | Docker + docker-compose | 私有化部署 |

#### Month 3 预研技术

| 组件 | 技术选型 | 用途 |
|------|---------|------|
| **自研ASR** | faster-whisper (CTranslate2) | CPU推理优化 |
| **模型量化** | INT8 量化 | 减少内存和延迟 |
| **微调** | LoRA (PEFT库) | 方言适配 |

---

## 三、详细开发计划

### Month 1：基础设施与数据验证（Week 1-5）

#### Week 1：项目初始化

**目标：** 搭建开发环境和基础框架

**项目结构：**

```
fangyan_mvp/
├── api/
│   ├── __init__.py
│   ├── main.py              # FastAPI应用入口
│   ├── dependencies.py      # 依赖注入
│   ├── schemas.py           # Pydantic数据模型
│   └── routers/
│       ├── __init__.py
│       ├── health.py        # 健康检查
│       └── speech.py        # 语音识别接口
├── core/
│   ├── __init__.py
│   ├── asr_adapter.py       # ASR适配器抽象
│   ├── audio_processor.py   # 音频预处理
│   ├── text_normalizer.py   # 文本规范化
│   ├── intent_engine.py     # 意图识别引擎（Month 2）
│   ├── risk_control.py      # 风险控制（Month 2）
│   └── logger.py            # 日志配置
├── adapters/
│   ├── __init__.py
│   ├── aliyun_asr.py        # 阿里云ASR实现
│   ├── tencent_asr.py       # 腾讯云ASR实现
│   └── whisper_asr.py       # Whisper实现（Month 3）
├── config/
│   ├── settings.py          # 配置管理
│   ├── dialect_dict.json    # 绍兴方言词典
│   └── intent_rules.yaml    # 意图规则（Month 2）
├── data/
│   ├── bootstrap/
│   │   ├── text_generator.py
│   │   ├── audio_synthesizer.py
│   │   └── templates.json
│   └── samples/
├── db/
│   ├── __init__.py
│   ├── models.py
│   └── repository.py
├── tests/
│   ├── __init__.py
│   ├── test_api.py
│   ├── test_asr.py
│   ├── test_intent.py
│   └── fixtures/
├── scripts/
│   ├── batch_test.py
│   └── evaluate.py
├── deploy/
│   ├── Dockerfile
│   ├── docker-compose.yml
│   └── deploy.sh
├── requirements.txt
├── README.md
└── .env.example
```

**核心依赖：**

```
fastapi==0.109.0
uvicorn[standard]==0.27.0
pydantic==2.5.0
pydantic-settings==2.1.0
redis==5.0.1
psycopg2-binary==2.9.9
sqlalchemy==2.0.25
aliyun-python-sdk-core==2.14.0
tencentcloud-sdk-python==3.0.1060
pydub==0.25.1
librosa==0.10.1
structlog==24.1.0
pytest==7.4.4
httpx==0.26.0
python-multipart==0.0.6
```

**配置管理（`config/settings.py`）：**

```python
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    APP_NAME: str = "Elderly Dialect Speech Infrastructure"
    VERSION: str = "1.0.0"
    DEBUG: bool = False

    # ASR配置
    ASR_PROVIDER: str = "aliyun"  # aliyun | tencent | whisper
    ALIYUN_ACCESS_KEY: str
    ALIYUN_ACCESS_SECRET: str

    # 音频限制
    MAX_AUDIO_DURATION: int = 8
    MIN_AUDIO_DURATION: int = 2
    ALLOWED_FORMATS: list = ["wav", "mp3", "m4a"]

    # Redis
    REDIS_URL: str = "redis://localhost:6379/0"
    CACHE_TTL: int = 86400

    # PostgreSQL
    DATABASE_URL: str = "postgresql://user:pass@localhost/fangyan"

    # 成本控制
    ENABLE_CACHE: bool = True
    ENABLE_DEDUP: bool = True

    class Config:
        env_file = ".env"
```

**交付物：**
- ✅ 项目结构完整
- ✅ FastAPI应用可启动
- ✅ `GET /health` 接口返回200

---

#### Week 2：ASR适配层开发

**目标：** 接入商业ASR API，实现音频转文本

**音频预处理（`core/audio_processor.py`）：**

```python
import hashlib
from pydub import AudioSegment

class AudioProcessor:
    def validate(self, audio_bytes: bytes) -> dict:
        """验证音频格式和时长，返回 {valid, format, duration}"""

    def convert_to_pcm(self, audio_bytes: bytes, format: str) -> bytes:
        """转换为16kHz单声道PCM WAV"""
        audio = AudioSegment.from_file(io.BytesIO(audio_bytes), format=format)
        audio = audio.set_frame_rate(16000).set_channels(1)
        return audio.export(format="wav").read()

    def compute_hash(self, audio_bytes: bytes) -> str:
        """计算SHA-256哈希用于去重"""
        return hashlib.sha256(audio_bytes).hexdigest()
```

**ASR适配器抽象（`core/asr_adapter.py`）：**

```python
from abc import ABC, abstractmethod
from dataclasses import dataclass

@dataclass
class ASRResult:
    text: str
    confidence: float
    duration_ms: int
    provider: str

class ASRAdapter(ABC):
    @abstractmethod
    async def transcribe(self, audio_bytes: bytes) -> ASRResult:
        pass
```

**Redis缓存层（`core/cache.py`）：**

```python
class ASRCache:
    def __init__(self, redis_url: str, ttl: int):
        self.redis = redis.from_url(redis_url)
        self.ttl = ttl

    async def get(self, audio_hash: str) -> ASRResult | None:
        cached = self.redis.get(f"asr:{audio_hash}")
        return ASRResult(**json.loads(cached)) if cached else None

    async def set(self, audio_hash: str, result: ASRResult):
        self.redis.setex(f"asr:{audio_hash}", self.ttl, json.dumps(result.__dict__))
```

**测试任务：**
- 用5条人工录制绍兴方言音频验证ASR
- 验证缓存命中和去重逻辑
- 记录ASR延迟和成本

**交付物：**
- ✅ 阿里云ASR可用
- ✅ Redis缓存正常工作
- ✅ 音频格式自动检测和转换
- ✅ 5条音频的ASR准确率和延迟测试报告

---

#### Week 3-4：数据Bootstrap系统

**目标：** 生成200条绍兴方言测试数据

**绍兴方言文本模板（`data/bootstrap/templates.json`）：**

```json
{
  "CALL_NURSE": ["护士啊阿有人", "帮我叫护士来", "阿有护士在格"],
  "CALL_FAMILY": ["拨我儿子打个电话", "叫我囡儿来一下", "帮我联系一下老伴"],
  "HEALTH_ALERT": ["我勿舒服", "脊皮蛮痛", "头蛮晕"],
  "EMERGENCY": ["救命啊快来人", "我跌倒了快来", "我要死哉快救我"]
}
```

**TTS音频合成（`data/bootstrap/audio_synthesizer.py`）：**

```python
class AudioSynthesizer:
    def synthesize(self, text: str) -> bytes:
        # 调用阿里云TTS，普通话音色 + 老年语速（0.8x）（绍兴话将语厥输入即可）

    def add_noise(self, audio: bytes) -> bytes:
        # 叠加轻微背景噪声（模拟真实环境）
```

**批量生成命令：**

```bash
python data/bootstrap/generate_dataset.py \
  --output data/samples/ \
  --count 200 \
  --add-noise
```

**命令行标注工具（`data/bootstrap/label_tool.py`）：**
- 播放音频 → 输入转写文本 → 选择意图 → 选择风险等级
- 输出格式：JSON Lines

**交付物：**
- ✅ 200条标注数据（JSON Lines格式）
- ✅ 数据质量报告（合成音频ASR准确率）
- ✅ 标注工具可用

---

#### Week 5：文本规范化与数据库

**目标：** 处理ASR输出的方言文本，准备存储层

**绍兴方言规范化（`core/text_normalizer.py`）：**

```python
class ShaoxingDialectNormalizer:
    def normalize(self, text: str) -> str:
        # 1. 方言词汇替换（勿→不，蛮→很，交关→非常）
        # 2. 去除语气词（哉/伐/嗲——吴语绍兴话特有语气词）
        # 3. 简化口语表达
        # 4. 保留关键医疗词汇（头晕/胸闷/跌倒/肚皮痛）
```

**方言词典（`config/dialect_dict.json`）：**

```json
{
  "勿": "不",
  "蛮": "很",
  "交关": "非常",
  "侬": "你",
  "拨": "给",
  "要死哉": "快不行了",
  "吃力": "难受"
}
```

**数据库模型（`db/models.py`）：**

```python
class RecognitionRecord(Base):
    __tablename__ = "recognition_records"
    id = Column(String(36), primary_key=True)   # UUID
    audio_hash = Column(String(64), index=True)
    raw_text = Column(Text)
    normalized_text = Column(Text)
    intent = Column(String(50))
    confidence = Column(Float)
    risk_level = Column(String(20))
    asr_duration_ms = Column(Integer)
    total_duration_ms = Column(Integer)
    created_at = Column(DateTime, default=datetime.utcnow)
```

**Month 1 里程碑验收：**
- ✅ API接口正常，返回规范JSON
- ✅ 商业ASR基线评估（200条样本WER报告）
- ✅ 端到端延迟 < 2秒
- ✅ PostgreSQL + Redis + 日志均正常

---

### Month 2：意图识别与风险控制（Week 6-9）

#### Week 6-7：规则意图识别引擎

**目标：** 基于Month 1真实转写文本构建意图规则

**规则配置（`config/intent_rules.yaml`）：**

```yaml
CALL_NURSE:
  keywords: [护士, 医生, 人来, 帮忙, 医务]
  patterns: [".*喊.*护士.*", ".*找.*医生.*", ".*来.*人.*"]
  weight: 1.0
  min_confidence: 0.6

CALL_FAMILY:
  keywords: [子女, 儿子, 女儿, 家人, 老伴, 亲人]
  patterns: [".*打.*电话.*", ".*联系.*家.*"]
  weight: 1.0
  min_confidence: 0.6

HEALTH_ALERT:
  keywords: [不舒服, 痛, 晕, 难受, 胸闷, 气短]
  patterns: [".*不.*舒服.*", ".*痛.*"]
  weight: 0.9
  min_confidence: 0.5

EMERGENCY:
  keywords: [救命, 紧急, 快来, 摔倒, 出血, 昏迷]
  patterns: [".*救.*", ".*摔.*"]
  weight: 1.2
  min_confidence: 0.7
```

**规则引擎（`core/intent_engine.py`）：**

```python
class RuleBasedIntentEngine:
    def recognize(self, text: str) -> IntentResult:
        # 关键词匹配 + 正则匹配 + 权重打分
        # 归一化置信度到0-1
        # 返回最高分意图，低于min_confidence返回UNKNOWN

    def reload_rules(self):
        # 热更新规则（无需重启服务）
```

**规则热更新（watchdog监听`config/`目录）：**
- 修改 `intent_rules.yaml` 后自动重载，无需重启服务

**迭代策略：**
1. 用200条数据测试 → 分析错误 → 调整规则权重 → 再测试
2. 重点优化召回率（宁可误报，不能漏报紧急情况）

**交付物：**
- ✅ 意图识别引擎可用，支持热更新
- ✅ 基于200条样本，准确率 > 75%

---

#### Week 8：风险控制模块

**目标：** 实现紧急情况检测和三级风险判定

**紧急词库（`config/emergency_keywords.json`）：**

```json
{
  "critical": ["救命", "快来", "死了", "不行了", "心脏", "胸痛", "呼吸困难", "昏迷"],
  "urgent": ["摔倒", "头晕", "呕吐", "骨折", "发烧", "腹痛", "胸闷", "气短"],
  "warning": ["不舒服", "难受", "疼", "乏力"]
}
```

**风险控制（`core/risk_control.py`）：**

```python
class RiskController:
    def __init__(self, keywords_path: str):
        # 使用 Aho-Corasick 构建多模式匹配自动机（<10ms）

    def assess_risk(self, text: str, intent: str, confidence: float) -> tuple[str, list]:
        # critical词 → HIGH
        # urgent词 → MEDIUM
        # EMERGENCY意图 → 强制HIGH
        # HEALTH_ALERT意图 → 至少MEDIUM
        # 低置信度 + 任何紧急词 → 升级一级
        return risk_level, matched_keywords
```

**测试要求：**
- 紧急情况召回率 > 95%（不能漏报）
- 误报率可接受（宁可多报）

**交付物：**
- ✅ 风险控制模块可用
- ✅ HIGH风险召回率 > 95%

---

#### Week 9：集成测试与优化

**完整API流程（`api/routers/speech.py`）：**

```python
@router.post("/v1/speech/recognize")
async def recognize_speech(audio: UploadFile):
    # 1. 验证音频 + 计算哈希
    # 2. ASR（优先命中Redis缓存）
    # 3. 文本规范化
    # 4. 意图识别
    # 5. 风险控制
    # 6. 异步写入PostgreSQL
    # 7. 返回结构化JSON
    return {
        "intent": intent_result.intent,
        "slots": {},
        "confidence": intent_result.confidence,
        "risk_level": risk_level,
        "raw_text": asr_result.text,
        "metadata": {"duration_ms": total_ms}
    }
```

**批量回归测试：**

```bash
python scripts/batch_test.py \
  --audio-dir data/samples/ \
  --labels data/labels.jsonl \
  --output results.json

python scripts/evaluate.py results.json
# 预期输出：
# Intent Accuracy: 86.5%
# Risk Recall (HIGH): 98.0%
# Avg Latency: 1.85s
```

**Month 2 里程碑验收：**
- ✅ 意图准确率 ≥ 85%
- ✅ HIGH风险召回率 ≥ 90%
- ✅ 平均延迟 < 2秒
- ✅ 规则热更新可用
- ✅ Swagger API文档完整

---

### Month 3：自研ASR预研与POC Demo（Week 10-12）

#### Week 10-11：Whisper CPU优化预研

**目标：** 评估自研ASR在CPU环境的可行性，为后续降本提供决策依据

**faster-whisper部署（`adapters/whisper_asr.py`）：**

```python
from faster_whisper import WhisperModel

class WhisperASRAdapter(ASRAdapter):
    def __init__(self, model_size: str = "medium"):
        self.model = WhisperModel(
            model_size,
            device="cpu",
            compute_type="int8",
            num_workers=4
        )

    async def transcribe(self, audio_bytes: bytes) -> ASRResult:
        # INT8量化推理，输出中文转写文本
```

**基准测试（`scripts/benchmark_asr.py`）：**

对比三组方案（200条测试集）：

| 方案 | 平均WER | 平均延迟 | 月成本（1万次） |
|------|--------|---------|----------------|
| 阿里云ASR | 基准 | ~800ms | ~175元（含缓存） |
| Whisper-medium INT8 | 待测 | 待测 | ~300元（服务器） |
| Whisper-small INT8 | 待测 | 待测 | ~300元（服务器） |

**混合部署策略（如果Whisper延迟超标）：**

```python
class HybridASRAdapter(ASRAdapter):
    async def transcribe(self, audio_bytes: bytes) -> ASRResult:
        try:
            return await asyncio.wait_for(
                self.whisper.transcribe(audio_bytes), timeout=1.5
            )
        except asyncio.TimeoutError:
            return await self.commercial_api.transcribe(audio_bytes)
```

**交付物：**
- ✅ Whisper CPU延迟和WER基准测试报告
- ✅ 三方案成本对比分析
- ✅ 给出Year 2 ASR路线决策建议

---

#### Week 12：POC Demo与部署文档

**目标：** 可演示的完整系统，具备商业洽谈能力

**Web Demo（`demo/index.html`）：**
- 录音按钮 → 上传音频 → 展示识别结果
- 风险等级颜色区分（HIGH红色 / MEDIUM黄色 / LOW绿色）

**Docker部署（`deploy/docker-compose.yml`）：**

```yaml
services:
  api:
    build: .
    ports: ["8000:8000"]
    environment:
      - ASR_PROVIDER=aliyun
      - ALIYUN_ACCESS_KEY=${ALIYUN_ACCESS_KEY}
      - REDIS_URL=redis://redis:6379/0
      - DATABASE_URL=postgresql://fangyan:password@postgres:5432/fangyan
    volumes:
      - ./logs:/app/logs
      - ./config:/app/config
    depends_on: [redis, postgres]

  redis:
    image: redis:7-alpine

  postgres:
    image: postgres:14-alpine
    environment:
      POSTGRES_DB: fangyan
      POSTGRES_USER: fangyan
      POSTGRES_PASSWORD: password
    volumes:
      - postgres_data:/var/lib/postgresql/data

volumes:
  postgres_data:
```

**一键部署脚本（`deploy/deploy.sh`）：**

```bash
#!/bin/bash
echo "=== 老年方言语音基础设施部署 ==="
[ ! -f .env ] && echo "错误：缺少.env文件" && exit 1
docker-compose build
docker-compose up -d
sleep 10
curl -f http://localhost:8000/health && echo "✅ 部署成功！" || (docker-compose logs api && exit 1)
```

**Month 3 里程碑验收：**
- ✅ Whisper基准测试报告完成
- ✅ POC Demo可流畅演示
- ✅ Docker一键部署成功
- ✅ README + API文档完整

---

## 四、验收标准汇总

| 阶段 | 验收项 | 标准 | 验证方式 |
|------|--------|------|---------|
| **Month 1** | API可用性 | 健康检查200 | `curl GET /health` |
| | ASR集成 | 商业API正常调用 | 5条真实音频测试 |
| | 数据Bootstrap | 200条样本生成 | 检查目录文件数 |
| | 延迟 | 端到端 < 2秒 | 批量测试均值 |
| **Month 2** | 意图准确率 | ≥ 85% | 200条回归测试 |
| | 风险召回率 | ≥ 90%（HIGH级） | 紧急场景专项测试 |
| | 规则热更新 | 修改YAML无需重启 | 线上更新验证 |
| **Month 3** | Whisper基准 | WER + 延迟对比完成 | 基准测试报告 |
| | POC Demo | 完整流程可演示 | 内部演示通过 |
| | 部署 | 新环境一键部署成功 | 全量部署测试 |

---

## 五、关键决策记录

### 决策1：商业ASR优先（Month 1-2）
**原因：** 无真实老年方言数据，Whisper方言WER未知，自研风险高  
**后续行动：** Month 3基于成本/WER数据决定Year 2是否切换自研

### 决策2：规则引擎（MVP阶段坚持）
**原因：** 4个意图场景受限；CPU环境运行LLM会超出2秒延迟；可解释性强  
**预留方案：** Year 2扩展到30个意图时，引入小型分类模型（BERT/Qwen2-1.5B）

### 决策3：数据Bootstrap
**原因：** 暂无养老机构合作，无20小时真实音频  
**风险：** 合成数据准确率上限约80-85%  
**关键行动：** Month 2必须获取至少50条真实音频（最高优先级）

### 决策4：不持久化音频文件
**原因：** 预算有限 + 隐私合规  
**补充：** 可在用户授权情况下选择性存储，用于后续模型训练

### 决策5：Redis缓存+去重
**原因：** 商业ASR按量计费，养老场景存在常见重复音频（如固定报警词）  
**预期效果：** 节省约30%调用成本

---

## 六、风险管理

| 风险 | 概率 | 影响 | 缓解措施 |
|------|------|------|---------|
| 商业ASR对老年方言识别率低（WER>40%） | 高 | 致命 | Week 2立即验证；考虑更换提供商（如讯飞、科大讯飞） |
| 无法获取真实老年方言数据 | 高 | 严重 | Month 1同步启动BD，联系养老SaaS客户；考虑数据众包 |
| CPU环境无法满足2秒延迟 | 中 | 严重 | Whisper+商业API混合部署；数据库写入异步化 |
| ASR API成本失控 | 中 | 中等 | 月度成本监控告警；严格缓存策略 |
| 规则引擎扩展性瓶颈 | 高 | 中等 | MVP后预留LLM路线 |

---

## 七、成本估算

### 开发成本（3个月MVP）

| 角色 | 投入 | 小计 |
|------|------|------|
| 后端开发 | 1人 × 3月 | 7.5万 |
| 算法工程师 | 0.5人 × 3月 | 4.5万 |
| 测试工程师 | 0.5人 × 3月 | 3万 |
| **合计** | | **15万** |

### 月运营成本（1万次调用）

| 项目 | 小计 |
|------|------|
| 阿里云ASR（0.025元/次 × 1万次） | 250元 |
| 缓存节省（-30%） | -75元 |
| 4核8G CPU服务器 | 300元 |
| PostgreSQL云数据库 | 200元 |
| **合计** | **675元/月** |

---

## 八、长期规划

| 阶段 | 目标 |
|------|------|
| **Year 1** | 单方言（绍兴话/吴语）深度突破；单场景成熟；建立语音数据资产；试点首单商业化 |
| **Year 2** | 扩展3-5个方言；SDK标准化；多场景（用药/健康咨询）；切换自研ASR降本 |
| **Year 3** | 成为养老行业默认语音接口层；开放平台；多模态探索 |

---

## 九、附录

### API接口规范（OpenAPI 3.0摘要）

```yaml
POST /v1/speech/recognize
Request:
  multipart/form-data:
    audio: binary (WAV/MP3/M4A, 2-8秒)

Response 200:
  intent: CALL_NURSE | CALL_FAMILY | HEALTH_ALERT | EMERGENCY | UNKNOWN
  slots: {}
  confidence: float (0.0-1.0)
  risk_level: LOW | MEDIUM | HIGH
  raw_text: string
  metadata:
    duration_ms: integer
    matched_keywords: string[]
```

### 关键监控指标

- `asr_request_total`：ASR请求总数
- `asr_request_duration_seconds`：延迟分布（P50/P95/P99）
- `cache_hit_rate`：Redis缓存命中率
- `intent_distribution`：4个意图调用占比
- `risk_high_total`：HIGH风险事件数（需实时告警）

### 绍兴方言词汇表（示例）

| 方言 | 标准考 | 场景 |
|------|--------|------|
| 勿 | 不 | 否定 |
| 蛮 | 很 | 程度 |
| 交关 | 非常 | 程度 |
| 要死哉 | 快不行了 | 紧急 |
| 吃力 | 难受 | 健康 |
| 囡儿 | 女儿 | 亲属 |

---

**下一步立即行动：**
1. **Week 1**：初始化项目，搭建FastAPI框架
2. **Week 2**：接入阿里云ASR，验证绍兴方言识别基线
3. **Month 2启动**：同步联系至少3家养老机构，洽谈真实数据合作（最高优先级）
