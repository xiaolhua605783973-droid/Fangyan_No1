#!/usr/bin/env bash
# =============================================================================
#  一键部署脚本 — 绍兴方言语音基础设施 (elderly_dialect_speech_infrastructure)
#  适用环境：阿里云 ECS / Ubuntu 20.04 / 22.04
#
#  用法：
#    chmod +x deploy/setup_aliyun_ubuntu.sh
#    sudo bash deploy/setup_aliyun_ubuntu.sh
#
#  脚本完成后：
#    - API 识别服务:      http://<IP>:8000
#    - B2B Demo 页面:     http://<IP>:8000/demo
#    - 语料收集页面:      http://<IP>:8001
#    - 自动训练调度器:    后台 Docker 容器（每30分钟执行一次）
#    - 训练指标日志:      /opt/fangyan/data/metrics/train_metrics.jsonl
# =============================================================================
set -euo pipefail

###############################################################################
# 颜色输出工具
###############################################################################
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

info()    { echo -e "${GREEN}[INFO]${NC}  $*"; }
warn()    { echo -e "${YELLOW}[WARN]${NC}  $*"; }
error()   { echo -e "${RED}[ERROR]${NC} $*" >&2; }
section() { echo -e "\n${CYAN}${BOLD}══════ $* ══════${NC}"; }

###############################################################################
# 配置常量
###############################################################################
PROJECT_DIR="/opt/fangyan"
REPO_URL="${REPO_URL:-}"          # 可通过环境变量预置，否则提示手动上传
DOCKER_COMPOSE_VERSION="2.27.0"
COMPOSE_FILE="${PROJECT_DIR}/fangyan_mvp/deploy/docker-compose.yml"
ENV_FILE="${PROJECT_DIR}/fangyan_mvp/.env"

###############################################################################
# 0. 前置检查
###############################################################################
section "前置检查"

if [[ $EUID -ne 0 ]]; then
    error "请以 root 身份运行此脚本，或使用 sudo bash deploy/setup_aliyun_ubuntu.sh"
    exit 1
fi

OS_ID=$(. /etc/os-release && echo "$ID")
OS_VERSION=$(. /etc/os-release && echo "$VERSION_ID")
if [[ "$OS_ID" != "ubuntu" ]]; then
    error "此脚本仅支持 Ubuntu，当前系统: $OS_ID $OS_VERSION"
    exit 1
fi
info "系统检查通过: Ubuntu $OS_VERSION"

PUBLIC_IP=$(curl -sf --max-time 5 http://100.100.100.200/latest/meta-data/eip/public-ip-address 2>/dev/null \
    || curl -sf --max-time 5 http://ipinfo.io/ip 2>/dev/null \
    || echo "未知")
info "服务器公网 IP: ${PUBLIC_IP}"

###############################################################################
# 1. 系统更新 + 基础工具
###############################################################################
section "安装系统依赖"

# 使用阿里云 apt 源加速
if ! grep -q "mirrors.aliyun.com" /etc/apt/sources.list 2>/dev/null; then
    info "替换为阿里云 apt 镜像..."
    cp /etc/apt/sources.list /etc/apt/sources.list.bak
    cat > /etc/apt/sources.list <<EOF
deb http://mirrors.aliyun.com/ubuntu/ $(lsb_release -cs) main restricted universe multiverse
deb http://mirrors.aliyun.com/ubuntu/ $(lsb_release -cs)-updates main restricted universe multiverse
deb http://mirrors.aliyun.com/ubuntu/ $(lsb_release -cs)-security main restricted universe multiverse
EOF
fi

apt-get update -qq
apt-get install -y -qq \
    curl git ca-certificates gnupg lsb-release \
    ufw net-tools jq
info "基础工具安装完成"

###############################################################################
# 2. 安装 Docker CE
###############################################################################
section "安装 Docker CE"

if command -v docker &>/dev/null; then
    DOCKER_VER=$(docker --version | awk '{print $3}' | tr -d ',')
    info "Docker 已安装: $DOCKER_VER，跳过安装"
else
    info "安装 Docker CE（阿里云镜像）..."
    install -m 0755 -d /etc/apt/keyrings
    curl -fsSL https://mirrors.aliyun.com/docker-ce/linux/ubuntu/gpg \
        | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
    chmod a+r /etc/apt/keyrings/docker.gpg
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
https://mirrors.aliyun.com/docker-ce/linux/ubuntu \
$(lsb_release -cs) stable" > /etc/apt/sources.list.d/docker.list
    apt-get update -qq
    apt-get install -y -qq docker-ce docker-ce-cli containerd.io
    systemctl enable --now docker
    info "Docker 安装完成: $(docker --version)"
fi

###############################################################################
# 3. 安装 Docker Compose v2
###############################################################################
section "安装 Docker Compose v2"

COMPOSE_BIN="/usr/local/lib/docker/cli-plugins/docker-compose"
if docker compose version &>/dev/null 2>&1; then
    info "Docker Compose 已安装: $(docker compose version --short)"
else
    info "安装 Docker Compose v${DOCKER_COMPOSE_VERSION}..."
    mkdir -p /usr/local/lib/docker/cli-plugins
    ARCH=$(uname -m)
    [[ "$ARCH" == "aarch64" ]] && ARCH="aarch64" || ARCH="x86_64"
    curl -fsSL \
        "https://github.com/docker/compose/releases/download/v${DOCKER_COMPOSE_VERSION}/docker-compose-linux-${ARCH}" \
        -o "${COMPOSE_BIN}"
    chmod +x "${COMPOSE_BIN}"
    info "Docker Compose 安装完成: $(docker compose version --short)"
fi

###############################################################################
# 4. 部署项目代码
###############################################################################
section "部署项目代码"

mkdir -p "${PROJECT_DIR}"

if [[ -n "${REPO_URL}" ]]; then
    info "从 Git 仓库克隆: ${REPO_URL}"
    if [[ -d "${PROJECT_DIR}/.git" ]]; then
        cd "${PROJECT_DIR}" && git pull
        info "代码已更新（git pull）"
    else
        git clone "${REPO_URL}" "${PROJECT_DIR}"
        info "代码克隆完成"
    fi
elif [[ -f "$(dirname "$0")/../fangyan_mvp/api/main.py" ]]; then
    # 脚本在项目目录中运行，直接使用当前目录
    SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
    SOURCE_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
    if [[ "${SOURCE_DIR}" != "${PROJECT_DIR}" ]]; then
        info "从当前目录复制项目到 ${PROJECT_DIR}..."
        rsync -a --exclude='.git' --exclude='__pycache__' \
              --exclude='*.pyc' --exclude='.venv' --exclude='*.egg-info' \
              "${SOURCE_DIR}/" "${PROJECT_DIR}/"
        info "项目代码复制完成"
    else
        info "项目已在目标目录，跳过复制"
    fi
else
    warn "未找到项目代码，请手动上传 fangyan_mvp 目录到 ${PROJECT_DIR}/"
    echo ""
    echo -e "${YELLOW}  上传方法（在本地终端执行）：${NC}"
    echo "    scp -r ./fangyan_mvp root@${PUBLIC_IP}:${PROJECT_DIR}/"
    echo ""
    echo "  上传完成后，重新运行本脚本继续部署。"
    exit 1
fi

###############################################################################
# 5. 创建 .env 配置文件
###############################################################################
section "配置环境变量"

if [[ -f "${ENV_FILE}" ]]; then
    warn ".env 文件已存在，跳过创建（如需重新配置请删除 ${ENV_FILE}）"
else
    info "开始交互式配置..."
    echo ""

    read -rp "  阿里云 AccessKey ID       : " ALIYUN_ACCESS_KEY
    read -rsp "  阿里云 AccessKey Secret   : " ALIYUN_ACCESS_SECRET
    echo ""
    read -rp "  阿里云 NLS AppKey         : " ALIYUN_NLS_APP_KEY
    echo ""
    
    # 生成随机数据库密码
    POSTGRES_PASSWORD=$(cat /dev/urandom | tr -dc 'a-zA-Z0-9' | fold -w 24 | head -n 1)
    info "已自动生成 PostgreSQL 密码（保存至 .env）"

    cat > "${ENV_FILE}" <<EOF
# ============================================================
# 绍兴方言语音基础设施 — 生产环境配置
# 生成时间: $(date -u +"%Y-%m-%dT%H:%M:%SZ")
# ============================================================

# ASR 提供商
ASR_PROVIDER=aliyun
ALIYUN_ACCESS_KEY=${ALIYUN_ACCESS_KEY}
ALIYUN_ACCESS_SECRET=${ALIYUN_ACCESS_SECRET}
ALIYUN_NLS_APP_KEY=${ALIYUN_NLS_APP_KEY}

# 数据库
POSTGRES_PASSWORD=${POSTGRES_PASSWORD}

# 应用
ENABLE_CACHE=True
ENABLE_DEDUP=True
EOF
    chmod 600 "${ENV_FILE}"
    info ".env 文件已创建: ${ENV_FILE}"
fi

###############################################################################
# 6. 创建必要目录
###############################################################################
section "初始化目录结构"

mkdir -p \
    "${PROJECT_DIR}/fangyan_mvp/logs" \
    "${PROJECT_DIR}/fangyan_mvp/data/collected" \
    "${PROJECT_DIR}/fangyan_mvp/data/metrics" \
    "${PROJECT_DIR}/fangyan_mvp/data/samples" \
    "${PROJECT_DIR}/fangyan_mvp/models"

# 初始化 collected/labels.jsonl（若不存在）
LABELS_FILE="${PROJECT_DIR}/fangyan_mvp/data/collected/labels.jsonl"
if [[ ! -f "${LABELS_FILE}" ]]; then
    touch "${LABELS_FILE}"
    info "创建语料文件: ${LABELS_FILE}"
fi

info "目录初始化完成"

###############################################################################
# 7. 配置防火墙
###############################################################################
section "配置防火墙"

if command -v ufw &>/dev/null; then
    ufw --force enable
    ufw allow 22/tcp    comment 'SSH'
    ufw allow 8000/tcp  comment 'API服务'
    ufw allow 8001/tcp  comment '语料收集页面'
    ufw status verbose
    info "防火墙规则已配置"
else
    warn "ufw 未安装，跳过防火墙配置"
fi

###############################################################################
# 8. 构建并启动 Docker 容器
###############################################################################
section "构建并启动服务"

cd "${PROJECT_DIR}/fangyan_mvp"

info "构建 Docker 镜像（首次构建约需 3-5 分钟）..."
docker compose -f "${COMPOSE_FILE}" --env-file "${ENV_FILE}" build --no-cache

info "启动所有服务..."
docker compose -f "${COMPOSE_FILE}" --env-file "${ENV_FILE}" up -d

# 等待服务就绪
info "等待服务就绪..."
for i in $(seq 1 12); do
    sleep 5
    if curl -sf http://localhost:8000/health &>/dev/null; then
        info "API 服务健康检查通过 ✓"
        break
    fi
    if [[ $i -eq 12 ]]; then
        warn "API 服务启动超时，请手动检查: docker compose logs api"
    fi
done

docker compose -f "${COMPOSE_FILE}" ps

###############################################################################
# 9. 配置 systemd 开机自启
###############################################################################
section "配置开机自启"

SYSTEMD_SERVICE="/etc/systemd/system/fangyan.service"
cat > "${SYSTEMD_SERVICE}" <<EOF
[Unit]
Description=Elderly Dialect Speech Infrastructure
Requires=docker.service
After=docker.service network-online.target

[Service]
Type=oneshot
RemainAfterExit=yes
WorkingDirectory=${PROJECT_DIR}/fangyan_mvp
EnvironmentFile=${ENV_FILE}
ExecStart=/usr/local/lib/docker/cli-plugins/docker-compose -f ${COMPOSE_FILE} --env-file ${ENV_FILE} up -d
ExecStop=/usr/local/lib/docker/cli-plugins/docker-compose -f ${COMPOSE_FILE} --env-file ${ENV_FILE} down
StandardOutput=journal

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable fangyan.service
info "systemd 服务已配置（fangyan.service），开机自动启动"

###############################################################################
# 10. 部署完成摘要
###############################################################################
section "部署完成"

echo ""
echo -e "${GREEN}${BOLD}╔═══════════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}${BOLD}║         绍兴方言语音基础设施 — 部署成功 🎉               ║${NC}"
echo -e "${GREEN}${BOLD}╚═══════════════════════════════════════════════════════════╝${NC}"
echo ""
echo -e "${BOLD}  访问地址：${NC}"
echo -e "  🔌 API 识别服务      http://${PUBLIC_IP}:8000"
echo -e "  📊 API 健康检查      http://${PUBLIC_IP}:8000/health"
echo -e "  🎤 语料收集页面      http://${PUBLIC_IP}:8001"
echo ""
echo -e "${BOLD}  快速测试：${NC}"
echo '  curl -X POST http://'"${PUBLIC_IP}"':8000/v1/speech/recognize \'
echo '    -F "audio=@test.wav"'
echo ""
echo -e "${BOLD}  常用运维命令：${NC}"
echo "  # 查看所有服务状态"
echo "  docker compose -f ${COMPOSE_FILE} ps"
echo ""
echo "  # 查看自动训练日志"
echo "  docker compose -f ${COMPOSE_FILE} logs -f scheduler"
echo ""
echo "  # 查看训练指标"
echo "  tail -f ${PROJECT_DIR}/fangyan_mvp/data/metrics/train_metrics.jsonl | jq ."
echo ""
echo "  # 查看实时语料收集量"
echo "  wc -l ${PROJECT_DIR}/fangyan_mvp/data/collected/labels.jsonl"
echo ""
echo "  # 手动触发一次训练"
echo "  docker compose -f ${COMPOSE_FILE} exec scheduler \\"
echo "    python scripts/auto_train.py --data data/collected/labels.jsonl"
echo ""
echo "  # 更新代码后重新部署"
echo "  cd ${PROJECT_DIR} && git pull"
echo "  docker compose -f ${COMPOSE_FILE} --env-file ${ENV_FILE} up -d --build api scheduler"
echo ""
echo -e "${YELLOW}  ⚠  .env 文件包含密钥，请勿提交到 Git 或对外暴露：${NC}"
echo "     ${ENV_FILE}"
echo ""
