<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'

import { api, type Book, type DownloadTask } from '../api/client'

const router = useRouter()
const keyword = ref('')
const books = ref<Book[]>([])
const tasks = ref<DownloadTask[]>([])
const loading = ref(true)

async function load(): Promise<void> {
  loading.value = true
  try {
    const [bookResult, taskResult] = await Promise.all([api.listBooks(8), api.listTasks()])
    books.value = bookResult.items
    tasks.value = taskResult.items.slice(0, 5)
  } finally {
    loading.value = false
  }
}

function goSearch(): void {
  const query = keyword.value.trim()
  router.push({ path: '/search', query: query ? { q: query } : {} })
}

onMounted(load)
</script>

<template>
  <div>
    <h1>InkFlow</h1>

    <div class="card search-card">
      <input
        v-model="keyword"
        placeholder="搜索小说，回车开始"
        @keyup.enter="goSearch"
      />
      <button class="primary" @click="goSearch">搜索</button>
    </div>

    <section>
      <h2>最近入库</h2>
      <p v-if="loading" class="dim">加载中…</p>
      <p v-else-if="books.length === 0" class="dim">
        书库还是空的。先去「搜索」找一本书，或到「书源」导入一个书源。
      </p>
      <div v-else class="grid">
        <div
          v-for="book in books"
          :key="book.id"
          class="card book-card"
          @click="router.push(`/books/${book.id}`)"
        >
          <div class="book-name">{{ book.name }}</div>
          <div class="dim small">{{ book.author || '未知作者' }}</div>
        </div>
      </div>
    </section>

    <section v-if="tasks.length">
      <h2>最近任务</h2>
      <table>
        <thead>
          <tr><th>状态</th><th>进度</th><th>输出</th></tr>
        </thead>
        <tbody>
          <tr v-for="task in tasks" :key="task.id">
            <td>{{ task.status }}</td>
            <td>{{ task.completed }} / {{ task.total }}</td>
            <td class="dim small">{{ task.output_path || '—' }}</td>
          </tr>
        </tbody>
      </table>
    </section>
  </div>
</template>

<style scoped>
h1 {
  margin: 0 0 20px;
  font-size: 22px;
}

h2 {
  margin: 28px 0 12px;
  font-size: 15px;
  color: var(--text-dim);
  font-weight: 500;
}

.search-card {
  display: flex;
  gap: 10px;
}

.search-card input {
  flex: 1;
}

.grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(160px, 1fr));
  gap: 12px;
}

.book-card {
  cursor: pointer;
  transition: border-color 0.15s;
}

.book-card:hover {
  border-color: var(--accent-dim);
}

.book-name {
  font-weight: 500;
  margin-bottom: 4px;
}

.small {
  font-size: 12px;
}
</style>
