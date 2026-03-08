#!/bin/bash
set -e

echo "=== 老年方言语音基础设施 — 一键部署 ==="

# 检查 Docker
if ! command -v docker &> /dev/null; then
    echo "❌ 未安装 Docker，请先安装 Docker Desktop"
    exit 1
fi

# 检查 .env 文件
if [ ! -f ../.env ]; then
    echo "❌ 缺少 .env 文件，请先复制并填写："
    echo "   cp .env.example .env"
    exit 1
fi

# 检查关键配置
source ../.env
if [ -z "$ALIYUN_ACCESS_KEY" ] || [ "$ALIYUN_ACCESS_KEY" = "your_access_key_here" ]; then
    echo "❌ 请在 .env 中填写 ALIYUN_ACCESS_KEY"
    exit 1
fi

echo "▶ 构建 Docker 镜像..."
docker-compose build

echo "▶ 启动服务..."
docker-compose up -d

echo "▶ 等待服务启动（15秒）..."
sleep 15

echo "▶ 健康检查..."
if curl -sf http://localhost:8000/health > /dev/null; then
    echo ""
    echo "✅ 部署成功！"
    echo "   API 文档: http://localhost:8000/docs"
    echo "   健康检查: http://localhost:8000/health"
else
    echo "❌ 健康检查失败，查看日志："
    docker-compose logs api --tail=50
    exit 1
fi
