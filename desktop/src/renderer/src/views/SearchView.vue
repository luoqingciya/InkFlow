<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { api, type SearchItem } from '../api/client'

const route = useRoute()
const router = useRouter()

const keyword = ref((route.query.q as string) ?? '')
const items = ref<SearchItem[]>([])
const sourceErrors = ref<Record<string, string>>({})
const searching = ref(false)
const error = ref<string | null>(null)
const searched = ref(false)

async function run(): Promise<void> {
  const query = keyword.value.trim()
  if (!query) return

  searching.value = true
  error.value = null
  try {
    const result = await api.search(query)
    items.value = result.items
    sourceErrors.value = result.source_errors
    searched.value = true
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
    items.value = []
  } finally {
    searching.value = false
  }
}

function open(item: SearchItem): void {
  // 默认使用评分最高的来源
  const primary = item.sources[0]
  if (primary) router.push(`/books/${primary.book_id}`)
}

onMounted(() => {
  if (keyword.value) void run()
})
</script>

<template>
  <div>
    <h1>搜索</h1>

    <div class="card search-bar">
      <input v-model="keyword" placeholder="书名或作者" @keyup.enter="run" />
      <button class="primary" :disabled="searching" @click="run">
        {{ searching ? '搜索中…' : '搜索' }}
      </button>
    </div>

    <p v-if="error" class="error">{{ error }}</p>

    <div v-if="Object.keys(sourceErrors).length" class="card warn">
      <div class="dim small">以下书源未能返回结果：</div>
      <div v-for="(message, id) in sourceErrors" :key="id" class="dim small">
        · {{ id }}：{{ message }}
      </div>
    </div>

    <p v-if="searched && items.length === 0 && !error" class="dim">没有找到结果。</p>

    <table v-if="items.length">
      <thead>
        <tr>
          <th>书名</th>
          <th>作者</th>
          <th>来源</th>
          <th>最新章节</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="(item, index) in items" :key="index" class="row" @click="open(item)">
          <td>{{ item.name }}</td>
          <td>{{ item.author || '—' }}</td>
          <td>
            {{ item.sources.map((s) => s.source_name).join('、') }}
            <span v-if="item.sources.length > 1" class="dim small">
              （{{ item.sources.length }} 个来源）
            </span>
          </td>
          <td class="dim small">{{ item.sources[0]?.latest_chapter || '—' }}</td>
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

h2 {
  margin: 28px 0 12px;
  font-size: 15px;
  color: var(--text-dim);
  font-weight: 500;
}

.search-bar {
  display: flex;
  gap: 10px;
  margin-bottom: 16px;
}

.search-bar input {
  flex: 1;
}

.warn {
  border-color: var(--warning);
  margin-bottom: 12px;
}

.row {
  cursor: pointer;
}

.small {
  font-size: 12px;
}
</style>
