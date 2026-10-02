<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { RouterLink, RouterView, useRoute } from 'vue-router'

import { api, resetConnection } from './api/client'

interface AppInfo {
  version: string
  electron: string
  node: string
}

const route = useRoute()
const ready = ref(false)
const error = ref<string | null>(null)
const apiVersion = ref('')
const appInfo = ref<AppInfo | null>(null)

const navItems = [
  { to: '/', label: '首页' },
  { to: '/search', label: '搜索' },
  { to: '/tasks', label: '下载' },
  { to: '/sources', label: '书源' }
]

async function connect(): Promise<void> {
  error.value = null
  try {
    const health = await api.health()
    apiVersion.value = health.version
    ready.value = true
  } catch (e) {
    ready.value = false
    error.value = e instanceof Error ? e.message : String(e)
  }
}

async function retry(): Promise<void> {
  resetConnection()
  await connect()
}

onMounted(async () => {
  await connect()
  appInfo.value = await window.inkflow.getAppInfo()
})
</script>

<template>
  <div class="layout">
    <aside class="sidebar">
      <div class="brand">
        <span class="logo">InkFlow</span>
        <span class="tagline">API-First 下载平台</span>
      </div>

      <nav>
        <RouterLink
          v-for="item in navItems"
          :key="item.to"
          :to="item.to"
          class="nav-link"
          :class="{ active: route.path === item.to }"
        >
          {{ item.label }}
        </RouterLink>
      </nav>

      <div class="status">
        <div v-if="ready" class="status-line success">后端已连接</div>
        <div v-else class="status-line error">后端未连接</div>
        <div class="dim small">API {{ apiVersion || '—' }}</div>
        <div v-if="appInfo" class="dim small">Electron {{ appInfo.electron }}</div>
      </div>
    </aside>

    <main class="content">
      <div v-if="error" class="card error-banner">
        <div class="error">{{ error }}</div>
        <p class="dim small">
          后端可能尚未就绪，或未安装依赖。可在仓库根目录执行
          <code>uv sync --all-packages</code> 后重试。
        </p>
        <button @click="retry">重试连接</button>
      </div>

      <RouterView v-else />
    </main>
  </div>
</template>

<style scoped>
.layout {
  display: grid;
  grid-template-columns: 200px 1fr;
  height: 100%;
}

.sidebar {
  display: flex;
  flex-direction: column;
  gap: 20px;
  padding: 20px 14px;
  background: var(--bg-elevated);
  border-right: 1px solid var(--border);
}

.brand {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.logo {
  font-size: 18px;
  font-weight: 600;
  letter-spacing: 0.02em;
}

.tagline,
.small {
  font-size: 11px;
}

.tagline {
  color: var(--text-dim);
}

nav {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.nav-link {
  padding: 8px 12px;
  border-radius: 6px;
  color: var(--text-dim);
}

.nav-link:hover {
  background: var(--bg-hover);
  color: var(--text);
}

.nav-link.active {
  background: var(--bg-hover);
  color: var(--accent);
}

.status {
  margin-top: auto;
  display: flex;
  flex-direction: column;
  gap: 3px;
}

.status-line {
  font-size: 12px;
}

.content {
  overflow-y: auto;
  padding: 24px 28px;
}

.error-banner {
  border-color: var(--danger);
}

.error-banner p {
  margin: 8px 0 12px;
}

code {
  background: var(--bg-hover);
  padding: 1px 5px;
  border-radius: 3px;
  font-size: 12px;
}
</style>
