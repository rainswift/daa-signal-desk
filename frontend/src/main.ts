import { createApp } from 'vue'
import { createPinia } from 'pinia'
import '@fontsource/ibm-plex-sans-condensed/500.css'
import '@fontsource/ibm-plex-sans-condensed/600.css'
import '@fontsource/ibm-plex-mono/500.css'
import '@fontsource/ibm-plex-mono/600.css'
import './styles/tokens.css'
import App from './App.vue'

createApp(App).use(createPinia()).mount('#app')
