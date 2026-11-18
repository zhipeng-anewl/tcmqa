/**
 * Element Plus 按组件注册。
 *
 * 为什么不用 unplugin-vue-components 的自动引入：
 * 它的 ElementPlusResolver 生成的 import 语句是 `from 'element-plus'`（整包入口），
 * 实测产物里会混进 ElTable / ElDatePicker 等根本没用到的组件，vendor 包 945KB。
 * 这里改成显式深层导入，用到哪个引哪个，体积可预期。
 *
 * 样式同样按组件引入（element-plus/es/components/xxx/style/css），
 * 这样组件的 CSS 变量仍会被 src/assets/element-theme.css 覆盖。
 */

import {
  ElButton,
  ElEmpty,
  ElInput,
  ElProgress,
  ElSkeleton,
  ElTag,
  ElTooltip,
  ElUpload,
} from './element-components'

export function installElement(app) {
  for (const component of [
    ElButton,
    ElEmpty,
    ElInput,
    ElProgress,
    ElSkeleton,
    ElTag,
    ElTooltip,
    ElUpload,
  ]) {
    app.component(component.name, component)
  }
}
