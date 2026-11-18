# Vue3 前端逐文件讲解（面试版）

> **讲解范围**：`frontend/` 全部文件，以及和前端直接相关的后端接口、构建部署、验证脚本。
>
> **使用方法**：第 0 节先背熟，它是整场面试的主线；后面每个文件不用逐字背，
> 记住「这个文件解决什么问题 + 一个关键技术点」即可。带「面试可讲」的句子可以直接说出口。

---

## 0. 先背这一页

### 0.1 30 秒版

> 这是一个 Vue3 + Vite 的前端，服务于中医药知识图谱问答系统。
> 页面有六个平级视图：首页、智能问答、知识图谱、拍照识药、运行指标、关于。
> 问答用 SSE 流式渲染，答案里的证据编号可以点开回溯到原始 Cypher；
> 知识图谱用 vis-network 做力导向可视化，支持按实体搜索、邻域扩展和双击换中心；
> 指标页用 ECharts 按需引入。整个前端没有用 vue-router 和 Pinia，
> 用 hash 路由加三个模块级 reactive store，依赖少、状态流向清晰。

### 0.2 2 分钟版（按数据流讲）

> **入口和视图**：`main.js` 挂载 App，并按需注册 Element Plus。
> `App.vue` 负责视图切换：首页和问答用 `v-show` 保活，因为对话消息存在 `ChatPanel` 内部，
> 卸载会丢；图谱、识药、指标、关于用 `defineAsyncComponent` + `v-if` 懒加载，
> 把 vis-network 和 ECharts 挪出首包。
>
> **路由**：没有引入 vue-router，六个视图都是平级的，用 `stores/ui.js` 管当前视图。
> URL hash 同时承担分享和深链：`#chat?q=问题` 能直接带问题进入问答，`#graph?q=枸杞` 能直接搜实体。
>
> **问答链路**：`ChatPanel.ask()` 先推一条用户消息，再创建一个 `reactive` 的助手消息对象，
> 然后 `fetch('/api/chat/stream')`。这里没有用 `EventSource`，因为 EventSource 只能发 GET，
> 而问题需要 POST。拿到 `ReadableStream` 后用 `TextDecoder(stream: true)` 解码，
> 按 `\n\n` 切 SSE 帧，再解析 `data:` 后面的 JSON。
> 事件按 `meta → plan → retrieval → evidence → token* → citations → done` 分发；
> 每个 token 只改 `msg.text`，Vue 的响应式自动重渲染。
>
> **答案渲染**：`AssistantMessage` 负责气泡、意图标签、证据、Cypher、向量命中、执行轨迹和反馈。
> 首字没回来时显示骨架屏；引用点击会展开证据并滚动高亮。
> `CiteText` 是一个极简 Markdown 渲染器，先 HTML 转义，再拼标题/列表/粗体/行内代码，
> 最后把 `[E1]` 替换成可点击 span——不引第三方库，XSS 面小。
>
> **图谱**：`GraphTab` 把证据翻译成图数据：graph 证据取 `payload`，文档证据用标题补单节点；
> 然后 `utils/graph.js` 把行数据变成节点和边；`GraphCanvas` 只是 vis-network 的封装，
> 负责力导向布局、拖拽缩放、选中和导出 PNG。稳定后关闭物理模拟，避免两个实例常驻吃 CPU。
>
> **图片和指标**：证据里的药名/成分名通过 `/api/media/resolve` 批量换成缩略图，
> 用 `reactive(new Map())` 做前端缓存；点击进入 `Lightbox`，中药可以拉图库。
> 指标页用 ECharts 的按需注册，只引入饼图、柱图和必要的组件。

### 0.3 一张数据流图

```text
用户输入
  │
  ├─ HomeView / VisionPage 的「提问」──► App.handleAsk
  │                                      │ goAsk(q)：切到 chat + 写 hash
  │                                      ▼
  └──────────────────────────────► ChatPanel.ask(q)
                                         │
          POST /api/chat/stream ◄────────┘
                 │ SSE
                 ▼
      meta / plan / retrieval / evidence / token* / citations / done
                 │
                 ▼
        reactive assistant message
          ├─► AssistantMessage：气泡 + 证据 + Cypher + 轨迹 + 反馈
          ├─► graphStore.set(evidence, links)
          │        └─► GraphTab / GraphCanvas（vis-network）
          └─► utils/media.resolveMedia → 缩略图 → Lightbox
```

### 0.4 十条核心设计决策

1. **不用 vue-router**：六个平级视图、无嵌套和参数，hash 足够；少一个依赖，深链反而更简单。
2. **首页/问答保活，其余懒加载**：对话状态在组件内部，必须 `v-show`；重库用异步组件 + `v-if`。
3. **不用 Pinia**：三个模块级 `reactive` store（ui / graph / lightbox）已经覆盖共享状态。
4. **SSE 手写解析**：需要 POST，所以用 `fetch` + `ReadableStream`，不用 `EventSource`。
5. **流式消息必须是 `reactive`**：推入数组后还会继续改它，普通对象改属性不会触发渲染。
6. **AbortController**：清空会话时主动中断流式请求，避免旧请求继续写状态。
7. **引用渲染先转义再拼 HTML**：`CiteText` 不用第三方 Markdown 库，XSS 面可控。
8. **证据 → 图模型分离**：`utils/graph.js` 是纯函数，渲染在 `GraphCanvas`，可单独测试和替换。
9. **大依赖按需 + 拆包**：Element Plus 深层导入、ECharts 按需注册、Vite `manualChunks` 拆 vendor。
10. **非关键失败静默降级**：图片、指标、首页统计失败不影响主流程；关键链路（问答）才弹错误。

---

## 1. 工程入口与配置

### `frontend/package.json`

**做什么**：声明项目元信息、脚本和依赖。

- 脚本：`dev`（Vite 开发服务器）、`build`（生产构建到 `dist`）、`preview`（本地预览构建产物）。
- 运行依赖：`vue`、`element-plus`、`echarts`、`vis-network`。
- 开发依赖：Vite、Vue 插件，以及 `unplugin-auto-import` / `unplugin-element-plus` / `unplugin-vue-components`。

**面试可讲**：
> 依赖分两类：运行时要进产物的只有 Vue、Element Plus、ECharts、vis-network；
> 构建工具都在 devDependencies。Element Plus 最终没有用自动引入插件，而是显式深层导入，
> 因为自动解析器的产物里会混进没用到的组件，包体积不可控。

**可能追问**：`unplugin-*` 还在 package.json 里，但 `vite.config.js` 没使用——这是可以清理的遗留依赖。主动说出来反而显得清楚。

### `frontend/package-lock.json`

**做什么**：锁定整棵依赖树的精确版本，保证 `npm ci`、Docker 构建和同事环境完全一致。

**面试可讲**：
> 这个文件不手改。Dockerfile 用 `npm ci` 而不是 `npm install`，就是因为它要求 lock 文件存在、按 lock 精确安装，构建可复现。

### `frontend/vite.config.js`

**做什么**：Vite 配置，三件事：

1. **开发代理**：`/api`、`/media` 代理到 `http://127.0.0.1:8000`，开发时同源，避开 CORS。
2. **生产输出**：`outDir: 'dist'`，FastAPI 直接托管这个目录。
3. **分包**：`manualChunks` 把 vis-network、ECharts、Element Plus、Vue 分别拆成 vendor chunk。

**关键代码**：
```js
manualChunks(id) {
  if (id.includes('node_modules/vis-network') ...) return 'vendor-graph'
  if (id.includes('node_modules/echarts') ...) return 'vendor-charts'
  if (id.includes('node_modules/element-plus') ...) return 'vendor-element'
  if (id.includes('node_modules/vue')) return 'vendor-vue'
}
```

**面试可讲**：
> 拆分有两个目的：首包不被图谱和图表库拖慢；这两个库很少升级，独立 chunk 的浏览器缓存命中率更高。
> `chunkSizeWarningLimit` 调到 700KB，是因为 vis-network 和 ECharts 本身就大，不是业务代码失控。

**可能追问**：为什么不用 CDN？——部署环境不保证外网；而且 vendor chunk 已经能长期缓存。

### `frontend/index.html`

**做什么**：唯一的 HTML 入口。一个 `#app` 挂载点、一个 `/src/main.js` 模块脚本、favicon。

**面试可讲**：
> 真正的页面结构都在 Vue 组件里，index.html 只负责挂载。SPA 的入口保持最小。

### `frontend/src/main.js`

**做什么**：创建应用、安装 Element Plus、加载全局样式、挂载。

```js
const app = createApp(App)
installElement(app)
app.mount('#app')
```

**关键点**：`style.css` 先引，`element-theme.css` 后引——后者覆盖 Element Plus 的 CSS 变量，顺序不能反。

### `frontend/public/favicon.svg`

**做什么**：站点图标。Vite 会把 `public/` 原样拷到 `dist/`，所以构建后是 `/favicon.svg`。

### `frontend/README.md`

**做什么**：前端开发、构建、目录结构、图谱/图表取舍、Element Plus 接入方式和 CDP 验证说明。

**面试可讲**：
> 我把关键取舍写在 README 里，包括「为什么不用自动引入」「为什么稳定后关物理模拟」
> 「导出 PNG 为什么要过滤 0×0 画布」，这些是代码里看不出原因、但面试官最常问的点。

---

## 2. 全局状态（stores）

### `frontend/src/stores/ui.js`

**做什么**：管理当前视图和 hash 路由。

- `ui = reactive({ tab: 'home' })`：唯一全局视图状态。
- `TABS`：六个视图的 key 和中文名，导航栏直接遍历。
- `parseHash()`：解析 `#chat?q=xxx`，非法 key 回退 `home`。
- `setTab(key, { silent })`：切视图，必要时 `history.replaceState` 写 hash。
- `goAsk(question)`：切到 `chat` 并把问题编码进 hash。
- `syncFromHash()`：首屏恢复视图；如果当前是 chat，返回要自动提问的问题。

**面试可讲**：
> 没有上 vue-router：六个视图完全平级，没有嵌套路由和路由参数，一个 hash 就够。
> 好处是深链简单、刷新不丢当前页面，而且少一个依赖。
> `replaceState` 而不是 `pushState`，是因为视图切换不想污染浏览器后退历史。

**可能追问**：刷新 `#chat?q=...` 会重新提问，可能重复消耗 token。——这是已知边界，可以说「如果做成产品，会改为只恢复历史、不自动重放」。

### `frontend/src/stores/graph.js`

**做什么**：保存当前要展示的图谱证据。

- `evidence` / `links`：对话结束后由 `ChatPanel` 写入。
- `revision`：每次 `set()` 自增，`GraphTab` 监听它触发重绘。
- `reset()`：清空。

**面试可讲**：
> 用 revision 计数而不是深 watch 整个 evidence 数组。证据可能是几十层嵌套对象，
> 深比较成本高；一个整数变化就能可靠触发重绘。

### `frontend/src/stores/lightbox.js`

**做什么**：图片放大层的全局状态和加载逻辑。

- `visible / name / kindText / id / src / strip / activeIndex`。
- `openLightbox(name, info)`：先显示封面，再按需拉图库。
- 只有 `label === 'Herb' && gallery > 1` 才请求 `/api/media/herb/{id}/images`，最多 12 张。
- 图库失败只保留封面，不阻塞。
- `selectLightboxImage` / `closeLightbox`。

**面试可讲**：
> 放大层被很多组件共用（证据缩略图、识药结果、图谱节点），所以状态放全局 store，
> 组件只负责触发和展示。图库是按需加载的，不是所有图片一开始就拉。

---

## 3. 工具与插件

### `frontend/src/api/client.js`

**做什么**：统一 JSON 请求封装。

- `api(path, options)`：默认 `Content-Type: application/json`，非 2xx 抛错，错误信息带状态码和响应前 200 字符。
- `postJSON(path, body)`：POST JSON 的快捷方法。

**面试可讲**：
> 上传接口故意不用它：`multipart/form-data` 的 boundary 必须由浏览器自动生成，
> 一旦手动设 JSON 头，请求就坏了。所以识药上传是直接 `fetch(FormData)`。

### `frontend/src/utils/format.js`

**做什么**：展示格式化。

- `fmtMs`：小于 1 秒显示 `123ms`，否则 `1.2s`；空值显示 `—`。
- `intentLabel`：把后端意图 key 翻译成中文（lookup、relation、aggregate、mechanism、semantic、chitchat、out_of_scope、blocked）。

### `frontend/src/utils/graph.js`

**做什么**：把「一行行证据」翻译成「节点 + 边」的纯数据模型，不含渲染。

关键规则：
1. 字段顺序固定 `herb → ingredient → target → disease`，一行里的实体按顺序连成链。
2. 节点 id 用 `类型:名称`，同一实体跨行出现时自动合并。
3. 边用 `from->to` 去重，避免同一对节点画多条重叠边。
4. 没有明确实体字段的行（例如只有一个 `ingredient` 列），接到锚点实体上。
5. 导出 `TYPE_COLOR` / `TYPE_LABEL` 给画布和图例共用。

**面试可讲**：
> 这一层是纯函数，输入证据、输出 `{nodes, edges}`，不 import vis-network。
> 这样图数据可以单独测，也可以换渲染库而不动业务逻辑。

**可能追问**：如果同一实体的类型不同（比如同名中药和成分）？——节点 id 带类型，所以不会合并错。

### `frontend/src/utils/media.js`

**做什么**：实体名 → 图片信息的缓存与批量解析。

- `mediaCache = reactive(new Map())`：响应式 Map，模板里 `get/has` 也参与依赖追踪。
- `resolveMedia(names)`：去重、跳过已缓存、单次最多 40 个，批量请求 `/api/media/resolve`；缺失也缓存为 `null`，避免重复请求。
- `pickEntityName(e)`：文档证据用 `title`；图谱证据优先 `payload.ingredient`，其次 `payload.herb`。

**面试可讲**：
> 图片不是一条证据一个请求，而是把答案里出现的名称一次性批量解析；
> 负缓存（`null`）也很重要，否则一个没有图的实体每次渲染都会重新请求。

### `frontend/src/plugins/element-components.js`

**做什么**：按组件深层引入 Element Plus，并引入对应样式。

- 每个组件都从 `element-plus/es/components/xxx/index` 引入，而不是从 `element-plus` 整包入口。
- 显式引入 `style/css`，否则组件没有外观。
- 额外导出 `ElMessage` 供函数式调用。

**面试可讲**：
> 如果从整包入口 import，Rollup 无法可靠 tree-shake 掉没用到的组件。
> 按 README 记录，自动引入方案产物约 945KB，改成深层导入后约 162KB，未用组件归零。

### `frontend/src/plugins/element.js`

**做什么**：把实际用到的 8 个 Element 组件注册到全局。

- `ElButton`、`ElEmpty`、`ElInput`、`ElProgress`、`ElSkeleton`、`ElTag`、`ElTooltip`、`ElUpload`。

**面试可讲**：
> 只注册用到的组件。模板里可以直接写 `<el-input>`，但产物里不会出现 `ElTable`、`ElDatePicker` 这些没用的东西。

---

## 4. 应用骨架与视图

### `frontend/src/App.vue`

**做什么**：根组件，负责视图切换、异步加载和全局问答入口。

- `HomeView` 和问答工作台用 `v-show`：对话消息在 `ChatPanel` 内部，卸载会丢。
- 图谱、识药、指标、关于用 `defineAsyncComponent` + `v-if`：切走即卸载，避免两套 Canvas / 图表常驻。
- `handleAsk(question)`：`goAsk()` 切视图并写 hash，`nextTick()` 等 `v-show` 生效后再调用 `chatRef.ask()`。
- `onMounted` 调 `syncFromHash()`，支持 `#chat?q=` 直接提问；监听 `hashchange`。
- 卸载时移除监听。

**面试可讲**：
> 这里最关键的是「保活还是卸载」的取舍：问答必须保活，否则切到图谱再回来消息没了；
> 图谱和图表必须卸载，否则两个 vis-network 实例、两套 ECharts DOM 同时在跑。
> 异步组件还把这两个大依赖从首包挪走了。

**可能追问**：为什么是 `nextTick`？——`v-show` 刚切过来时容器高度可能还是 0，立即滚动到底部会算错位置。

### `frontend/src/views/HomeView.vue`

**做什么**：门户首页。

- 顶部 Hero：标题、搜索框、五个示例问题。
- 六个规模卡片：中药、化学成分、靶点蛋白、疾病、关联关系、药材图片，数据来自 `/api/graph/overview` 和 `/api/vision/stats`。
- 六个能力卡片：意图路由、Text2Cypher、混合检索、拍照识药、证据可溯、成本可测。
- 提交搜索框或点示例，`emit('ask', text)` 交给 App。
- 点统计卡片 `setTab('graph')`。

**面试可讲**：
> 首页不是静态介绍页，数字全部来自图谱实时统计；后端没起来时两个请求都静默失败，
> 页面仍然可用，只是显示 `—`。这是「非关键依赖降级」。

### `frontend/src/views/GraphPage.vue`

**做什么**：知识图谱全宽页，一个薄壳：页头 + `<GraphTab :active="true" :deep-link="true" />`。

**面试可讲**：`deep-link` 让这个实例响应 `#graph?q=`，而问答页侧栏的实例不跟着整句问题自动搜索。

### `frontend/src/views/VisionPage.vue`

**做什么**：拍照识药全宽页，包一层 `<VisionTab :active="true" @ask="$emit('ask', $event)" />`，把「追问」向上转给 App。

### `frontend/src/views/MetricsPage.vue`

**做什么**：运行指标页，包 `<MetricsTab :active="true" />`。

### `frontend/src/views/AboutPage.vue`

**做什么**：关于页，包 `<AboutTab :active="true" />`。

**面试可讲（四个 view）**：
> 页面组件只负责页头和容器，真正的交互在 Tab 组件里。
> 这样同一个 `GraphTab` 既能放在全宽页面，也能放在问答页的窄侧栏，只靠 props 控制。

### `frontend/src/components/TopBar.vue`

**做什么**：品牌、主导航、服务状态。

- 导航遍历 `TABS`，点击 `setTab`。
- `onMounted` 请求 `/api/graph/overview`：拿到节点数并判断服务在线。
- 状态三态：检测中 / 服务在线 / 离线。

**面试可讲**：
> 这里只探一次 overview，不轮询。状态为「离线」表示图谱不可达，不只是进程没起来。
> 首页和页脚都保持轻量，主要状态集中在这里。

### `frontend/src/components/AppFooter.vue`

**做什么**：免责声明、数据来源、技术栈、版权年份。

**面试可讲**：中医药场景必须在所有页面可见地声明「不构成诊疗建议」，这是产品边界，不是装饰。

---

## 5. 对话链路

### `frontend/src/components/ChatPanel.vue`

**做什么**：对话状态机 + SSE 客户端，是整个前端最核心的组件。

**状态**：
- `messages`：消息数组，用户消息和助手消息共用一个列表。
- `sessionId`：后端会话 id。
- `streaming`：是否正在流式输出，控制输入框禁用。
- `controller`：当前请求的 `AbortController`。

**`ask(question)` 流程**：
1. 去空白、防重复提交。
2. 推入用户消息。
3. 创建 **`reactive`** 的助手消息对象（文字、chips、traceId、detail、finished 等）。
4. 调 `streamAnswer`。
5. `finally` 里置 `finished`、解除 streaming、滚到底部。

**SSE 解析**：
```js
const res = await fetch('/api/chat/stream', { method: 'POST', ..., signal })
const reader = res.body.getReader()
const decoder = new TextDecoder()
buffer += decoder.decode(value, { stream: true })
while ((sep = buffer.indexOf('\n\n')) >= 0) { ... }
```
- 用 `TextDecoder(stream: true)` 处理中文被切在两个 chunk 中间的情况。
- 按 `\n\n` 切帧，找 `data:` 行，`JSON.parse`；单帧解析失败就跳过。
- 这里不用 `EventSource`，因为它只能 GET，而问题必须 POST。

**事件分发** `handleEvent`：

| 事件 | 前端动作 |
| --- | --- |
| `meta` | 记录 sessionId、traceId |
| `plan` | 记录意图，追加「关系查询」等 chip |
| `retrieval` | 记录 Cypher、attempts、links、vector_hits |
| `evidence` | 记录证据（流式阶段） |
| `token` | 追加文本并滚动 |
| `citations` | 记录引用校验结果 |
| `cached` | 追加「缓存命中」chip |
| `error` | 把错误写进气泡 |
| `done` | `finish()`：补延迟/token/缓存 chip，保存 detail，写 graphStore |

**`newSession()`**：`controller.abort()`、清空消息、清 sessionId、重置图谱。

**`defineExpose({ ask })`**：让 App 和识药页能调用。

**面试可讲**：
> 流式消息对象必须是 `reactive`。如果只是普通对象 push 进数组，之后再改它的 `text`，
> Vue 不会触发更新——因为改的是原始对象，没走代理的 set trap。
> 另外清空会话要 abort 请求，否则旧请求还在后台慢慢吐 token，会和新会话的状态打架。

**可能追问**：为什么不用 WebSocket？——这里是单向增量输出，SSE 更轻，服务端就是一个生成器；WebSocket 适合双向交互，本项目不需要。

### `frontend/src/components/Composer.vue`

**做什么**：输入框。

- `v-model` 绑定输入。
- `Enter` 发送、`Shift+Enter` 换行、`maxlength=500`。
- 输入时自动增高：`height = min(scrollHeight, 140)px`。
- `disabled` 时禁止发送。

**面试可讲**：
> 自动增高每次先设 `auto` 再读 `scrollHeight`，否则高度只会增不会减。

### `frontend/src/components/AssistantMessage.vue`

**做什么**：一条助手消息的完整渲染。

- 首字未到时显示 `el-skeleton`，比空气泡更像在思考。
- chips：意图、延迟、token、缓存、反馈状态。
- 反馈：POST `/api/feedback`，成功显示「已记录 👍/👎」。
- 折叠区：
  - 证据：缩略图 + `[E1]` + kind + 标题/正文。
  - 图谱查询：Cypher + 多次执行过程 + 实体链接。
  - 向量检索命中：分数、来源、标题。
  - 执行轨迹：阶段耗时条形图 + 总耗时/token/成本。
- 引用点击：展开证据、`scrollIntoView`、加 `flash` 类重放高亮动画。
- 缩略图：`evidenceThumbs` 计算属性按 `mediaCache` 取，消息内按图片去重。

**面试可讲**：
> 这是「渐进式披露」：默认只给答案和 chip，证据、Cypher、轨迹都折叠。
> 引用编号不是装饰，点一下能定位到对应证据并高亮，这是系统可信度的落点。

**可能追问**：图片为什么按 `thumb` 去重？——机制链路里同一味药会出现在多条证据中，不去重会连续出现同一张图。

### `frontend/src/components/CiteText.vue`

**做什么**：极简 Markdown 渲染 + 引用标记。

处理顺序：
1. `escapeHtml` 先转义 `& < > " '`。
2. 行内处理 `**粗体**` 和 `` `代码` ``。
3. 块级处理标题（`#` → `h4`）、无序/有序列表、空行分段、普通行用 `<br>` 连接。
4. 最后把 `[E1]` 替换成 `<span class="cite" data-eid="E1">`。
5. 用事件委托 `closest('.cite')` 处理点击，避免给每个 span 绑监听。

**面试可讲**：
> 先转义再拼 HTML，而且引用替换放在最后——因为此时 `[E1]` 还是纯文本，
> 替换成 span 不会破坏已经生成的标签。不用 marked/markdown-it，是因为模型输出格式有限，
> 自己写的链路短，更容易保证不出现注入。以后要支持链接/图片，就应该引库 + DOMPurify。

**可能追问**：`v-html` 安全吗？——输入先经过自己的 `escapeHtml`，标签都是代码里白名单生成的；没有用户原始 HTML。

### `frontend/src/components/SidePanel.vue`

**做什么**：问答页右侧「证据链」侧栏。

- `GraphTab :active="true" :compact="true"`：始终显示当前回答的图谱。
- 底部按钮 `setTab('graph')` 跳到全宽图谱页。

**面试可讲**：
> 侧栏宽度只有三百多像素，所以 `compact` 模式限制节点数（9 个）并提高最小缩放；
> 不然十几个节点会被压成看不清的小字。

---

## 6. 知识图谱

### `frontend/src/components/GraphTab.vue`

**做什么**：图谱的「业务层」：搜索、加载节点、邻域扩展、详情卡、导出。

**核心数据结构**：
- `nodes` / `edges`：当前画布数据。
- `selected`：当前选中的节点详情。
- `expandedIds`：已经展开过邻居的节点，避免重复请求。
- 上限：`MAX_NODES=60`、`EXPAND_LIMIT=12`、`COMPACT_MAX_NODES=9`。

**证据 → 图** `evidenceToRows`：
- `kind === 'graph'`：取 `payload`（真正的关系行）。
- `kind` 是 herb/ingredient/disease 的文档证据：用 `title` 生成单节点。
- 不能把整个证据对象直接丢给图模型，否则会出现名为 `graph`、`E1` 的假节点。

**节点操作**：
- `searchNode`：`/api/graph/search` 取第一个结果，`loadNode(..., { reset: true })`，然后 `fit()`。
- `loadNode`：`/api/graph/node` 拿属性、邻居、疾病中文别名；`mergeNeighbors` 合并去重。
- `expandSelected`：只追加邻居，不重置视图；已展开过就跳过。
- `onActivate`（双击）：把节点设为新中心，重新拉一圈。
- `exportPng`：文件名用中心实体名 + 日期，非法字符替换。
- `openCover`：中药看封面、成分看分子结构式。
- `deepLink`：`#graph?q=枸杞` 时自动搜索；问答侧栏不响应，避免整句问题被当成实体。

**监听**：
- `graphStore.revision` → 对话产生新答案时刷新图。
- `props.active` → 切回来时重新 fit。
- `ui.tab` + `deepLink` → hash 深链触发搜索。

**面试可讲**：
> 这层最重要的工作是「证据到图的翻译」。图谱证据的 payload 是关系行，
> 语义证据没有关系，就用标题补一个单节点，让用户至少看到答案里提到了什么。
> 另外所有扩展都是「点了才拉」，节点上限 60，避免点着点着把上千个邻居全铺开。

**已知小边界**：`applyModel` 给锚点加粗时默认按 `herb` 拼 id，如果锚点是成分则不会加粗。影响只是视觉，不影响数据。

### `frontend/src/components/GraphCanvas.vue`

**做什么**：vis-network 的无业务封装。

- `DataSet` 管理节点和边；`Network` 负责渲染。
- 每种实体一个 group：背景浅色、描边用类型色。
- 布局：`forceAtlas2Based`，适合十几个到几十个节点的小图；`stabilization.iterations=420`。
- `applyData`：增量更新——删掉不存在的、更新存在的，不整表重建。
- `fitReadable`：先 `fit`，再保证最小缩放（compact 0.78，普通 0.7），否则窄容器字太小。
- `settleAndFit`：开物理 → `stabilize()` → 稳定后**关闭物理模拟**再 fit。
- 事件：`selectNode` → emit select；`doubleClick` → emit activate。
- `exportPNG`：过滤 0×0 辅助画布，挑面积最大的当底图，铺纸色背景，合成后下载。
- `defineExpose`：`fit / focus / stabilize / exportPNG`。
- 卸载时 `network.destroy()`。

**面试可讲**：
> 稳定后关物理，是因为问答页侧栏和图谱页各有一个实例，常驻力模拟会一直吃 CPU；
> 关掉后节点仍可拖拽，只是不再自动回弹。
> 导出 PNG 不能直接 `toDataURL`：vis 的 canvas 是透明背景，而且容器里可能有零尺寸辅助画布，
> 所以要过滤零尺寸、取最大的一张，自己铺底再合成。

**可能追问**：为什么用 vis-network 而不是 ECharts graph？——需要拖拽、缩放、双击、增量更新和导出；
vis-network 的交互更成熟，ECharts 更适合统计图。两者拆成独立 chunk，互不影响。

---

## 7. 多模态、指标与图片

### `frontend/src/components/VisionTab.vue`

**做什么**：拍照识药。

- `el-upload`：`drag` + `:auto-upload="false"` + `:show-file-list="false"`，`on-change` 里拿 `file.raw`。
- 图像检索：直接 `fetch(FormData)`，不经过 `api()`；后端 `/api/vision/search-image?top_k=8`。
- 文本检索：`/api/vision/search-text?q=...&top_k=8`。
- `render()`：写结果、查询类型、候选数、免责声明。
- 相似度条：相对 Top-1 归一化，最小 6%，避免全 0 时看不见。
- 点击图片打开 Lightbox；「追问这味药」emit ask。
- 搜索过且无结果时显示 `el-empty`。

**面试可讲**：
> 结果明确标注「候选召回，不是鉴定结论」。中药同名异物、同物异名很常见，
> 拿一张图断言是某味药是不负责任的。前端把这个边界写在 UI 上，而不是只藏在接口文档里。

### `frontend/src/components/MetricsTab.vue`

**做什么**：指标卡片 + 两张 ECharts。

- ECharts 按需注册：`PieChart`、`BarChart`、`GridComponent`、`LegendComponent`、`TooltipComponent`、`CanvasRenderer`。
- `load()`：`/api/metrics`，过滤掉没有问题的历史空轨迹，`nextTick` 后画图。
- 八张卡片：提问数、平均延迟、累计 token、单次成本、缓存条目、缓存命中、索引文档、好评/差评。
- 饼图：意图分布，`intentLabel` 翻译；环形样式。
- 柱图：最近 10 条请求延迟，反向排列，tooltip 显示问题原文。
- `resize` 监听 + 卸载时 `dispose()`。
- `watch(active, immediate)`：页面激活时加载。

**面试可讲**：
> ECharts 用 `echarts/core` 按需注册，不引整包。
> 一个坑：`legend` 属于 `LegendComponent`，漏注册时图例配置会被静默忽略，不报错。
> 图表实例必须 `dispose`，否则路由式切换后 DOM 没了，实例还挂着。

### `frontend/src/components/Lightbox.vue`

**做什么**：全屏图片放大层。

- `v-if="lightbox.visible"`。
- 点遮罩或 × 关闭；`Esc` 关闭（全局 keydown，卸载时移除）。
- 底部缩略条：当前项高亮，坏图 `display:none`。
- 中文说明 + 类型 + 图谱 id。

**面试可讲**：放大层状态在 store 里，组件只负责渲染和键盘/点击交互。

### `frontend/src/components/AboutTab.vue`

**做什么**：静态说明：这是什么、为什么不是纯向量 RAG、可信度、免责声明。

**面试可讲**：这页也是对评审的「系统边界」说明，和 README、首页能力卡片口径一致。

---

## 8. 样式

### `frontend/src/assets/style.css`

**做什么**：全站设计系统和样式，约 1000 行。

- 设计变量：宣纸色系 `--paper / --paper-2 / --card`，墨色 `--ink`，竹青 `--jade`，朱砂 `--cinnabar`，金色 `--gold`；字体分 `--serif`（标题/数字）和 `--sans`（正文）。
- 布局：`#app` 纵向 flex；`.appbar` sticky；`.app-main` 撑满；`.home` / `.page` 各自滚动；`.workbench` 两栏（对话 + 证据链）。
- 组件：导航、按钮、首页、页面容器、消息气泡、Markdown 排版、折叠详情、输入区、证据链侧栏、图谱容器、图表卡片、指标卡、识药卡片、页脚、流式光标、放大层。
- 响应式：`1180px` 以下工作台改单列；`860px` 以下导航换行、统计卡两列、图表单列。

**面试可讲**：
> 用 CSS 变量做设计系统，主题改一处即可。没有用 scoped：这是全站统一的视觉语言，
> 组件结构也基本一页一类；全局样式反而更容易保持一致。代价是命名要克制，目前用 BEM 风格的层级类名隔离。

### `frontend/src/assets/element-theme.css`

**做什么**：覆盖 Element Plus 的 CSS 变量，把默认蓝白企业风改成竹青/纸色。

- 主色、成功/警告/危险色、文字色、边框色、背景色、圆角、字体、阴影。
- 用 `html:root` 而不是 `:root` 提高优先级。
- 必须在 `style.css` 之后引入（`main.js` 里控制顺序）。

**面试可讲**：
> 按需引入的组件样式是运行时插入的，插入顺序不可控；用 `html:root` 多一个元素选择器，
> 保证主题变量稳定覆盖，不依赖加载顺序。

---

## 9. 与前端直接相关的后端接口

> 这一节不是后端全量讲解，只讲前端会调用、需要前端同学理解契约的部分。

### `tcmqa/main.py`

**做什么**：FastAPI 装配。

- `lifespan`：启动时 `build_services`，关停时释放。
- 中间件：request_id + 访问日志 + 统一 500 错误。
- 路由：chat / graph / health / media / vision 全部挂 `/api`。
- 图片静态目录：`/media/covers`、`/media/gallery`、`/media/mol`。
- Vue 构建产物：有 `frontend/dist/index.html` 就挂根路径；没有则 `/` 返回 503 和构建提示。

**面试可讲**：
> 前后端同源部署，生产环境没有 CORS 问题。静态资源挂在根路径，
> 但 `/api`、`/media` 路由注册在前，不会被前端 fallback 抢占。

### `tcmqa/api/deps.py`

**做什么**：应用级单例容器。

- `Services` 持有 settings、llm、graph、linker、semantic、vision、db、pipeline。
- 重型资源只在 lifespan 构建一次，挂 `app.state.services`。
- embedding 和 Chinese-CLIP 在后台线程预热，避免第一个用户等十几秒。

**面试可讲**：
> 模型加载不能放请求里。后台预热让服务先可用，代价只是头几秒仍然慢。

### `tcmqa/api/chat.py`

**做什么**：问答接口。

- `POST /api/chat`：同步问答。
- `POST /api/chat/stream`：SSE 流式。
- 并发闸门：`threading.Semaphore(llm_max_concurrency)`，流式最多等 60 秒，拿不到就发 `error` 事件。
- SSE 格式：`data: {json}\n\n`。
- 响应头：`Cache-Control: no-cache`、`X-Accel-Buffering: no`（nginx 下关缓冲，否则流式变一次性）。
- 客户端断开：捕获 `GeneratorExit`，记日志。
- `/sessions`、`/sessions/{id}/messages`、`/feedback`、`/feedback/stats`。

**面试可讲**：
> `X-Accel-Buffering` 是流式部署的坑：nginx 默认缓冲，会把 SSE 攒成一坨再发，用户看不到逐字效果。

### `tcmqa/api/schemas.py`

**做什么**：Pydantic 请求/响应模型。

- `ChatRequest`：问题 1–500 字，session 可空，use_cache 默认 true。
- `FeedbackRequest`：rating 只能是 -1 或 1。
- `NeighborRequest`：label 限定四种实体。
- 好处：`/docs` 自动文档、入参校验、错误格式统一。

**面试可讲**：
> 前端和后端共用一份契约。现在没有生成 TS 类型，后续可以从 OpenAPI 生成，减少字段拼写错误。

### `tcmqa/api/graph.py`

**做什么**：图谱接口。

- `/graph/overview`：节点/关系统计、Top 中药/疾病/功效。
- `/graph/node`：节点属性 + 邻居；label 白名单；疾病中文名先映射成图谱英文名。
- `/graph/neighbors`：邻居扩展。
- `/graph/cypher`：手工只读 Cypher，同样过守卫。
- `/graph/search`：名称搜索；中文病名会先做别名映射，并把中文名作为 alias 返回。

**面试可讲**：
> 疾病在图谱里是英文 ICD 术语，用户输入「糖尿病」直接查 name 会一无所获；
> 所以搜索接口先做一次中文病名映射，前端拿到的 `alias` 用来展示中文。

### `tcmqa/api/health.py`

**做什么**：健康检查与指标。

- `/health`：Neo4j、LLM key、索引、缓存状态。
- `/metrics`：问答数、延迟、token、成本、缓存、反馈、索引、最近 10 条轨迹。
- `/metrics/recent`、`/traces/{trace_id}`。

**面试可讲**：指标页直接消费 `/api/metrics`，后端每个字段都有明确来源，不是前端估算。

### `tcmqa/api/media.py`

**做什么**：图片资源。

- `/media/resolve?names=...`：批量把实体名换成 `{label, id, thumb, orig, gallery}`。
- `/media/herb/{id}/images`：图库，返回序号和缩略图。
- `/media/herb/{id}/image/{index}`：大图，序号由服务端解析。
- `/media/mol/{ingredient_id}`：分子结构式。
- `/media/stats`：图片资源就绪情况。

**安全设计**：对外只暴露服务端拼出来的固定路径或序号，客户端不能传任意文件名，杜绝目录穿越。

**面试可讲**：
> 中药原图平均 200KB、单张最大 1.6MB，前端拿到的是预生成的 480px webp 封面；
> 分子结构图只有几 KB，直接发原图。尺寸分流是首屏性能的关键。

### `tcmqa/api/vision.py`

**做什么**：以图搜药、以文搜图。

- 上传校验：content-type、非空、≤8MB、PIL 实际解码验证。
- 索引未构建返回 503。
- 结果统一带 `followup`（可直接发问）和 `disclaimer`。
- 文本检索支持 `alpha` 参数（纯跨模态 ↔ 纯文本先验）。

**面试可讲**：
> 不只看 content-type，还要真的用 PIL 解码一次，避免把任意二进制喂给模型。

### SSE 事件契约（前端按这个写）

| 顺序 | 事件 | 何时发 | data |
| --- | --- | --- | --- |
| 1 | `meta` | 会话建立 | `trace_id`, `session_id` |
| 2 | `cached` | 命中缓存（可选） | 缓存类型/分数 |
| 3 | `plan` | 规划完成 | 意图、改写、实体、路由 |
| 4 | `retrieval` | 检索完成 | `cypher`, `attempts`, `links`, `vector_hits` |
| 5 | `evidence` | 证据生成 | 证据数组 |
| 6 | `token` × N | 模型逐字输出 | 文本片段 |
| 7 | `citations` | 答案结束后的引用校验 | 引用统计 |
| 8 | `done` | 一次问答结束 | 完整结果（含 evidence/cypher/trace/cached/latency） |

**注意**：前端不能假设这些事件一定存在：

- 缓存命中：`meta → cached → token → done`，没有 `plan/retrieval/evidence/citations`；
- 闲聊/超范围：`meta → plan → token* → done`，没有检索和证据；
- 输入被拦截：`meta → token → done`；
- 检索为空：仍有 `plan/retrieval/evidence`，但 evidence 是空数组，随后给固定兜底文案。

这正是 `handleEvent` 用 `switch` 按类型分发、`finish()` 对字段做 `?? []` 兜底的原因。

---

## 10. 构建、部署与验证

### `Dockerfile`

**做什么**：两阶段构建。

1. `node:22-alpine`：`npm ci` + `npm run build`，产出 `dist`。
2. `python:3.11-slim`：装 CPU 版 torch 依赖，拷 `tcmqa/`、`scripts/`、金标集，再 `COPY --from=frontend` 拷构建产物。
- 健康检查打 `/api/health`。

**面试可讲**：
> 前端在镜像里构建，不把 `node_modules` 和 `dist` 塞进构建上下文；
> `.dockerignore` 排除了这两个目录。运行时镜像不需要 Node。

### `start.ps1` / `start.bat`

**做什么**：一键启动 Neo4j + API。

- 检测 `frontend/dist/index.html`：不存在就 `npm install`（首次）+ `npm run build`，保证新环境一键可用。
- 然后检查 7474/8000 端口，缺什么起什么，最后打健康检查。

**面试可讲**：
> 旧版原生 JS 已移除，所以启动脚本加了一层前端构建兜底；
> `npm.cmd` 是为了绕过 PowerShell 对 `npm.ps1` 执行策略的限制。

### `.gitignore` / `.dockerignore`

**做什么**：忽略 `frontend/node_modules/`、`frontend/dist/`、Python 缓存、数据和密钥。
`dist` 不进仓库，但 `package-lock.json` 进，保证构建可复现。

### `scripts/demo.py`

**做什么**：最直白的接口演示脚本。

- 调 `/api/health` 打印服务状态。
- 调同步 `/api/chat`，打印意图、耗时、token、成本、Cypher、前 6 条证据、回答、分阶段耗时、引用校验。

**面试可讲**：
> 面试现场如果不想开浏览器，跑这个脚本就能把一次完整问答的后端输入输出打出来，
> 适合解释「证据和引用到底长什么样」。

### `scripts/test_api.py`

**做什么**：对运行中的服务做接口回归。

- 覆盖问答、图谱、指标、反馈、静态资源、图片、边界情况。
- 静态资源部分检查 `/` 返回 Vue 入口、`/assets/*.js` 可访问。

### `scripts/cdp_probe.py` + `scripts/cdp_*.js`

**做什么**：用 Chrome DevTools Protocol 驱动页面做真实交互验证。

- `cdp_probe.py`：启动带调试端口的 Chrome，拿 WebSocket，执行 `Runtime.evaluate`。
- `cdp_read_graph.js`、`cdp_check_canvas.js`、`cdp_check_chat.js`、`cdp_check_export.js`、`cdp_check_message.js`、`cdp_check_vision.js`：读页面状态或检查交互结果。

**面试可讲**：
> 截图只能看静态结果。双击换中心、导出 PNG、图表渲染这些必须真的触发事件。
> 而且 vis-network 用 pointer 事件，JS 里 `dispatchEvent(new MouseEvent('dblclick'))` 到不了它的手势层，
> 必须用 CDP 发浏览器级输入。页面里还有可见图谱页和隐藏问答侧栏两个实例，
> 查询要限定在 `.page` 内，否则会读到隐藏实例的空状态。

### `frontend/dist/`

**做什么**：构建产物，不手改。

- `index.html`
- `assets/index-*.css/js`：主包
- `assets/vendor-vue/graph/charts/element-*.js`：手动拆分的 vendor
- 异步页面 chunk：`GraphPage-*.js`、`VisionPage-*.js`、`MetricsPage-*.js`、`AboutPage-*.js`
- `favicon.svg`

**面试可讲**：
> 打开 dist 能直接看出分包策略：首包只有入口和 Vue，图谱/图表/Element 各自独立，
> 四个非首页视图也是独立 chunk。

---

## 11. 面试演示脚本

### 11.1 推荐演示顺序（3–5 分钟）

1. **首页**：指规模卡片说明数据来自图谱实时统计，不是写死的。
2. **提问**「为什么麻黄能治疗哮喘？」：
   - 指出流式光标和意图 chip；
   - 等结束后展开「证据」，点一个 `[E1]`，说明引用如何定位到证据；
   - 展开「图谱查询」，说明 Cypher 是模型生成、执行过的；
   - 展开「执行轨迹」，说明延迟/token/成本可按阶段量化。
3. **右侧证据链**：说明答案里的关系同步画成了图。
4. **知识图谱页**：搜「枸杞」→ 双击节点换中心 → 展开邻居 → 导出 PNG。
5. **拍照识药**：上传一张或输入「红色的果实」，强调「候选不是鉴定」。
6. **运行指标**：指饼图和柱图，说明数据来自 SQLite 轨迹。
7. 如果时间够：刷新 `#chat?q=...` 展示 hash 深链。

### 11.2 高频追问速答

**Q1：为什么用 Vue3 组合式 API？**
> 这个项目的状态和副作用比较集中（SSE、ECharts、vis-network 都要在生命周期里创建/销毁），
> 组合式 API 让「状态 + 逻辑」放在一起，比 Options API 分散在 data/mounted/watch 里更好读。

**Q2：为什么不用 vue-router？**
> 六个平级视图、没有嵌套和路由参数。hash + 一个 reactive store 就够了，
> 深链 `#chat?q=` 反而更直接。以后要加权限、嵌套布局或路由守卫，再上 router。

**Q3：为什么不用 Pinia？**
> 只有三个跨组件状态：当前视图、图谱数据、放大层。模块级 `reactive` 足够，
> 少一个依赖，也没有 actions/getters 的样板代码。

**Q4：SSE 怎么实现的？为什么不用 EventSource？**
> EventSource 只能 GET，问题需要 POST，所以用 fetch + ReadableStream 手写解析。
> 按 `\n\n` 切帧，`TextDecoder(stream: true)` 处理中文跨 chunk，单帧解析失败跳过。

**Q5：流式渲染为什么不会卡？**
> 每个 token 只改一个响应式字符串，Vue 批量更新 DOM；没有用深度 watch 整个消息列表。
> 滚动用 `nextTick`，确保 DOM 更新后再滚到底部。

**Q6：如何防止 XSS？**
> 答案正文先 `escapeHtml`，再由代码生成白名单标签（p/h4/ul/ol/li/strong/code/span），
> 最后替换引用标记。没有把用户或模型输出直接塞进 `innerHTML`。
> 如果以后支持链接/图片，会引 Markdown 库 + DOMPurify。

**Q7：图表和画布会不会内存泄漏？**
> ECharts 在 `onBeforeUnmount` 里 `dispose`，vis-network 在 `network.destroy()`；
> resize 和 keydown 监听都在卸载时移除。异步页面用 `v-if`，切走就卸载。

**Q8：大依赖怎么优化？**
> 四个非首页视图用 `defineAsyncComponent`；ECharts 按需注册；Element Plus 深层导入；
> Vite `manualChunks` 把 vis / echarts / element / vue 拆成独立 vendor。

**Q9：为什么图谱稳定后要关物理模拟？**
> 两个实例（问答侧栏 + 图谱页）如果一直跑力模拟，会持续吃 CPU；
> 稳定后位置基本不变，关掉不影响拖拽，只是不再自动回弹。

**Q10：导出 PNG 为什么不能直接 `toDataURL`？**
> vis 的 canvas 是透明背景，而且容器里可能有 0×0 的辅助画布。
> 要过滤零尺寸、取面积最大的当底图，铺一层纸色背景，再把同尺寸画布叠上去。

**Q11：前端如何保证和后端契约一致？**
> 接口用 Pydantic 定义，`/docs` 有 OpenAPI；前端集中在 `api/client.js` 和几个调用点。
> 目前没有自动生成 TS 类型，这是可以改进的点。

**Q12：如果要做多轮会话恢复，怎么做？**
> 后端已有 `/api/sessions` 和 `/api/sessions/{id}/messages`；
> 前端现在切视图能保活，但刷新会丢。可以在 `ChatPanel.onMounted` 读 sessionId，回放消息。

**Q13：已知的不足？**
> 没有前端单元测试（目前用 CDP 脚本做交互验证）；Markdown 只支持标题/列表/粗体/代码；
> 刷新 `#chat?q=` 会重新提问；`unplugin-*` 是未使用的遗留依赖；锚点加粗默认按中药类型。

**Q14：如果让你继续优化，优先做什么？**
> 先补 Vitest 组件测试和 Playwright 端到端；再做会话恢复和消息虚拟滚动；
> 然后把 OpenAPI 生成 TS 类型，最后清理未使用依赖。

---

## 12. 一页速查表

| 文件 | 一句话 |
| --- | --- |
| `package.json` | 依赖与脚本 |
| `package-lock.json` | 精确锁定依赖树 |
| `vite.config.js` | 代理 + 分包 |
| `index.html` | SPA 挂载点 |
| `src/main.js` | 创建应用、装 Element、样式顺序 |
| `src/App.vue` | 视图切换 / 保活 / 懒加载 / hash 同步 |
| `src/stores/ui.js` | 当前视图 + hash 深链 |
| `src/stores/graph.js` | 证据图谱数据 + revision |
| `src/stores/lightbox.js` | 放大层 + 图库 |
| `src/api/client.js` | JSON 请求封装 |
| `src/utils/format.js` | 延迟 / 意图格式化 |
| `src/utils/graph.js` | 证据行 → 节点边模型 |
| `src/utils/media.js` | 缩略图批量解析 + 负缓存 |
| `src/plugins/element-components.js` | Element 深层导入 |
| `src/plugins/element.js` | 注册 8 个组件 |
| `components/TopBar.vue` | 品牌 / 导航 / 在线状态 |
| `components/AppFooter.vue` | 免责声明 |
| `components/ChatPanel.vue` | SSE 流式问答核心 |
| `components/Composer.vue` | 输入框 |
| `components/AssistantMessage.vue` | 答案 / 证据 / Cypher / 轨迹 / 反馈 |
| `components/CiteText.vue` | 极简 Markdown + 引用 |
| `components/SidePanel.vue` | 问答页证据链侧栏 |
| `components/GraphTab.vue` | 图谱搜索 / 扩展 / 详情 |
| `components/GraphCanvas.vue` | vis-network 封装 |
| `components/VisionTab.vue` | 拍照识药 |
| `components/MetricsTab.vue` | 指标卡片 + ECharts |
| `components/Lightbox.vue` | 大图 / 图库 |
| `components/AboutTab.vue` | 说明 |
| `views/*.vue` | 五个页面的薄壳 |
| `assets/style.css` | 设计系统与全站样式 |
| `assets/element-theme.css` | Element 主题变量覆盖 |
| `tcmqa/main.py` | 静态托管 + 路由装配 |
| `tcmqa/api/chat.py` | 同步 / SSE / 反馈 |
| `tcmqa/api/graph.py` | 概览 / 节点 / 搜索 |
| `tcmqa/api/health.py` | 健康检查 / 指标 |
| `tcmqa/api/media.py` | 图片解析 / 图库 / 安全路径 |
| `tcmqa/api/vision.py` | 以图搜药 / 以文搜图 |
| `tcmqa/api/schemas.py` | Pydantic 契约 |
| `tcmqa/api/deps.py` | 重资源单例 / 预热 |
| `Dockerfile` | 前端构建 + Python 运行时 |
| `start.ps1` | 一键启动 + 前端兜底构建 |
| `scripts/demo.py` | 同步接口演示 |
| `scripts/test_api.py` | 接口回归 |
| `scripts/cdp_probe.py` | 真实浏览器交互验证 |
