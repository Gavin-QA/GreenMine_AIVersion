import { createApp } from 'vue'
import ElementPlus from 'element-plus'
import 'element-plus/dist/index.css'
import 'element-plus/theme-chalk/dark/css-vars.css'
import zhCn from 'element-plus/es/locale/lang/zh-cn.mjs'
import * as ElementPlusIconsVue from '@element-plus/icons-vue'

import './styles/theme.css'
import App from './App.vue'

// 启用 Element Plus 暗黑模式与工业深蓝主色调融合
document.documentElement.classList.add('dark')

const app = createApp(App)

for (const [key, component] of Object.entries(ElementPlusIconsVue)) {
  app.component(key, component)
}

app.use(ElementPlus, { locale: zhCn })
app.mount('#app')

