import { reactive } from 'vue'

/**
 * 关系图当前要展示的证据行。
 * 对话结束后由 ChatPanel 写入，节点搜索由 GraphTab 写入；
 * revision 用来触发画布重绘（比深层 watch 便宜）。
 */
export const graphStore = reactive({
  evidence: [],
  links: [],
  revision: 0,

  set(evidence, links = []) {
    this.evidence = evidence || []
    this.links = links || []
    this.revision += 1
  },

  reset() {
    this.set([], [])
  },
})
