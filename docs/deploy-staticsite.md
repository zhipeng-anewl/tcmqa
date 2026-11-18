# 部署演示版（纯静态，零服务器）

给自己做一个**能写进简历的在线链接**，但不用租服务器、不用备案、不会挂。

## 这是什么

把真实运行的结果录成静态 JSON，前端回放：

```
本机跑真服务 → 录 16 条问答 → 前端打包成静态站点 → 传到 CDN
```

访客点开链接，看到的是一个**完全真实**的问答界面：真实回答、真实证据、
真实的 Cypher 语句、真实的图谱、真实耗时和 token 数——只是这些数据是提前录好的，
不会再调用模型。

## 优点与局限（先说清楚）

| 优点 | 局限 |
|---|---|
| 秒开，不用等模型加载 | **只能点录制好的问题**，输入别的话会提示可用示例 |
| 永不挂（CDN 静态托管） | 拍照识药不能真上传图片，只能用文本检索 |
| 零成本、免备案 | 不能证明"现在真的在跑"——但面试时你可以在本机现场跑 |
| 自动 HTTPS、全球加速 | |

页面上有个「离线演示」角标，不冒充实时服务——这点对面试反而加分：
说明你清楚演示环境和生产环境的区别。

## 一、生成演示包

```bash
# 1. 本机把服务跑起来（要有 Neo4j + API）
.\start.ps1

# 2. 录 fixture（16 条问答 + 首页统计 + 节点 + 识药结果）
python scripts/export_demo_fixtures.py
python scripts/fix_demo_nodes.py        # 统一节点命名 + 生成搜索索引
python scripts/export_demo_media.py     # 抽出引用到的图片（约 1.8MB）

# 3. 构建静态包
cd frontend
npm run build:demo                      # 输出到 dist-demo/
```

产物：`frontend/dist-demo/`，**约 3.4MB / 115 个文件**。

> 想换问题就改 `scripts/export_demo_fixtures.py` 里的 `QUESTIONS` 列表，重跑一遍。
> 每加一条，`demo/index.json` 和示例按钮会自动更新。

## 二、部署到 EdgeOne Pages

### 方式 A：Git 导入（推荐，改了自动重新部署）

1. 把项目推到 GitHub / Gitee（`dist-demo/` 已在 `.gitignore` 里，不用提交）
2. 打开 [EdgeOne Makers 控制台](https://console.cloud.tencent.com/edgeone/makers) → 新建项目 → **导入 Git 仓库**
3. 授权并选择你的仓库
4. 构建配置填：

   | 项 | 值 |
   |---|---|
   | 根目录 | `frontend` |
   | 构建命令 | `npm install && npm run build:demo` |
   | 输出目录 | `dist-demo` |

5. 部署，拿到 `https://xxx.edgeone.app` 之类的地址

平台会自动识别 Vite/Vue 框架，上面几项如果预填了就别改。

### 方式 B：直接上传（不想连 Git 时最快）

1. `cd frontend/dist-demo` 打成 zip
2. 打开 [EdgeOne 直接上传](https://makers.edgeone.link/drop)，把 zip 拖进去
3. 几秒后拿到地址

缺点：以后更新要手动重传。

### 自定义域名（可选）

EdgeOne Pages 支持绑定自定义域名并**自动签发免费证书**：
控制台 → 域名管理 → 自定义域名 → 按提示加 CNAME。

国内加速域名同样需要备案；用平台分配的 `edgeone.app` 子域名则不用。

## 三、其他平台（都不花钱）

这个包是纯静态的，任何静态托管都能放：

| 平台 | 命令/操作 | 备注 |
|---|---|---|
| GitHub Pages | 把 `dist-demo` 推到 `gh-pages` 分支 | 需要把 `base` 改成仓库名 |
| Vercel | `vercel --prod`，输出目录填 `dist-demo` | 国内访问一般 |
| Cloudflare Pages | 连仓库，构建命令同上 | 全球快，国内中等 |
| 阿里云 OSS / 腾讯云 COS | 上传后开静态网站托管 | 国内快，需要备案域名 |

⚠️ 部署到**子路径**（如 `https://user.github.io/tcmqa/`）时，
要在 `frontend/vite.config.js` 里加 `base: '/tcmqa/'`，否则资源 404。
EdgeOne / Vercel 的根路径部署不需要。

## 四、更新演示版

改了回答措辞、加了新问题，想刷新线上版本：

```bash
python scripts/export_demo_fixtures.py   # 重新录
cd frontend && npm run build:demo        # 重新构建
git add -A && git commit -m "update demo" && git push
```

Git 方式接好之后，push 就会自动重新部署。

## 五、简历上怎么写

```
项目演示：https://tcmqa-demo.edgeone.app
项目源码：https://github.com/你的账号/tcmqa
演示视频：https://www.bilibili.com/video/xxxxx   ← 强烈建议补一个
```

**为什么建议再加个视频**：

- 静态 Demo 证明「做出来了、能用」，视频证明「真的会跑、能自由提问」
- 视频里可以展示拍照识药（静态版用不了）、随便输入问题、实时流式输出
- 面试官看视频只要 3 分钟，比点开网站慢慢试更高效

录视频时在本机跑真服务，用 OBS 或系统自带录屏，
讲三件事就够：**它解决什么问题 → 架构怎么分层 → 哪几个指标能证明有效**。

## 六、什么时候该换成真服务器

这套方案限制很清楚：**访客不能自由提问**。

如果出现下面任一情况，就该回到 `docs/deploy.md` 用真服务：

- 要把链接放到会被大量访问的地方（技术社区、招聘平台公开主页）
- 面试官明确要自己输入问题试
- 你想展示「实时调用」而不是「回放」

在那之前，静态演示版的性价比高得多：零成本、秒开、不会在半夜挂掉。
