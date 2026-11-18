# 部署手册（EdgeOne Pages）

线上跑的是**离线演示版**：把真实运行录下来的问答做成静态数据，前端回放。

访客看到的是完整界面、真实回答、真实证据与图谱、真实的耗时和 token 数——
但这些数据是提前录好的，**不再调用模型**。所以不需要服务器、数据库和模型，
一个纯静态托管就够。

---

## 一、为什么部署静态版

| | 静态演示版 | 真服务（Neo4j + 模型） |
|---|---|---|
| 打开速度 | 秒开（CDN） | 首次要加载模型，十几秒 |
| 可用性 | 不会挂 | 机器/进程/数据库任一环节出问题就不可用 |
| 成本 | ¥0 | 4 核 8G 起，¥400–600/年 |
| 备案 | 平台默认域名不需要 | 国内节点绑域名必须备案 |
| 限制 | 只能点录制好的问题 | 可自由提问 |

简历/作品集场景下，"点开就能看到"比"能自由提问"更重要。
真要展示自由提问，面试时用本机跑一遍更有说服力。

---

## 二、生成部署包

先在本机把服务跑起来（需要 Neo4j + API + 模型），然后录数据。

```bash
# 1) 录真实问答
python scripts/export_demo_fixtures.py     # 16 条问答 + 首页统计 + 实体 + 识药结果
python scripts/fix_demo_nodes.py           # 统一节点命名、生成图谱搜索索引
python scripts/export_demo_media.py        # 抽出被引用的图片（约 1.8 MB，72 张）

# 2) 构建静态包
cd frontend
npm run build:demo                         # → dist-demo/
```

产物大小：**约 3.4 MB / 115 个文件**。

> 想换问题：改 `scripts/export_demo_fixtures.py` 里的 `QUESTIONS` 列表，重跑上面三条命令。
> `demo/index.json` 与页面上的示例按钮会自动跟着更新。

---

## 三、部署到 EdgeOne Pages

控制台：<https://console.cloud.tencent.com/edgeone/makers>

### 方式 A：导入 Git 仓库（推荐，改了自动重新部署）

1. 代码已经在 GitHub 上（`zhipeng-anewl/tcmqa`）
2. 控制台 → 新建项目 → **导入 Git 仓库** → 授权并选择该仓库
3. 构建配置填：

   | 项 | 值 |
   |---|---|
   | 根目录 | `frontend` |
   | 构建命令 | `npm ci && npm run build:demo` |
   | 输出目录 | `dist-demo` |

4. 部署，拿到平台分配的访问地址

### 方式 B：直接上传（不想连 Git 时最快）

1. 把 `frontend/dist-demo` 整个目录打成 zip
2. 打开 <https://makers.edgeone.link/drop>，拖进去
3. 几秒后拿到地址

缺点：以后更新要手动重传。

---

## 四、加速区域与备案（重要）

EdgeOne Pages 的第一个坑就在这里，先看清楚再决定：

| 加速区域 | 国内访问 | 需要什么 |
|---|---|---|
| **不含中国大陆** | 平台默认域名在国内会返回 **401** | 无需备案，但国内打不开 |
| **中国大陆** | 正常 | 必须**绑定已备案的自定义域名** |

也就是说：**想让国内的人打开，最终还是要一个备案过的域名**，这一步绕不过去。
平台分配的默认子域名只能用于海外访问，或者短期预览。

### 备案流程（约 2–3 周）

1. 买域名（¥30–80/年）
2. 腾讯云控制台 → 备案 → 提交主体信息（身份证 + 手机核验）
3. 腾讯云初审 1–2 个工作日
4. 管局审核 5–20 个工作日
5. 通过后：EdgeOne 项目 → 域名管理 → 绑定自定义域名 → CNAME 解析

证书由平台自动签发与续期，不用自己处理。

### 备案期间怎么办

- 用 GitHub Pages 之类免备案托管先顶着（国内访问不稳但多数能开）
- 或者在简历上直接放：仓库地址 + 演示视频

---

## 五、更新线上版本

```bash
# 改了问题或回答措辞
python scripts/export_demo_fixtures.py
cd frontend && npm run build:demo
git add -A && git commit -m "update demo" && git push
```

Git 方式接好之后，push 就会自动重新构建部署。

---

## 六、常见问题

**构建失败：找不到 `demo/index.json`**
`frontend/demo-public/demo/` 没提交。检查 `git ls-files frontend/demo-public | head`。

**页面能打开，但图片全是裂图**
演示数据里的图片地址是后端风格的 `/media/...`。部署在子路径时必须补 base 前缀，
`src/demo/index.js` 里的 `withBase()` 负责这件事；如果改了部署路径，检查 `VITE_BASE`。

**页面空白，控制台报 404 一堆 JS**
部署在子路径（如 `/<repo>/`）却没设 `VITE_BASE`。本地验证：
```bash
VITE_BASE=/tcmqa/ npm run build:demo
```

**输入没录过的问题怎么答**
会提示"这是离线演示版"，并列出可点击的示例——不假装能答，这是有意设计。

**想让访客自由提问**
那就得回到真服务：Neo4j + API + 模型，一台 4 核 8G 的服务器起步，
国内还要备案域名。成本与运维复杂度都会上一个量级。
