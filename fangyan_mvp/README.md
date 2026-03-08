# elderly_dialect_speech_infrastructure

> 将绍兴方言（吴语）老年人语音转换为结构化业务意图的 **B2B 语音基础设施层**

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

# 使用 Windows 本地中文 TTS 生成真实语音（无需 API Key）
python data/bootstrap/regen_demo_audio.py --count 10
```

### 8. 自动训练流水线

```bash
# 单次执行（评估准确率 + 自动优化规则）
python scripts/auto_train.py --data data/collected/labels.jsonl

# 守护进程模式（每30分钟自动执行一次）
python scripts/auto_train.py --daemon --interval 30

# 试运行（仅查看候选词，不修改规则文件）
python scripts/auto_train.py --dry-run

# 查看历史训练指标
cat data/metrics/train_metrics.jsonl | python -m json.tool
```

**流程说明：**
1. 评估 `data/collected/labels.jsonl` 中真实语料的意图准确率
2. 准确率 < 90% 时，分析错误样本，提取高频候选关键词（阈值：出现 ≥3 次）
3. 自动合并候选词到 `config/intent_rules.yaml`（带备份）
4. 重新评估验证：若准确率下降则自动回滚规则文件
5. 每轮指标写入 `data/metrics/train_metrics.jsonl`

## 生产部署（阿里云 ECS Ubuntu）

### 一键部署

```bash
# 1. 将代码上传到服务器（本地执行）
scp -r ./fangyan_mvp root@<服务器IP>:/opt/fangyan/

# 2. SSH 登录服务器后执行
sudo bash /opt/fangyan/fangyan_mvp/deploy/setup_aliyun_ubuntu.sh
```

脚本完成后自动启动 **5 个 Docker 服务**：

| 服务 | 端口 | 说明 |
|------|------|------|
| `api` | 8000 | FastAPI 识别服务 + Demo 页面 |
| `voice_collector` | 8001 | 语料收集页面（公开访问） |
| `scheduler` | — | 自动训练调度器（每30分钟） |
| `redis` | 6379 | ASR 结果缓存 |
| `postgres` | 5432 | 识别结果持久化 |

### 运维命令

```bash
# 查看各服务状态
docker compose -f deploy/docker-compose.yml ps

# 查看调度器实时日志（训练进度）
docker compose -f deploy/docker-compose.yml logs -f scheduler

# 手动触发一次训练
docker compose -f deploy/docker-compose.yml exec scheduler \
  python scripts/auto_train.py --data data/collected/labels.jsonl

# 语料统计
wc -l data/collected/labels.jsonl

# 查看准确率趋势
cat data/metrics/train_metrics.jsonl
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

| 指标 | 目标 | 验收条件 |
|------|------|------|
| 意图准确率 | ≥ 90% | 真实语料 ≥100条 |
| 端到端延迟 | < 2秒 | 生产环境 API 调用 |
| HIGH 风险召回率 | ≥ 95% | EMERGENCY 意图样本 |
| 语料环境准确率 | ≥ 85% | 合成数据集 |

> 当当前准确率：**89.3%**（80条真实语料），距 90% 目标仅差 0.7%。继续收集语料将自动优化。
