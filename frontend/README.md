# 前端（Vue3 + Vite）

FastAPI 后端不变，Vue3 前端与后端接口一一对应。

## 开发

```bash
npm install
npm run dev        # http://localhost:5173
```

Vite 把 `/api`、`/media` 代理到 `http://127.0.0.1:8000`，所以先启动后端。
注意要在**项目根目录**（不是 `frontend/`）执行，否则会报 `No module named 'tcmqa'`：

```bash
cd ..
python -m uvicorn tcmqa.main:app --port 8000
```

后端没起来时，开发页仍能打开，但控制台会刷 `http proxy error ... ECONNREFUSED 127.0.0.1:8000`，
那是代理在等后端，不是前端报错。

## 构建

```bash
npm run build      # 输出 frontend/dist
```

重启 API 后，`http://127.0.0.1:8000` 直接托管构建产物。
`dist/` 不进仓库，新环境需先构建；`start.ps1` 检测到缺失会自动安装依赖并构建，
否则根路径会返回 503 并提示构建命令。

## 目录

```
src/
├── main.js                 挂载入口
├── App.vue                 视图切换（首页/问答保活，其余按需异步加载）
├── api/client.js           fetch 封装（上传接口单独处理 multipart）
├── assets/style.css        宣纸色系设计变量与全部样式
├── utils/
│   ├── format.js           延迟格式化 / 意图中文名
│   ├── graph.js            证据行 → 图数据模型（纯数据，不含渲染）
│   └── media.js            名称 → 缩略图缓存、证据配图规则
├── stores/
│   ├── ui.js               当前视图 + hash 路由（#chat?q=… / #graph?q=…）
│   ├── graph.js            当前关系图数据（对话与节点搜索共享）
│   └── lightbox.js         图片放大层状态 + 图库加载
├── views/
│   ├── HomeView.vue        门户首页：搜索框 / 实体规模卡片 / 能力分区
│   ├── GraphPage.vue       知识图谱（全宽）
│   ├── VisionPage.vue      拍照识药（全宽）
│   ├── MetricsPage.vue     运行指标（ECharts）
│   └── AboutPage.vue       关于
└── components/
    ├── TopBar.vue          品牌 + 主导航 + 健康状态
    ├── AppFooter.vue       免责声明与数据来源
    ├── ChatPanel.vue       消息列表 / SSE 流式解析 / 会话管理
    ├── Composer.vue        输入框（Enter 发送、自动增高）
    ├── AssistantMessage.vue 证据、Cypher、向量命中、执行轨迹、反馈
    ├── CiteText.vue        极简 Markdown 渲染 + [E1] 引用标记
    ├── SidePanel.vue       问答页右侧证据链侧栏
    ├── GraphCanvas.vue     vis-network 封装：力导向 / 拖拽 / 缩放 / 选中
    ├── GraphTab.vue        实体搜索 + 邻域扩展 + 节点详情
    ├── VisionTab.vue       拍照识药（以图搜药 / 以文搜图）
    ├── MetricsTab.vue      指标卡片 + ECharts 图表
    ├── AboutTab.vue        说明
    └── Lightbox.vue        大图 + 图库条
```

## 图谱与图表的取舍

- **vis-network**：力导向布局、节点可拖拽、滚轮缩放、点击选中。
  交互有三条：
  1. **单击**节点 → 下方显示详情；
  2. **双击**节点 → 把它设为新的中心，重新拉一圈邻居（等价于「换一个实体继续逛」）；
  3. **展开邻居**按钮 → 只追加邻居、不重置视图。
- 稳定后会自动关闭物理模拟（两个实例常驻，不关会一直吃 CPU），
  「重新布局」按钮可重新开。
- 「导出 PNG」把容器里的 canvas 合成到一张纸色底图上再下载：
  必须先**过滤掉 0×0 的辅助画布**并取面积最大的那张当底图，
  隐藏实例里出现过零尺寸画布，直接取第一个会得到空图。
- 侧栏容器窄（约 360px），节点超过 9 个时无论怎么缩放都会「字看不清」或「被裁掉」，
  所以 compact 模式下限制节点数并给缩放下限。
- **ECharts**：只注册 `PieChart`、`BarChart`、`GridComponent`、`LegendComponent`、
  `TooltipComponent`、`CanvasRenderer`。**漏注册 `LegendComponent` 时 legend 配置会被静默忽略**，
  图例不显示也不报错。
- 两个库都单独打了 vendor chunk（`vendor-graph` / `vendor-charts`），
  且四个非首页视图用 `defineAsyncComponent` 懒加载，ECharts 只在打开指标页时下载。

## Element Plus 的接入方式

用到的组件：`el-input`（搜索框，带 append 按钮）、`el-button`、`el-tag`（实体类型图例）、
`el-tooltip`（按钮/统计卡片说明）、`el-empty`（空状态）、`el-progress`（相似度条）、
`el-upload`（识药拖拽上传）、`el-skeleton`（首字未回的占位）、`ElMessage`（操作反馈）。

**不要用 `unplugin-vue-components` 的 `ElementPlusResolver` 自动引入。**
它生成的 import 语句是 `from 'element-plus'`（整包入口），实测产物里会混进
`ElTable`、`ElDatePicker` 等根本没用的组件，vendor 包 **945 KB**。
改成在 `src/plugins/element-components.js` 里显式深层导入
（`element-plus/es/components/button/index`）并按需注册后，降到 **162 KB**，未用组件归零。

配套细节：

- 每个组件还要单独引 `element-plus/es/components/xxx/style/css`，否则没有外观；
- 主题覆盖写在 `src/assets/element-theme.css`，只改 CSS 变量（主色改竹青、边框改纸色），
  并且用 `html:root` 而不是 `:root`——按需注入的样式表插入顺序不可控，
  需要多一个元素选择器来保证优先级；
- 该文件必须在 `style.css` 之后引入。

## 交互怎么验证的

截图只能看静态结果。真交互用 `scripts/cdp_probe.py`（Chrome DevTools Protocol）：

```bash
# 读取页面状态
python scripts/cdp_probe.py "http://127.0.0.1:8000/#graph?q=枸杞" --file scripts/cdp_read_graph.js

# 在画布相对位置 (0.4, 0.48) 双击，再读一次状态
python scripts/cdp_probe.py "http://127.0.0.1:8000/#graph?q=枸杞" \
  --file scripts/cdp_read_graph.js --dblclick "0.40,0.48" --after 4
```

注意两点：
1. 页面里同时挂了**可见的知识图谱页**和**隐藏的问答侧栏**，两个实例都有
   `.graph-host` / `.graph-meta`，查询必须限定在 `.page` 内，否则读到的是隐藏实例的空状态；
2. JS 里 `dispatchEvent(new MouseEvent('dblclick'))` **到不了 vis 的手势层**（它用 pointer 事件），
   必须用 CDP 的 `Input.dispatchMouseEvent` 发浏览器级输入。

## 行为说明

- 「清空对话」不刷新页面，会中断正在进行的流式请求并清空消息与关系图；
- 引用高亮使用 CSS `@keyframes`；
- 视图切换用 `v-show` 而不是 `v-if`：对话消息存在 `ChatPanel` 内部，
  卸载组件会丢状态，`v-show` 保活最省事；
- 回答正文的 Markdown（标题/列表/粗体/行内代码）由 `CiteText` 自己渲染，
  先转义再拼 HTML，不引第三方渲染库，避免加依赖和 XSS 面；
- 没有引入 vue-router 和 Pinia：只有 6 个平级视图、没有嵌套参数，`stores/ui.js` + hash 足够。
