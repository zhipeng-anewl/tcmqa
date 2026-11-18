#!/usr/bin/env bash
# 服务器上一键部署。放在 deploy/ 目录下执行：
#   bash deploy.sh
#
# 前置：项目已上传到服务器（git clone 或 rsync），deploy/ 下已有
#   .env（从 .env.example 复制并填好）、backup/neo4j.dump、data/index、data/images
set -euo pipefail

cd "$(dirname "$0")"

red()   { printf '\033[31m%s\033[0m\n' "$*"; }
green() { printf '\033[32m%s\033[0m\n' "$*"; }
gray()  { printf '\033[90m%s\033[0m\n' "$*"; }

echo ""
echo "=== 部署前检查 ==="

command -v docker >/dev/null 2>&1 || { red "没装 docker，先执行：curl -fsSL https://get.docker.com | sh"; exit 1; }
docker compose version >/dev/null 2>&1 || { red "没装 docker compose 插件（需要 Docker Compose v2）"; exit 1; }

if [ ! -f .env ]; then
  cp .env.example .env
  red "已生成 deploy/.env，请先填好 DEEPSEEK_API_KEY / NEO4J_PASSWORD / SITE_ADDRESS 再重跑"
  exit 1
fi

if ! grep -qE '^DEEPSEEK_API_KEY=sk-' .env; then
  red "deploy/.env 里的 DEEPSEEK_API_KEY 还是占位符"
  exit 1
fi

DUMP=$(ls backup/*.dump 2>/dev/null | head -n 1 || true)
if [ -z "$DUMP" ]; then
  red "deploy/backup 下没有 neo4j dump。本机执行 scripts/export_deploy.ps1 生成后上传"
  exit 1
fi

for d in data/index data/images; do
  [ -d "$d" ] || { red "缺少 $d，问答会起不来（索引）或没有图片（降级）"; exit 1; }
done

MEM_MB=$(awk '/MemTotal/ {printf "%d", $2/1024}' /proc/meminfo)
if [ "$MEM_MB" -lt 3500 ]; then
  red "内存只有 ${MEM_MB}MB，Neo4j 1G 堆 + Python 模型大概率 OOM，建议 4G 及以上"
fi

TOTAL=$(du -sm data backup media 2>/dev/null | awk '{s+=$1} END {print s+0}')
green "检查通过（数据约 ${TOTAL}MB / 内存 ${MEM_MB}MB）"

echo ""
echo "=== 构建并启动（首次 5-10 分钟，主要在下依赖） ==="
docker compose -f docker-compose.prod.yml up -d --build

echo ""
echo "=== 等待服务就绪 ==="
for i in $(seq 1 60); do
  if curl -fsS "http://127.0.0.1:8000/api/health" >/dev/null 2>&1; then
    green "API 已就绪"
    break
  fi
  sleep 5
  printf '.'
done
echo ""

docker compose -f docker-compose.prod.yml ps
echo ""
SITE=$(grep -E '^SITE_ADDRESS=' .env | cut -d= -f2-)
if [ "$SITE" = ":80" ] || [ -z "$SITE" ]; then
  IP=$(curl -fsS --max-time 5 https://api.ipify.org 2>/dev/null || echo "服务器IP")
  green "打开 http://${IP} 验收"
else
  green "打开 https://${SITE} 验收（首次申请证书约 10 秒）"
fi
gray "看日志：docker compose -f docker-compose.prod.yml logs -f api"
