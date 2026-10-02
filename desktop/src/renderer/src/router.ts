import { createRouter, createWebHashHistory, type RouteRecordRaw } from 'vue-router'

import BookDetailView from './views/BookDetailView.vue'
import HomeView from './views/HomeView.vue'
import SearchView from './views/SearchView.vue'
import SourcesView from './views/SourcesView.vue'
import TasksView from './views/TasksView.vue'

const routes: RouteRecordRaw[] = [
  { path: '/', name: 'home', component: HomeView, meta: { title: '首页' } },
  { path: '/search', name: 'search', component: SearchView, meta: { title: '搜索' } },
  { path: '/books/:id', name: 'book', component: BookDetailView, props: true },
  { path: '/tasks', name: 'tasks', component: TasksView, meta: { title: '下载' } },
  { path: '/sources', name: 'sources', component: SourcesView, meta: { title: '书源' } }
]

export const router = createRouter({
  // 打包后从 file:// 加载，hash 模式最稳
  history: createWebHashHistory(),
  routes
})
