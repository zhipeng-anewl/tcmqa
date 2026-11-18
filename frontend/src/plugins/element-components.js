/**
 * 按组件引入 Element Plus。
 *
 * 全部使用深层路径（element-plus/es/components/xxx/index），
 * 不要写成 `import { ElButton } from 'element-plus'`——
 * 那是整包入口，会把所有组件拉进产物。
 *
 * 样式也必须单独引，否则组件渲染出来没有外观。
 */

import { ElButton } from 'element-plus/es/components/button/index'
import 'element-plus/es/components/button/style/css'

import { ElEmpty } from 'element-plus/es/components/empty/index'
import 'element-plus/es/components/empty/style/css'

import { ElInput } from 'element-plus/es/components/input/index'
import 'element-plus/es/components/input/style/css'

import { ElProgress } from 'element-plus/es/components/progress/index'
import 'element-plus/es/components/progress/style/css'

import { ElSkeleton, ElSkeletonItem } from 'element-plus/es/components/skeleton/index'
import 'element-plus/es/components/skeleton/style/css'

import { ElTag } from 'element-plus/es/components/tag/index'
import 'element-plus/es/components/tag/style/css'

import { ElTooltip } from 'element-plus/es/components/tooltip/index'
import 'element-plus/es/components/tooltip/style/css'

import { ElUpload } from 'element-plus/es/components/upload/index'
import 'element-plus/es/components/upload/style/css'

// 函数式调用的消息提示，同样走深层路径
import { ElMessage } from 'element-plus/es/components/message/index'
import 'element-plus/es/components/message/style/css'

export {
  ElButton,
  ElEmpty,
  ElInput,
  ElMessage,
  ElProgress,
  ElSkeleton,
  ElSkeletonItem,
  ElTag,
  ElTooltip,
  ElUpload,
}
