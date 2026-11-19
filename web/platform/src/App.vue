<template>
  <div id="app-shell" style="display: flex; width: 100vw; height: 100vh; overflow: hidden;">
    <aside class="sidebar">

      <div class="brand">

        <div class="brand-icon">⚡</div>

        <div>

          <div class="brand-title">Vision Platform</div>

          <div class="brand-sub">多模态巡检与性能中枢</div>

        </div>

      </div>



      <ul class="nav-menu">

        <!-- 1. 任务控制台 -->
        <li class="nav-item" :class="{ active: currentTab === 'dashboard' }" @click="currentTab = 'dashboard'">
          <span class="nav-icon">📊</span>
          <span>任务控制台</span>
        </li>

        <!-- 2. 实时监控大屏 -->
        <li class="nav-item" :class="{ active: currentTab === 'monitor' }" @click="currentTab = 'monitor'">
          <span class="nav-icon">📈</span>
          <span>实时监控大屏</span>
        </li>

        <!-- 3. 任务与产物库 (默认收起，可展开/收起) -->
        <li class="nav-group">
          <div class="nav-item" :class="{ active: currentTab === 'tasks' && !assetsSubTab }"
            @click="selectPrimaryMenu('tasks')"
            style="justify-content: space-between;">
            <div style="display: flex; align-items: center; gap: 10px;">
              <span class="nav-icon">📁</span>
              <span style="font-weight: 600;">任务与产物库</span>
            </div>
            <span style="font-size: 11px; color: var(--text-muted);">{{ navExpanded.tasks ? '▾' : '▸' }}</span>
          </div>
          <ul v-show="navExpanded.tasks" class="sub-nav-menu">
            <li class="sub-nav-item" :class="{ active: currentTab === 'tasks' && assetsSubTab === 'runs' }"
              @click="currentTab = 'tasks'; assetsSubTab = 'runs'">
              <span style="margin-right: 6px;">📑</span>
              <span>历史巡检任务</span>
            </li>
            <li class="sub-nav-item" :class="{ active: currentTab === 'tasks' && assetsSubTab === 'queue' }"
              @click="currentTab = 'tasks'; assetsSubTab = 'queue'">
              <span style="margin-right: 6px;">⏱️</span>
              <span style="flex: 1;">调度执行队列</span>
            </li>
            <li class="sub-nav-item" :class="{ active: currentTab === 'tasks' && assetsSubTab === 'cases' }"
              @click="currentTab = 'tasks'; assetsSubTab = 'cases'">
              <span style="margin-right: 6px;">🧪</span>
              <span>用例资产管理</span>
            </li>
          </ul>
        </li>

        <!-- 4. 缺陷治理中枢 -->
        <li class="nav-item" :class="{ active: currentTab === 'bugs' }" @click="currentTab = 'bugs'">
          <span class="nav-icon">🐛</span>
          <span>缺陷治理中枢</span>
        </li>

        <!-- 5. 系统配置 (默认收起，可展开/收起) -->
        <li class="nav-group">
          <div class="nav-item" :class="{ active: currentTab === 'settings' && !settingsSubTab }"
            @click="selectPrimaryMenu('settings')"
            style="justify-content: space-between;">
            <div style="display: flex; align-items: center; gap: 10px;">
              <span class="nav-icon">⚙️</span>
              <span style="font-weight: 600;">系统配置</span>
            </div>
            <span style="font-size: 11px; color: var(--text-muted);">{{ navExpanded.settings ? '▾' : '▸' }}</span>
          </div>
          <ul v-show="navExpanded.settings" class="sub-nav-menu">
            <li class="sub-nav-item" :class="{ active: currentTab === 'settings' && settingsSubTab === 'overview' }"
              @click="currentTab = 'settings'; settingsSubTab = 'overview'">
              <span style="margin-right: 6px;">📋</span>
              <span>配置总览</span>
            </li>
            <li class="sub-nav-item" :class="{ active: currentTab === 'settings' && settingsSubTab === 'cleanup' }"
              @click="currentTab = 'settings'; settingsSubTab = 'cleanup'">
              <span style="margin-right: 6px;">🧹</span>
              <span>磁盘清理</span>
            </li>
          </ul>
        </li>

      </ul>



      <!-- 底座物理状态探测 -->

      <div class="sidebar-status">

        <div>探针目标: <b style="color: #00d2ff;">{{ currentAppName }}</b></div>

        <div class="status-badge"
          :style="{ background: liveSnapshot.ue_online ? 'rgba(0, 230, 118, 0.1)' : 'rgba(255, 82, 82, 0.1)', color: liveSnapshot.ue_online ? '#00e676' : '#ff5252' }">

          <span class="dot" :style="{ background: liveSnapshot.ue_online ? '#00e676' : '#ff5252' }"></span>

          <span>UE5 伴生进程: {{ liveSnapshot.ue_online ? '在线 (PID ' + liveSnapshot.ue_pid + ')' : '离线' }}</span>

        </div>

        <div class="status-badge" style="margin-top: 4px;"
          :style="{ background: liveSnapshot.cdp_online ? 'rgba(0, 210, 255, 0.1)' : 'rgba(139, 155, 180, 0.1)', color: liveSnapshot.cdp_online ? '#00d2ff' : '#8b9bb4' }">

          <span class="dot" :style="{ background: liveSnapshot.cdp_online ? '#00d2ff' : '#8b9bb4' }"></span>

          <span>CDP 调试直连: {{ liveSnapshot.cdp_online ? '在线' : '待命' }}</span>

        </div>

      </div>

    </aside>



    <!-- 主展示区 -->

    <main class="main-content">

      <header class="top-bar">

        <div class="page-title">

          <span v-if="currentTab === 'dashboard'">🚀 任务发起与快速调度</span>

          <span v-if="currentTab === 'monitor'">📈 双核性能与日志流大屏 ({{ activeTaskId === '__live__' ? '⚡ 本机物理环境实时心电图' :
            (activeTask ? activeTask.name : '未选择任务') }})</span>

          <span v-if="currentTab === 'tasks'">📁 任务与产物库</span>

          <span v-if="currentTab === 'bugs'">🐛 缺陷知识库与禅道协同</span>

          <span v-if="currentTab === 'settings'">
            {{ settingsSubTab === 'cleanup' ? '🧹 系统配置 · 磁盘清理' : '⚙️ 系统配置 · 配置总览' }}
          </span>

        </div>

        <div class="top-actions">

          <div
            style="display: flex; align-items: center; gap: 8px; height: 32px; background: var(--bg-elevated); padding: 0 12px; border-radius: 4px; border: 1px solid var(--border-strong);">

            <span style="font-size: 12px; color: var(--text-muted); font-weight: 500;">目标矿山:</span>

            <select v-model="taskForm.app_name" @change="changeLiveApp(taskForm.app_name)"
              style="background: transparent; color: var(--text-main); border: none; font-weight: 600; font-size: 13px; cursor: pointer; outline: none;">

              <option v-for="app in options.apps" :key="app.key" :value="app.key" style="background: #0a0a0a; color: #ededed;">

                {{ app.name }}

              </option>

            </select>

          </div>

          <button class="btn btn-secondary" @click="triggerHotSync" :disabled="isSyncing"
            title="重新扫描磁盘上的最新测试运行批次与全局缺陷">

            <span>{{ isSyncing ? '⏳ 同步中...' : '⚡ 立即同步磁盘数据' }}</span>

          </button>

          <button class="btn btn-primary" @click="currentTab = 'dashboard'">+ 新建任务</button>

          <a :href="options.report_hub_url || '/report-hub'" target="_blank" class="btn btn-secondary">

            🌐 产物总门户

          </a>

        </div>

      </header>



      <div class="content-body">

        <!-- ============================================================= -->

        <!-- 1. 任务控制台 (免敲命令，选项化表单与预设任务库) -->

        <!-- ============================================================= -->

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
import { provide } from 'vue'
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
    return store
  }
}
</script>
