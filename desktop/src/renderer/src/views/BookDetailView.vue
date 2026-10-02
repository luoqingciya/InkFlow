<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'

import { api, type Book, type BookSource, type Chapter } from '../api/client'

const props = defineProps<{ id: string }>()
const router = useRouter()

const book = ref<Book | null>(null)
const source = ref<BookSource | null>(null)
const chapters = ref<Chapter[]>([])
const loading = ref(true)
const busy = ref(false)
const error = ref<string | null>(null)
const message = ref<string | null>(null)
const startChapter = ref(0)
const endChapter = ref<number | null>(null)

const chapterCount = computed(() => chapters.value.length)
const downloadedCount = computed(() => chapters.value.filter((c) => c.downloaded).length)

async function load(): Promise<void> {
  loading.value = true
  error.value = null
  try {
    const detail = await api.getBook(props.id)
    book.value = detail.book
    source.value = detail.source

    const list = await api.getChapters(props.id)
    chapters.value = list.chapters
    endChapter.value = list.chapters.length ? list.chapters.length - 1 : null
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    loading.value = false
  }
}

async function refreshToc(): Promise<void> {
  busy.value = true
  message.value = null
  try {
    const list = await api.getChapters(props.id, true)
    chapters.value = list.chapters
    endChapter.value = list.chapters.length ? list.chapters.length - 1 : null
    message.value = `目录已更新，共 ${list.chapters.length} 章`
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    busy.value = false
  }
}

async function download(): Promise<void> {
  busy.value = true
  error.value = null
  message.value = null
  try {
    const task = await api.createTask(props.id, {
      start: startChapter.value,
      end: endChapter.value ?? undefined
    })
    message.value = `任务已创建：${task.id}`
    router.push('/tasks')
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    busy.value = false
  }
}

async function exportBook(): Promise<void> {
  busy.value = true
  message.value = null
  try {
    const result = await api.exportBook(props.id, 'epub')
    message.value = `已导出：${result.output_path}`
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    busy.value = false
  }
}

async function openOutput(): Promise<void> {
  if (message.value?.startsWith('已导出：')) {
    await window.inkflow.revealPath(message.value.replace('已导出：', ''))
  }
}

onMounted(load)
</script>

<template>
  <div>
    <button class="back" @click="router.back()">← 返回</button>

    <p v-if="loading" class="dim">加载中…</p>
    <p v-else-if="error" class="error">{{ error }}</p>

    <template v-if="book">
      <h1>{{ book.name }}</h1>
      <p class="dim">
        {{ book.author || '未知作者' }}
        <span v-if="source"> · 来源 {{ source.name }}（{{ source.compatibility_level }}）</span>
      </p>

      <div class="card meta">
        <div class="stats">
          <span>章节 {{ chapterCount }}</span>
          <span>已下载 {{ downloadedCount }}</span>
          <span v-if="book.category">分类 {{ book.category }}</span>
          <span v-if="book.status">状态 {{ book.status }}</span>
        </div>
        <p v-if="book.intro" class="intro">{{ book.intro }}</p>
      </div>

      <div class="actions">
        <label>
          起始
          <input v-model.number="startChapter" type="number" min="0" class="num" />
        </label>
        <label>
          结束
          <input v-model.number="endChapter" type="number" min="0" class="num" />
        </label>
        <button class="primary" :disabled="busy || chapterCount === 0" @click="download">
          开始下载
        </button>
        <button :disabled="busy" @click="refreshToc">刷新目录</button>
        <button :disabled="busy || downloadedCount === 0" @click="exportBook">导出 EPUB</button>
      </div>

      <p v-if="message" class="success">
        {{ message }}
        <button v-if="message.startsWith('已导出')" class="link" @click="openOutput">
          打开位置
        </button>
      </p>

      <h2>目录</h2>
      <p v-if="chapterCount === 0" class="dim">
        还没有目录，点「刷新目录」从书源抓取。
      </p>
      <table v-else>
        <thead>
          <tr><th>#</th><th>章节名</th><th>状态</th></tr>
        </thead>
        <tbody>
          <tr v-for="chapter in chapters.slice(0, 300)" :key="chapter.id">
            <td class="dim">{{ chapter.index }}</td>
            <td>{{ chapter.name }}</td>
            <td>
              <span v-if="chapter.downloaded" class="success">已下载</span>
              <span v-else-if="chapter.is_vip" class="dim">VIP</span>
            </td>
          </tr>
        </tbody>
      </table>
      <p v-if="chapterCount > 300" class="dim small">（仅显示前 300 章）</p>
    </template>
  </div>
</template>

<style scoped>
h1 {
  margin: 12px 0 4px;
  font-size: 22px;
}

h2 {
  margin: 28px 0 12px;
  font-size: 15px;
  color: var(--text-dim);
  font-weight: 500;
}

.back {
  padding: 4px 10px;
}

.meta {
  margin: 16px 0;
}

.stats {
  display: flex;
  gap: 18px;
  color: var(--text-dim);
  font-size: 13px;
}

.intro {
  margin: 12px 0 0;
  color: var(--text-dim);
  font-size: 13px;
  max-height: 5.2em;
  overflow: hidden;
}

.actions {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.actions label {
  display: flex;
  align-items: center;
  gap: 6px;
  color: var(--text-dim);
  font-size: 13px;
}

.num {
  width: 80px;
}

.link {
  background: none;
  border: none;
  padding: 0 4px;
  color: var(--accent);
  text-decoration: underline;
}

.small {
  font-size: 12px;
}
</style>
