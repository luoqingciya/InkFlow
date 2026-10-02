<script setup lang="ts">
import { onMounted, ref } from 'vue'

import { api, type BookSource } from '../api/client'

const sources = ref<BookSource[]>([])
const loading = ref(true)
const busy = ref(false)
const error = ref<string | null>(null)
const notice = ref<string | null>(null)
const testResult = ref<{ id: string; ok: boolean; text: string } | null>(null)

async function load(): Promise<void> {
  try {
    const result = await api.listSources()
    sources.value = result.items
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    loading.value = false
  }
}

async function importFromFile(): Promise<void> {
  const path = await window.inkflow.selectFile({
    title: '选择书源文件',
    filters: [
      { name: '书源文件', extensions: ['json', 'yaml', 'yml'] },
      { name: '全部文件', extensions: ['*'] }
    ]
  })
  if (!path) return

  busy.value = true
  notice.value = null
  error.value = null
  try {
    // Renderer 没有文件系统权限，读文件走主进程
    const content = await window.inkflow.readTextFile(path)
    const result = await api.importSource(content)
    notice.value = `${result.created ? '已导入' : '已更新'}：${result.source.name}（${result.source.compatibility_level}）`
    await load()
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    busy.value = false
  }
}

async function toggle(source: BookSource): Promise<void> {
  busy.value = true
  try {
    await api.setSourceEnabled(source.id, !source.enabled)
    await load()
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    busy.value = false
  }
}

async function test(source: BookSource): Promise<void> {
  busy.value = true
  testResult.value = null
  try {
    const result = await api.testSource(source.id, 'search', '三体')
    testResult.value = {
      id: source.id,
      ok: result.ok,
      text: result.ok
        ? `通过，返回 ${result.count} 条结果（${result.elapsed_ms}ms）`
        : `失败：${result.error}`
    }
  } catch (e) {
    testResult.value = {
      id: source.id,
      ok: false,
      text: e instanceof Error ? e.message : String(e)
    }
  } finally {
    busy.value = false
  }
}

async function remove(source: BookSource): Promise<void> {
  busy.value = true
  try {
    await api.deleteSource(source.id)
    await load()
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    busy.value = false
  }
}

onMounted(load)
</script>

<template>
  <div>
    <h1>书源</h1>

    <div class="toolbar">
      <button class="primary" :disabled="busy" @click="importFromFile">导入书源文件</button>
      <span class="dim small">
        支持原生 YAML 与 Legado JSON。批量导入用 CLI：<code>inkflow sources import &lt;文件&gt;</code>
      </span>
    </div>

    <p v-if="error" class="error">{{ error }}</p>
    <p v-if="notice" class="success">{{ notice }}</p>
    <p v-if="loading" class="dim">加载中…</p>
    <p v-else-if="sources.length === 0" class="dim">
      还没有书源。导入一个书源后就能开始搜索了。
    </p>

    <table v-if="sources.length">
      <thead>
        <tr>
          <th>名称</th>
          <th>类型</th>
          <th>兼容等级</th>
          <th>状态</th>
          <th>操作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="source in sources" :key="source.id">
          <td>
            <div>{{ source.name }}</div>
            <div class="dim small">{{ source.url }}</div>
            <div
              v-if="testResult && testResult.id === source.id"
              class="small"
              :class="testResult.ok ? 'success' : 'error'"
            >
              {{ testResult.text }}
            </div>
          </td>
          <td class="dim">{{ source.source_type }}</td>
          <td class="dim">{{ source.compatibility_level }}</td>
          <td>
            <span :class="source.enabled ? 'success' : 'dim'">
              {{ source.enabled ? '已启用' : '已停用' }}
            </span>
          </td>
          <td class="ops">
            <button :disabled="busy" @click="test(source)">测试</button>
            <button :disabled="busy" @click="toggle(source)">
              {{ source.enabled ? '停用' : '启用' }}
            </button>
            <button :disabled="busy" @click="remove(source)">删除</button>
          </td>
        </tr>
      </tbody>
    </table>
  </div>
</template>

<style scoped>
h1 {
  margin: 0 0 20px;
  font-size: 22px;
}

.toolbar {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 16px;
  flex-wrap: wrap;
}

.ops {
  display: flex;
  gap: 6px;
}

.ops button {
  padding: 3px 10px;
  font-size: 12px;
}

code {
  background: var(--bg-hover);
  padding: 1px 5px;
  border-radius: 3px;
}

.small {
  font-size: 12px;
}
</style>
