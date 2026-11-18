# 上传 GitHub 前的安全审查

审查时间：2026-11-18　范围：全仓库（不含 `node_modules`、`dist`、`data/cache`）

> 本文是审查当时的快照。之后部署方案改为 EdgeOne Pages 静态演示版，
> `deploy/` 目录与服务器部署相关脚本已从仓库移除，文中提到的那些路径不再存在；
> 密钥、依赖、路由权限这几部分的结论仍然有效。

## 结论摘要

| 检查项 | 结果 | 处置 |
|---|---|---|
| 硬编码密钥 | ✅ 未发现（11 处命中全是占位符或 `localhost`） | 无需处理 |
| `.env` 被 Git 追踪 | ✅ 不会（已用 `git check-ignore -v` 实证） | 无需处理 |
| 依赖已知漏洞 | ⚠️ 前端 13 个（12 个仅构建期）、Python 1 个（传递依赖） | 建议升级 echarts |
| 受保护路由的权限检查 | ⚠️ **全部无身份认证**（设计如此）+ 限流已实现 | 需确认可接受 |
| 其他（XSS / 路径穿越 / 错误泄露） | ✅ XSS、路径穿越安全；⚠️ 错误信息回传客户端 | 建议修复 |

**可以上传，但建议先做 3 处小改动（见文末「修复清单」）。**

---

## 一、密钥与凭据

扫描正则：`sk-*`、`api_key=`、`password=`、`bolt://*`、`neo4j/<pwd>`。
命中 11 处，逐条确认：

| 文件 | 内容 | 判定 |
|---|---|---|
| `.env.example:3`、`deploy/.env.example:6` | `sk-xxxxxxxx…` | 占位符 ✅ |
| `docker-compose.yml`、`deploy/docker-compose.prod.yml`、`settings.py`、`config.py`、`view_graph.py`、`docs/deploy.md` | `bolt://localhost:7687` / `bolt://neo4j:7687` | 连接串，无凭据 ✅ |
| `deploy/docker-compose.prod.yml:25` | `neo4j/neostore` | 这是路径，误命中 ✅ |

**历史遗留文件已清理**：
`config.py:25` 与 `view_graph.py:9` 都是 `os.getenv("NEO4J_PASSWORD", "")`，没有硬编码密码。

**`.env` 里是真密钥**（`DEEPSEEK_API_KEY`，35 位），但：
- 被 `.gitignore` 排除（实证见下）
- 仓库是**新建的**，该文件从未进入过任何提交

> 如果这个项目目录此前发给过别人、或同步到过网盘，建议到 DeepSeek 控制台**轮换一次 key**，成本几秒钟。

---

## 二、`.env` 是否会被 Git 追踪

没有依赖"看规则猜"，直接初始化仓库用 `git check-ignore -v` 验证：

```
✓ .gitignore:9:.env                    .env
✓ .gitignore:39:deploy/.env            deploy/.env
✓ .gitignore:16:data/app.db            data/app.db
✓ .gitignore:14:data/cache/            data/cache
✓ .gitignore:40:deploy/backup/         deploy/backup/neo4j.dump
✓ .gitignore:23:frontend/node_modules/ frontend/node_modules
✓ .gitignore:24:frontend/dist/         frontend/dist
✓ .gitignore:45:frontend/dist-demo/    frontend/dist-demo
✓ .gitignore:35:.tmp-build/            .tmp-build
```

`git add -A` 后复查暂存区：

- 暂存 **292 个文件，共 3.35 MB**
- 敏感文件命中 **0**（无 `.env` / `.db` / `.dump` / `node_modules` / `dist`）
- 无单文件超过 1 MB

会被提交的数据文件只有：`disease_zh.json`、`ingredient_zh.json`、`golden_set.jsonl`、`vision_eval.json`、`vision_text_eval.json`（都是评测与映射数据，无隐私）。

---

## 三、依赖已知漏洞

### 前端（npm audit，官方源）

```
13 vulnerabilities (1 moderate, 12 high)
```

| 包 | 严重度 | 类型 | 影响 |
|---|---|---|---|
| **echarts <6.1.0** | moderate | **生产依赖** | XSS（GHSA-fgmj-fm8m-jvvx），修复版本 6.1.0（跨大版本） |
| vite / unplugin-* / picomatch / tinyglobby / fdir / unctx / unimport / @nuxt/kit | high | 开发依赖 | 仅构建期，**不进发布产物** |

判断依据：`package.json` 的 `dependencies` 只有 `echarts`、`element-plus`、`vis-network`、`vue` 四个；12 个 high 全在 `devDependencies` 及其传递依赖里，最终打包进 `dist` 的代码不含它们。

**echarts 那个 XSS 的实际风险很低**：图表数据来自本项目自己的 `/api/metrics`，不接受用户输入，攻击面接近于零。但仍建议升级。

### Python（pip-audit，按 `requirements.txt` 解析）

```
Found 17 known vulnerabilities in 1 package
```

| 包 | 当前 | 漏洞数 | 修复版本 |
|---|---|---|---|
| filelock | 4.1.0 | 17 | 4.2.1 |

`filelock` 是 `torch`/`huggingface` 的传递依赖，只用于模型文件加锁，不处理外部输入。

> 注意：直接审计开发机的整个 conda 环境会报 28 个包（jupyter、streamlit、pillow 等），
> 那些**不属于本项目依赖**，部署镜像里根本不会安装。以 `requirements.txt` 的结果为准。

---

## 四、路由权限检查

### 现状：全部 23 个路由都没有身份认证

| 模块 | 路由 | 敏感度 |
|---|---|---|
| chat | `POST /api/chat`、`POST /api/chat/stream` | 🔴 消耗 LLM 费用 |
| chat | `GET /api/sessions`、`GET /api/sessions/{id}/messages` | 🟡 会话内容 |
| chat | `POST /api/feedback`、`GET /api/feedback/stats` | 🟢 |
| graph | `POST /api/graph/cypher` | 🔴 任意只读 Cypher |
| graph | `GET /api/graph/overview`、`/node`、`POST /neighbors`、`GET /search` | 🟢 公开数据 |
| health | `GET /api/metrics`、`/metrics/recent`、`/traces/{trace_id}` | 🟡 运营数据 |
| media | `GET /api/media/*` | 🟢 |
| vision | `POST /api/vision/search-image`、`GET /search-text` | 🟡 计算资源 |
| health | `GET /api/health` | 🟢 |

**这是有意设计**：本项目是公开演示，没有账号体系。但必须清楚它的含义——
任何人拿到链接就能提问（烧你的 API 额度），也能读任意 `session_id` 的对话。

### 已有的防线

1. **限流已实现并生效**（`main.py:101-130`）：覆盖 `/api/chat`、`/api/vision`、`/api/graph/cypher`，
   按 IP 每分钟 + 全站每日双阈值；默认关闭，`docker-compose.prod.yml` 里打开（6 次/分、800 次/天）。
2. **Cypher 入口有护栏**（`graph.py:141-147`）：走同一套 `CypherGuard`（去字面量 → 结构检查 → 强制 LIMIT → 只读路由 + 超时）。
3. **媒体接口无路径穿越**：`herb_id`/`ingredient_id` 只作为 Cypher 参数（`{id: $id}`），
   文件路径取自数据库字段而非 URL；`index` 是整数并做越界检查。
4. **前端无 XSS**：全项目只有一处 `v-html`（`CiteText.vue`），且先 `escapeHtml` 再拼装，
   项目里没有 `innerHTML`/`eval`/`new Function`。

### 需要确认的两点

**① CORS 默认放开**

`settings.py:79` 的 `cors_origins` 默认是 `"*"`。公开演示可接受，但有域名后建议收紧到实际域名。

**② 异常处理把内部错误回传客户端**

`main.py:138`：

```python
content={"detail": "服务器内部错误", "error": str(exc)[:300]}
```

`str(exc)` 可能包含数据库地址、文件绝对路径、依赖内部信息。生产环境应去掉 `error` 字段，改为只写日志。

---

## 五、其他发现

### 本机绝对路径曾写死在代码里（**已修复**）

| 文件 | 原写法 | 现状 |
|---|---|---|
| `tcmqa/settings.py` | `herb_image_root` 默认值为本机绝对路径 | 改为空串，由 `HERB_IMAGE_ROOT` 配置 |
| `scripts/build_images.py` | 常量写死本机路径 | 改读 `settings`，缺配置时明确报错 |
| `scripts/export_demo_media.py` | 同上 | 同上 |
| `scripts/probe_images.py` | 同上 | 同上 |

不是密钥，但有三个问题：泄露本机目录结构、别人 clone 后跑不通、Windows 路径在 Linux 上无效。
修复后仓库里不再出现任何本机绝对路径。
建议改成环境变量 + 相对路径默认值。

### 会话 ID 不可猜

`session_id` 由 `uuid4().hex` 生成（128 位随机），配合无鉴权的 `/api/sessions/{id}/messages`
属于「知道链接才能读」的模型。风险可接受，但要意识到它是**分享即授权**。

---

## 六、修复清单

### 建议上传前做（约 10 分钟）

1. **去掉响应里的 `str(exc)`**（`main.py:138`）
   改成 `content={"detail": "服务器内部错误"}`，详细错误只进日志。

2. **把写死的本机路径改成环境变量**（`settings.py:91-92`）
   默认值改成空串或相对路径，文档里说明怎么配。

3. **升级 echarts 到 6.1.0**（或明确接受风险）
   如果不升级，至少在 README 里写一句"图表数据源不可控时需评估 XSS"。
   升级是跨大版本，需要重跑一遍图表页验证。

### 上线后可以再处理

4. 生产环境把 `CORS_ORIGINS` 收紧到实际域名
5. `requirements.txt` 加 `filelock>=4.2.1`
6. `npm audit fix`（非 `--force`）清掉构建期漏洞

### 不需要处理

- `.env` 与密钥：已确认不会进仓库
- XSS、路径穿越、SQL/Cypher 注入：已确认防护到位
- 无身份认证：公开演示的合理选择，靠限流 + 成本上限兜底

---

## 附：复审命令

```bash
# 前端依赖
cd frontend && npm audit --registry=https://registry.npmjs.org

# Python 依赖（要把注释去掉，否则解析器在 Windows 上按 GBK 读会报错）
grep -v '^\s*#' requirements.txt | grep -v '^$' > /tmp/req.txt
pip-audit -r /tmp/req.txt

# 密钥扫描
grep -rnE 'sk-[A-Za-z0-9]{16,}|(password|api_key)\s*=\s*["'\''][^"'\'']{8,}' \
  --include='*.py' --include='*.js' --include='*.vue' --include='*.yml' \
  --exclude-dir=node_modules --exclude-dir=dist --exclude-dir=cache .

# 确认 .env 不会被提交
git check-ignore -v .env deploy/.env
```
