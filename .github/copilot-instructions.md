# Copilot Instructions — elderly_dialect_speech_infrastructure

## 项目概述

本项目是一个 **B2B 语音基础设施层**，将四川方言老年人语音转换为结构化业务意图（JSON），服务于养老 SaaS 和智能养老硬件厂商。

**核心定位：** 不是老年人 AI 助手，而是让老年人能够使用 AI 的底层基础设施。

---

## 技术栈

- **语言：** Python 3.11
- **Web 框架：** FastAPI + Uvicorn
- **ASR：** 阿里云智能语音 API（MVP阶段），预留 faster-whisper 接口
- **意图识别：** 规则引擎（关键词 + 正则，`config/intent_rules.yaml`）
- **缓存：** Redis（ASR结果缓存 + 音频去重）
- **数据库：** PostgreSQL（仅存识别结果，不存音频）
- **日志：** structlog（结构化 JSON 日志）
- **容器化：** Docker + docker-compose

---

## 项目结构

```
fangyan_mvp/
├── api/            # FastAPI 路由和 Pydantic Schema
├── core/           # 核心业务逻辑（ASR适配器、意图引擎、风险控制）
├── adapters/       # 具体 ASR 实现（阿里云、腾讯云、Whisper）
├── config/         # 配置文件（intent_rules.yaml、dialect_dict.json）
├── data/           # 数据和 bootstrap 脚本
├── db/             # SQLAlchemy 模型和 Repository
├── tests/          # pytest 测试
├── scripts/        # 批量测试和评估工具
└── deploy/         # Docker 部署文件
```

---

## 编码规范

### 通用原则

- **类型注解：** 所有函数参数和返回值必须有类型注解
- **异步优先：** I/O 密集操作（ASR调用、数据库写入）使用 `async/await`
- **Pydantic v2：** 所有 API 入参和出参必须定义 Pydantic Schema
- **依赖注入：** FastAPI 路由通过 `Depends()` 注入服务，不直接实例化
- **日志规范：** 使用 `structlog`，禁止使用 `print()`

### 命名规范

```python
# 类名：PascalCase
class SichuanDialectNormalizer: ...

# 函数/方法/变量：snake_case
def normalize_text(raw_text: str) -> str: ...

# 常量：UPPER_SNAKE_CASE
MAX_AUDIO_DURATION = 8

# Pydantic Schema 以 Schema 或 Response 结尾
class IntentResponse(BaseModel): ...
class VoiceInputSchema(BaseModel): ...
```

### 错误处理规范

```python
# 业务异常使用 FastAPI HTTPException
raise HTTPException(status_code=400, detail="音频时长超出限制（最大8秒）")

# ASR 调用异常需要有 fallback 日志
logger.error("asr_failed", provider="aliyun", error=str(e))
raise HTTPException(status_code=503, detail="语音识别服务暂时不可用")
```

---

## 意图识别规则

MVP 阶段仅支持 4 个核心意图：

| 意图 | 说明 | 风险等级 |
|------|------|---------|
| `CALL_NURSE` | 呼叫护士/医生 | LOW |
| `CALL_FAMILY` | 联系家属 | LOW |
| `HEALTH_ALERT` | 身体不适告警 | MEDIUM |
| `EMERGENCY` | 紧急求救 | HIGH |

- 意图置信度 < 0.6 时返回 `UNKNOWN`
- 风险等级判定优先级高于准确率（宁可误报，不能漏报）
- **槽位（slots）MVP阶段统一返回空对象 `{}`**

---

## API 输出规范

所有语音识别结果遵循以下 JSON 结构：

```json
{
  "intent": "CALL_NURSE",
  "slots": {},
  "confidence": 0.87,
  "risk_level": "LOW",
  "raw_text": "帮我喊哈护士嘛"
}
```

---

## 成本控制原则

- **必须启用 Redis 缓存：** 相同音频（SHA-256 哈希相同）直接返回缓存，不重复调用 ASR API
- **不存储原始音频：** 仅持久化识别结果和日志（隐私 + 成本）
- **异步写库：** 数据库写入不阻塞 API 响应

---

## 测试规范

```bash
# 运行所有测试
pytest tests/ -v --cov=core --cov=api

# 批量评估意图准确率（目标 ≥85%）
python scripts/evaluate.py data/labels.jsonl

# 端到端延迟测试（目标 <2秒）
python scripts/batch_test.py --audio-dir data/samples/
```

- 每个核心模块必须有对应的单元测试
- ASR 调用在测试中必须 mock，不允许真实调用
- 使用 `tests/fixtures/` 存放测试音频和标注数据

---

## 网络代理规范

开发和测试过程中，若遇到网络连接超时（pip 安装超时、ASR API 调用失败、TTS 接口超时等），启用公司代理：

```powershell
# Windows PowerShell 设置代理（二选一）
$env:HTTP_PROXY  = "http://10.144.1.10:8080"
$env:HTTPS_PROXY = "http://10.144.1.10:8080"

# 备用节点
$env:HTTP_PROXY  = "http://10.158.100.3:8080"
$env:HTTPS_PROXY = "http://10.158.100.3:8080"
```

```bash
# Linux/macOS
export HTTP_PROXY=http://10.144.1.10:8080
export HTTPS_PROXY=http://10.144.1.10:8080
```

- 代理仅在开发环境启用，不写入代码或配置文件
- Docker 容器内需在 `docker-compose.yml` 的 `environment` 中设置代理环境变量
- 生产环境不使用代理

---

## 任务完成行为规范

每次任务完成后，必须严格按以下步骤执行，缺一不可：

### 第一步：测试验证（必须通过）

```bash
cd fangyan_mvp
pytest tests/ -v
```

- **所有测试必须 PASSED，不允许带 FAILED 提交**
- 若新增功能，需同步新增对应测试用例
- 若修改现有逻辑，需确保已有测试仍然通过

### 第二步：提交 Git

测试全部通过后，立即提交：

```bash
git add .
git commit -m "[类型] 简短描述"
```

提交类型规范：

| 类型 | 说明 |
|------|------|
| `feat` | 新功能 |
| `fix` | Bug 修复 |
| `refactor` | 重构（不改变功能） |
| `test` | 新增/修改测试 |
| `docs` | 文档更新 |
| `chore` | 依赖、配置、脚本等杂项 |

### 第三步：更新 README（必要时）

以下情况需同步更新 [fangyan_mvp/README.md](fangyan_mvp/README.md)：

- 新增 API 接口或修改现有接口行为
- 新增启动步骤、环境变量、依赖
- 新增可运行的脚本命令

> 其他说明性文档（CHANGELOG、CONTRIBUTING 等）**不自动创建**，需用户明确要求。

---

## 关键约束（禁止事项）

- ❌ 不构建基础大模型
- ❌ 不构建通用聊天机器人
- ❌ 不构建 C 端应用
- ❌ 不存储用户音频文件
- ❌ 意图引擎 MVP 阶段禁止引入 LLM（保持规则引擎）
- ❌ 禁止在生产代码中使用 `print()`，统一用 `structlog`
