<script setup lang="ts">
import { onMounted, onUnmounted, ref } from 'vue'

import { api, watchTask, type DownloadTask } from '../api/client'

const tasks = ref<DownloadTask[]>([])
const loading = ref(true)
const error = ref<string | null>(null)
/** task_id → 实时进度 */
const live = ref<Record<string, { percent: number; current: string; speed: string }>>({})

let closers: Array<() => void> = []
let poller: number | undefined
/** 已建立订阅的任务 ID，避免每次刷新都重复开连接 */
const watched = new Set<string>()

const ACTIVE = new Set(['PENDING', 'RUNNING', 'PAUSED'])

async function load(): Promise<void> {
  try {
    const result = await api.listTasks()
    tasks.value = result.items
    await attachWatchers()
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    loading.value = false
  }
}

/** 为每个进行中的任务建立 WebSocket 订阅（幂等）。 */
async function attachWatchers(): Promise<void> {
  const active = tasks.value.filter((task) => ACTIVE.has(task.status))
  for (const task of active) {
    if (watched.has(task.id)) continue
    watched.add(task.id)
    const close = await watchTask(task.id, (event) => {
      const type = event.type as string
      if (type === 'progress' || type === 'snapshot') {
        live.value[task.id] = {
          percent: Number(event.percent ?? 0),
          current: String(event.current ?? ''),
          speed: String(event.speed ?? '')
        }
      }
      if (type === 'completed' || type === 'error' || type === 'status') {
        void load()
      }
    })
    closers.push(close)
  }
}

async function control(task: DownloadTask, action: 'pause' | 'resume' | 'cancel'): Promise<void> {
  try {
    await api[`${action}Task`](task.id)
    await load()
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  }
}

async function reveal(path: string): Promise<void> {
  if (path) await window.inkflow.revealPath(path)
}

onMounted(() => {
  void load()
  // WebSocket 负责实时进度；轮询兜底，防止连接被中间设备掐断后界面卡死
  poller = window.setInterval(load, 5000)
})

onUnmounted(() => {
  closers.forEach((close) => close())
  closers = []
  watched.clear()
  if (poller) window.clearInterval(poller)
})
</script>

<template>
  <div>
    <h1>下载</h1>

    <p v-if="error" class="error">{{ error }}</p>
    <p v-if="loading" class="dim">加载中…</p>
    <p v-else-if="tasks.length === 0" class="dim">
      还没有下载任务。去「搜索」找一本书，在详情页开始下载。
    </p>

    <div v-for="task in tasks" :key="task.id" class="card task">
      <div class="task-head">
        <span class="status">{{ task.status }}</span>
        <span class="dim small">{{ task.id }}</span>
        <div class="spacer" />
        <button v-if="task.status === 'RUNNING'" @click="control(task, 'pause')">暂停</button>
        <button v-if="task.status === 'PAUSED'" @click="control(task, 'resume')">恢复</button>
        <button v-if="ACTIVE.has(task.status)" @click="control(task, 'cancel')">取消</button>
      </div>

      <div class="progress-track">
        <div
          class="progress-fill"
          :style="{ width: `${live[task.id]?.percent ?? (task.total ? (task.completed / task.total) * 100 : 0)}%` }"
        />
      </div>

      <div class="task-meta dim small">
        <span>{{ task.completed }} / {{ task.total }} 章</span>
        <span v-if="task.failed">失败 {{ task.failed }}</span>
        <span v-if="live[task.id]?.current">正在下载：{{ live[task.id].current }}</span>
        <span v-if="live[task.id]?.speed">{{ live[task.id].speed }}</span>
        <span>{{ task.output_format }}</span>
      </div>

      <div v-if="task.output_path" class="small">
        输出：
        <button class="link" @click="reveal(task.output_path)">{{ task.output_path }}</button>
      </div>

      <div v-if="task.error" class="error small">{{ task.error }}</div>
    </div>
  </div>
</template>

<style scoped>
h1 {
  margin: 0 0 20px;
  font-size: 22px;
}

.task {
  margin-bottom: 12px;
}

.task-head {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 10px;
}

.status {
  font-weight: 500;
}

.spacer {
  flex: 1;
}

.task-meta {
  display: flex;
  gap: 14px;
  flex-wrap: wrap;
  margin-top: 8px;
}

.link {
  background: none;
  border: none;
  padding: 0;
  color: var(--accent);
  text-decoration: underline;
  font-size: 12px;
}

.small {
  font-size: 12px;
}
</style>
