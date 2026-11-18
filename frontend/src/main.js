import { createApp } from 'vue'
import App from './App.vue'
import { installElement } from './plugins/element'
import './assets/style.css'
// 放在 style.css 之后：Element Plus 的主题变量要覆盖默认值
import './assets/element-theme.css'

const app = createApp(App)
installElement(app)
app.mount('#app')
