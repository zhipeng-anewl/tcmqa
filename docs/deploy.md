# 部署到腾讯云

目标：让别人通过一个网址打开问答页面。

部署件都在 `deploy/` 目录，服务器上只需要 `cd deploy && bash deploy.sh`。

---

## 一、买什么

### 配置依据（实测，不是估算）

| 组件 | 实测占用 |
|---|---|
| API 进程（两个模型都加载后） | **约 1.7 GB** 私有内存 |
| Neo4j（1G 堆 + 512M 页缓存） | 约 0.4–1.5 GB |
| 系统 + Docker | 约 0.5 GB |

| 方案 | 配置 | 价格（约） | 说明 |
|---|---|---|---|
| **推荐** | 4 核 8G | ¥100–120/月 | 有余量，构建阶段也不容易 OOM |
| 勉强 | 2 核 4G | ¥50–70/月 | `deploy.sh` 会检查内存；构建时建议临时加 swap |
| 不可用 | 2 核 2G | — | 模型加载不起来 |

> 价格随活动波动，以[轻量应用服务器控制台](https://cloud.tencent.com/product/lighthouse)为准。
> 新用户首年常有 3–5 折，但要注意**续费价**。

购买选项：

- 地域：国内节点（上海 / 广州 / 北京），访问快但绑域名要备案
- 镜像：**Ubuntu 22.04 LTS**
- 系统盘：默认 80G 够用（镜像约 5G + 数据约 0.3G）
- 带宽：3–5 Mbps 够（首屏约 400KB）

---

## 二、开放端口

轻量控制台 →「防火墙」，只需要三条：

| 端口 | 用途 |
|---|---|
| 22 | SSH |
| 80 | Caddy 入口（`SITE_ADDRESS=:80` 时用它验收） |
| 443 | 有域名后 HTTPS |

生产 compose **不会**把 8000、7474、7687 暴露到公网——API 只绑 `127.0.0.1`，Neo4j 在容器内网，外部统一走 Caddy。

---

## 三、本机准备部署包

```powershell
# 项目根目录
powershell -ExecutionPolicy Bypass -File .\scripts\export_deploy.ps1 -SkipModels
```

产出（`deploy/` 下）：

| 路径 | 内容 | 大小（实测） |
|---|---|---|
| `backup/neo4j.dump` | 图谱 | **64.6 MB** |
| `data/index/` | 向量 + BM25 索引 | 11 MB |
| `data/images/` | 药材封面与图库缩略图 | 40 MB |
| `data/*.json` | 中文病名映射等运行期数据 | < 1 MB |
| `data/cache/hf/` | 模型权重 | 1.5 GB（`-SkipModels` 可跳过） |
| `media/mol/` | 分子结构图 | 168 MB（`-SkipMol` 可跳过） |

**关于模型缓存**：跳过的话，服务器首次启动会自己从 `hf-mirror.com` 下载约 700MB，之后落在数据卷里不再重复下载。上传快、首启慢；传了则相反。按网络情况选。

> 脚本会**自动停掉本机 Neo4j 再导出、导完重新拉起**，因为 `neo4j-admin dump` 要求数据库离线。

---

## 四、上传

总共约 **120 MB**（不含模型缓存）。

```bash
# 代码（在开发机的 WSL / Git Bash 里执行）
rsync -avz --progress \
  --exclude 'data/cache' --exclude 'frontend/node_modules' \
  --exclude 'frontend/dist' --exclude '.git' --exclude '__pycache__' \
  ./ root@<服务器IP>:/opt/tcmqa/

# 部署数据
rsync -avz --progress \
  deploy/data deploy/backup \
  root@<服务器IP>:/opt/tcmqa/deploy/
```

如果用 `-SkipModels` 跳过了模型，就没有 `deploy/media`，上面第二条命令照抄即可。

---

## 五、服务器上配置

### 1. 装 Docker

```bash
ssh root@<服务器IP>
curl -fsSL https://get.docker.com | sh
systemctl enable --now docker

# 国内拉镜像慢的话配个加速器
mkdir -p /etc/docker
cat > /etc/docker/daemon.json <<'EOF'
{ "registry-mirrors": ["https://mirror.ccs.tencentyun.com"] }
EOF
systemctl restart docker
```

### 2. 填环境变量

```bash
cd /opt/tcmqa/deploy
cp .env.example .env
vim .env
```

必填三项：

```ini
DEEPSEEK_API_KEY=sk-你的key        # 建议单独申请一张，设消费限额
NEO4J_PASSWORD=换成强密码          # 首次初始化后别再改
SITE_ADDRESS=:80                   # 先验收；有域名后改成你的域名
```

可选（成本控制，默认已开）：

```ini
RATE_LIMIT_PER_MINUTE=6            # 单 IP 每分钟问答次数，0 关闭
DAILY_CHAT_LIMIT=800               # 全站每日上限，0 不限额
```

### 3. 一键部署

```bash
bash deploy.sh
```

脚本会依次做：检查 docker / 检查 `.env` 是否填了真 key / 检查 dump 与索引是否就位 / 检查内存 / 构建并启动 / 轮询健康接口。

首次构建 **5–10 分钟**（下载 torch CPU 版与 Python 依赖）。

### 4. 图谱是怎么进去的

不需要手动导入。compose 里有个 `neo4j-init` 一次性容器：

```
neo4j-init（读 /backup/neo4j.dump → 写入 neo4j_data 卷 → 退出）
        ↓ service_completed_successfully
neo4j（用同一个卷启动，库里已经有数据）
        ↓ service_healthy（cypher-shell 真跑一条查询）
api（连上去）
```

因为 `neo4j-admin database load` 要求数据库离线，所以单独用一个容器在 neo4j 启动前完成，而不是塞进 entrypoint。

验证：

```bash
docker compose -f docker-compose.prod.yml exec neo4j \
  cypher-shell -u neo4j -p '你的密码' "MATCH (n) RETURN count(n) AS nodes"
# 期望：32167
```

---

## 六、验收

浏览器打开 `http://<服务器IP>`（80 端口，走 Caddy）。

也可以直接探接口：

```bash
curl http://<服务器IP>/api/health
```

> 第一次提问会慢：API 在首次请求时加载模型（如果没传缓存，还要先下载 700MB）。之后重启从数据卷读取，快很多。

---

## 七、绑域名 + HTTPS

1. 域名控制台加 A 记录：`你的域名 → 服务器公网 IP`
2. `deploy/.env` 里改 `SITE_ADDRESS=你的域名`
3. 重启 Caddy：`docker compose -f docker-compose.prod.yml up -d caddy`

Caddy 会自动申请并续期 Let's Encrypt 证书，直接访问 `https://你的域名`。

**注意** `deploy/Caddyfile` 里的 `flush_interval -1`：这是让流式回答逐字输出的关键。少了它，回答会攒成一大段一次性蹦出来。

### ICP 备案

国内服务器绑域名**必须备案**：

1. 腾讯云控制台 →「备案」→ 提交主体信息（身份证 + 手机核验）
2. 腾讯云初审：1–2 个工作日
3. 管局审核：约 5–20 个工作日

备案期间用 `http://IP` 直接演示，不影响。备案通过后再切域名。

---

## 八、日常运维

```bash
cd /opt/tcmqa/deploy

# 看日志
docker compose -f docker-compose.prod.yml logs -f api

# 更新代码后重建
git pull && docker compose -f docker-compose.prod.yml up -d --build api

# 资源占用
docker stats --no-stream

# 备份图谱
docker compose -f docker-compose.prod.yml exec neo4j \
  neo4j-admin database dump neo4j --to-path=/data/backup
```

---

## 九、排错

**构建时容器被杀（exit 137）**
内存不足。加 swap：

```bash
fallocate -l 4G /swapfile && chmod 600 /swapfile
mkswap /swapfile && swapon /swapfile
```

**回答不是逐字出现，而是几秒后一次性出来**
反代缓冲了。确认走的是 `deploy/Caddyfile`（带 `flush_interval -1`），并且没有在它前面再套一层会缓冲的代理。

**api 一直 unhealthy**
看 `docker compose -f docker-compose.prod.yml logs api`：

- `.env` 里 `NEO4J_URI` 写成 `localhost` 了（容器内要用 `bolt://neo4j:7687`，compose 已自动注入）
- 模型下载失败：检查服务器出网和 `HF_ENDPOINT`
- 索引缺失：`deploy/data/index` 没传上去

**neo4j-init 失败，neo4j 起不来**
`deploy/backup/neo4j.dump` 没传或文件名不对。看 `docker compose ... logs neo4j-init`。
确认要重来时：`docker compose -f docker-compose.prod.yml down -v` 清卷再跑。

**图片全 404**
`deploy/data/images` 没传。检查 `ls /opt/tcmqa/deploy/data/images/covers | head`。

**改了 NEO4J_PASSWORD 后连不上**
密码只在**首次初始化**时写进库。已经初始化过再改 `.env`，容器里的库还是旧密码——要么改回去，要么 `down -v` 重来（数据会从 dump 重新导入，所以是安全的）。

---

## 十、成本

| 项 | 费用 |
|---|---|
| 轻量 4C8G | ¥100–120/月（首年常有优惠） |
| 域名 | ¥30–80/年 |
| 备案 | 免费 |
| LLM API | ¥0.006 / 次（DeepSeek） |
| 流量 | 轻量自带月流量包，个人演示够用 |

成本失控的主要风险是**别人刷你的 LLM key**，所以 `.env` 里默认开了 `RATE_LIMIT_PER_MINUTE` 与 `DAILY_CHAT_LIMIT`，并且建议用一张单独的、设了限额的 key。

---

## 附：不买服务器的临时方案

只想让人看一眼的话，本机跑着 + 内网穿透，零成本：

```powershell
.\start.ps1
# 另开一个窗口
cloudflared tunnel --url http://127.0.0.1:8000
# 输出的 https://xxx.trycloudflare.com 就能发出去
```

限制：电脑关了就失效，本机 Neo4j 必须一直开着。适合面试时现场演示，不适合写进简历当长期链接。
