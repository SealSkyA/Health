import { createApp } from 'vue'
import App from './App.vue'
import router from './router'
import SearchSelect from './components/SearchSelect.vue'
import './styles/theme.css'

createApp(App).component('SearchSelect', SearchSelect).use(router).mount('#app')