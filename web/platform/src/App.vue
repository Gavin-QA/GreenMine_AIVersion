<template>
  <div id="app-shell" style="display: flex; width: 100vw; height: 100vh; overflow: hidden;">
    <aside class="sidebar" :class="{ collapsed: sidebarCollapsed }">
      <!-- Brand Header -->
      <div class="brand">
        <div class="brand-logo" @click="currentTab = 'dashboard'" style="cursor: pointer;">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2" />
          </svg>
        </div>
        <div v-show="!sidebarCollapsed" class="brand-text">
          <div class="brand-title">AI 自动化测试平台</div>
        </div>
        <button
          type="button"
          class="sidebar-toggle-btn"
          @click="sidebarCollapsed = !sidebarCollapsed"
          :title="sidebarCollapsed ? '展开侧边栏' : '收起侧边栏'"
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <polyline v-if="sidebarCollapsed" points="9 18 15 12 9 6" />
            <polyline v-else points="15 18 9 12 15 6" />
          </svg>
        </button>
      </div>

      <!-- Navigation Menu -->
      <ul class="nav-menu">
        <li v-show="!sidebarCollapsed" class="nav-group-label">工作空间</li>

        <li class="nav-item" :class="{ active: currentTab === 'dashboard' }" @click="currentTab = 'dashboard'" title="任务控制台">
          <svg class="nav-svg" viewBox="0 0 24 24">
            <rect x="3" y="3" width="7" height="7" rx="1" />
            <rect x="14" y="3" width="7" height="7" rx="1" />
            <rect x="14" y="14" width="7" height="7" rx="1" />
            <rect x="3" y="14" width="7" height="7" rx="1" />
          </svg>
          <span v-show="!sidebarCollapsed" class="nav-label">任务控制台</span>
        </li>

        <li class="nav-item" :class="{ active: currentTab === 'monitor' }" @click="currentTab = 'monitor'" title="实时监控大屏">
          <svg class="nav-svg" viewBox="0 0 24 24">
            <polyline points="22 12 18 12 15 21 9 3 6 12 2 12" />
          </svg>
          <span v-show="!sidebarCollapsed" class="nav-label">实时监控大屏</span>
        </li>

        <li v-show="!sidebarCollapsed" class="nav-group-label" style="margin-top: 12px;">任务与产物</li>

        <li class="nav-group">
          <div
            class="nav-item"
            :class="{ active: currentTab === 'tasks' }"
            @click="onGroupClick('tasks')"
            title="任务与产物库"
          >
            <svg class="nav-svg" viewBox="0 0 24 24">
              <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z" />
            </svg>
            <span v-show="!sidebarCollapsed" class="nav-label" style="flex: 1;">任务与产物库</span>
            <svg v-show="!sidebarCollapsed" class="chevron-svg" :class="{ rotated: navExpanded.tasks }" viewBox="0 0 24 24">
              <polyline points="9 18 15 12 9 6" />
            </svg>
          </div>
          <ul v-show="!sidebarCollapsed && navExpanded.tasks" class="sub-nav-menu">
            <li class="sub-nav-item" :class="{ active: currentTab === 'tasks' && assetsSubTab === 'runs' }"
              @click="currentTab = 'tasks'; assetsSubTab = 'runs'">
              <span class="sub-dot"></span>
              <span>历史巡检任务</span>
            </li>
            <li class="sub-nav-item" :class="{ active: currentTab === 'tasks' && assetsSubTab === 'queue' }"
              @click="currentTab = 'tasks'; assetsSubTab = 'queue'">
              <span class="sub-dot"></span>
              <span>调度执行队列</span>
            </li>
            <li class="sub-nav-item" :class="{ active: currentTab === 'tasks' && assetsSubTab === 'cases' }"
              @click="currentTab = 'tasks'; assetsSubTab = 'cases'">
              <span class="sub-dot"></span>
              <span>用例资产管理</span>
            </li>
          </ul>
        </li>

        <li v-show="!sidebarCollapsed" class="nav-group-label" style="margin-top: 12px;">治理与系统</li>

        <li class="nav-item" :class="{ active: currentTab === 'bugs' }" @click="currentTab = 'bugs'" title="缺陷治理中枢">
          <svg class="nav-svg" viewBox="0 0 24 24">
            <path d="m8 2 1.88 1.88" />
            <path d="M14.12 3.88 16 2" />
            <path d="M9 7.13v-1a3.003 3.003 0 1 1 6 0v1" />
            <path d="M12 20c-3.3 0-6-2.7-6-6v-3a4 4 0 0 1 4-4h4a4 4 0 0 1 4 4v3c0 3.3-2.7 6-6 6" />
            <path d="M12 20v-9" />
            <path d="M6.53 9C4.6 8.8 3 7.1 3 5" />
            <path d="M6 13H2" />
            <path d="M3 21c0-2.1 1.7-3.9 3.8-4" />
            <path d="M20.97 5c0 2.1-1.6 3.8-3.5 4" />
            <path d="M22 13h-4" />
            <path d="M17.2 17c2.1.1 3.8 1.9 3.8 4" />
          </svg>
          <span v-show="!sidebarCollapsed" class="nav-label">缺陷治理中枢</span>
        </li>

        <li class="nav-group">
          <div
            class="nav-item"
            :class="{ active: currentTab === 'settings' }"
            @click="onGroupClick('settings')"
            title="系统配置"
          >
            <svg class="nav-svg" viewBox="0 0 24 24">
              <circle cx="12" cy="12" r="3" />
              <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z" />
            </svg>
            <span v-show="!sidebarCollapsed" class="nav-label" style="flex: 1;">系统配置</span>
            <svg v-show="!sidebarCollapsed" class="chevron-svg" :class="{ rotated: navExpanded.settings }" viewBox="0 0 24 24">
              <polyline points="9 18 15 12 9 6" />
            </svg>
          </div>
          <ul v-show="!sidebarCollapsed && navExpanded.settings" class="sub-nav-menu">
            <li class="sub-nav-item" :class="{ active: currentTab === 'settings' && settingsSubTab === 'overview' }"
              @click="currentTab = 'settings'; settingsSubTab = 'overview'">
              <span class="sub-dot"></span>
              <span>配置总览</span>
            </li>
            <li class="sub-nav-item" :class="{ active: currentTab === 'settings' && settingsSubTab === 'cleanup' }"
              @click="currentTab = 'settings'; settingsSubTab = 'cleanup'">
              <span class="sub-dot"></span>
              <span>磁盘清理</span>
            </li>
          </ul>
        </li>
      </ul>

      <!-- 底座物理状态探测（精简面板） -->
      <div v-show="!sidebarCollapsed" class="sidebar-status">
        <div class="status-target">
          <span class="status-target-label">探针目标</span>
          <span class="status-target-val">{{ currentAppName }}</span>
        </div>
        <div class="status-row">
          <span class="status-row-left">
            <span class="dot" :style="{ background: liveSnapshot.ue_online ? 'var(--accent-green)' : 'var(--accent-danger)' }"></span>
            <span>UE5 伴生进程</span>
          </span>
          <span class="status-row-val" :style="{ color: liveSnapshot.ue_online ? 'var(--accent-green)' : 'var(--text-muted)' }">
            {{ liveSnapshot.ue_online ? 'PID ' + liveSnapshot.ue_pid : '离线' }}
          </span>
        </div>
        <div class="status-row">
          <span class="status-row-left">
            <span class="dot" :style="{ background: liveSnapshot.cdp_online ? 'var(--accent-cyan)' : '#4b5a6b' }"></span>
            <span>CDP 调试直连</span>
          </span>
          <span class="status-row-val" :style="{ color: liveSnapshot.cdp_online ? 'var(--accent-cyan)' : 'var(--text-muted)' }">
            {{ liveSnapshot.cdp_online ? '在线' : '待命' }}
          </span>
        </div>
      </div>
    </aside>

    <!-- 主展示区 -->
    <main class="main-content">
      <header class="top-bar">
        <!-- 左侧面包屑标题 -->
        <div class="page-title">
          <template v-if="currentTab === 'dashboard'">
            <span class="crumb-root">工作空间</span>
            <span class="crumb-sep">/</span>
            <span class="crumb-cur">任务控制台</span>
          </template>
          <template v-else-if="currentTab === 'monitor'">
            <span class="crumb-root">工作空间</span>
            <span class="crumb-sep">/</span>
            <span class="crumb-cur">
              实时监控大屏 · {{ activeTaskId === '__live__' ? '本机物理环境实时心电图' : (activeTask ? activeTask.name : '未选择任务') }}
            </span>
          </template>
          <template v-else-if="currentTab === 'tasks'">
            <span class="crumb-root">任务与产物</span>
            <span class="crumb-sep">/</span>
            <span class="crumb-cur">
              {{ assetsSubTab === 'queue' ? '调度执行队列' : (assetsSubTab === 'cases' ? '用例资产管理' : '历史巡检任务') }}
            </span>
          </template>
          <template v-else-if="currentTab === 'bugs'">
            <span class="crumb-root">治理与系统</span>
            <span class="crumb-sep">/</span>
            <span class="crumb-cur">缺陷治理中枢</span>
          </template>
          <template v-else-if="currentTab === 'settings'">
            <span class="crumb-root">治理与系统</span>
            <span class="crumb-sep">/</span>
            <span class="crumb-cur">{{ settingsSubTab === 'cleanup' ? '磁盘清理' : '配置总览' }}</span>
          </template>
        </div>

        <!-- 右侧紧凑工具栏 -->
        <div class="top-actions">
          <button class="btn btn-secondary" @click="triggerHotSync" :disabled="isSyncing" title="重新扫描磁盘上的最新测试运行批次与全局缺陷">
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <polyline points="23 4 23 10 17 10" />
              <polyline points="1 20 1 14 7 14" />
              <path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15" />
            </svg>
            <span>{{ isSyncing ? '同步中...' : '同步数据' }}</span>
          </button>

          <a :href="options.report_hub_url || '/report-hub'" target="_blank" class="btn btn-secondary" title="打开测试报告平台 (Report Hub)">
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6" />
              <polyline points="15 3 21 3 21 9" />
              <line x1="10" y1="14" x2="21" y2="3" />
            </svg>
            <span>测试报告平台</span>
          </a>
        </div>
      </header>

      <div class="content-body">
        <DashboardView />
        <MonitorView />
        <TasksAssetsView />
        <BugsHubView />
        <SystemConfigView />
      </div>
    </main>
    <GlobalModals />
  </div>
</template>

<script>
import { provide, ref } from 'vue'
import { usePlatformStore } from './composables/usePlatformStore'
import DashboardView from './views/DashboardView.vue'
import MonitorView from './views/MonitorView.vue'
import TasksAssetsView from './views/TasksAssetsView.vue'
import BugsHubView from './views/BugsHubView.vue'
import SystemConfigView from './views/SystemConfigView.vue'
import GlobalModals from './components/GlobalModals.vue'

export default {
  components: {
    DashboardView,
    MonitorView,
    TasksAssetsView,
    BugsHubView,
    SystemConfigView,
    GlobalModals,
  },
  setup() {
    const store = usePlatformStore()
    provide('platformStore', store)

    const sidebarCollapsed = ref(false)

    function onGroupClick(tab) {
      if (sidebarCollapsed.value) {
        sidebarCollapsed.value = false
      }
      store.selectPrimaryMenu(tab)
    }

    return {
      ...store,
      sidebarCollapsed,
      onGroupClick,
    }
  }
}
</script>
