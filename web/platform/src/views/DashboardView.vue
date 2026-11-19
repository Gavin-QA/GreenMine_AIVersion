<template>
  <div v-show="currentTab === 'dashboard'" class="dashboard-page">
    <!-- ==================== 第一层：顶部 4 张 KPI 概览卡 ==================== -->
    <div class="grid-4" style="margin-bottom: 16px;">
      <div class="kpi-card">
        <div class="kpi-title">预设任务方案</div>
        <div class="kpi-val">{{ presetTasks.length }}</div>
        <div class="kpi-sub">当前筛选匹配 {{ filteredPresets.length }} 项</div>
      </div>

      <div class="kpi-card green" style="cursor: pointer;" @click="currentTab = 'tasks'; assetsSubTab = 'runs'" title="点击查看历史巡检任务">
        <div class="kpi-title">累计巡检批次</div>
        <div class="kpi-val">{{ tasks.length }}</div>
        <div class="kpi-sub">已完成 {{ completedTasksCount }} 次巡检</div>
      </div>

      <div class="kpi-card warning" style="cursor: pointer;" @click="runningTasksCount > 0 ? (currentTab = 'monitor') : (currentTab = 'tasks', assetsSubTab = 'queue')" title="点击查看实时监控或调度队列">
        <div class="kpi-title">运行中 / 调度计划</div>
        <div class="kpi-val">
          <span :style="{ color: runningTasksCount > 0 ? 'var(--accent-cyan)' : 'var(--text-main)' }">{{ runningTasksCount }}</span>
          <span style="font-size: 14px; color: var(--text-muted); font-weight: 500; margin-left: 6px;">/ {{ pendingQueueCount }} 排队</span>
        </div>
        <div class="kpi-sub">{{ runningTasksCount > 0 ? '任务执行中，点击进入监控大屏' : '当前无运行中任务' }}</div>
      </div>

      <div class="kpi-card danger" style="cursor: pointer;" @click="currentTab = 'bugs'" title="点击进入缺陷治理中枢">
        <div class="kpi-title">未处理激活缺陷</div>
        <div class="kpi-val" :style="{ color: totalActiveBugsCount > 0 ? 'var(--accent-danger)' : 'var(--accent-green)' }">
          {{ totalActiveBugsCount }}
        </div>
        <div class="kpi-sub">{{ totalActiveBugsCount > 0 ? '点击前往缺陷治理中枢处理' : '当前无待处理激活缺陷' }}</div>
      </div>
    </div>

    <!-- ==================== 第二/三层：预设任务库与筛选列表 ==================== -->
    <div class="card" style="margin-bottom: 0;">
      <div class="card-header" style="flex-wrap: wrap; gap: 12px;">
        <div>
          <div class="card-title">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="var(--accent-cyan)" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2" />
            </svg>
            <span>标准预设巡检任务库</span>
            <span class="badge badge-running" style="font-weight: 500;">共 {{ filteredPresets.length }} / {{ presetTasks.length }} 项</span>
          </div>
          <div style="font-size: 12px; color: var(--text-muted); margin-top: 4px;">
            支持按矿山与模式快速筛选、卡片/列表视图切换，以及一键发起巡检或微调参数
          </div>
        </div>

        <div style="display: flex; align-items: center; gap: 10px; flex-wrap: wrap;">
          <!-- 视图切换 -->
          <div class="view-switch">
            <button
              type="button"
              class="view-switch-btn"
              :class="{ active: presetViewMode === 'card' }"
              @click="setPresetViewMode('card')"
              title="切换为卡片网格视图"
            >
              卡片视图
            </button>
            <button
              type="button"
              class="view-switch-btn"
              :class="{ active: presetViewMode === 'list' }"
              @click="setPresetViewMode('list')"
              title="切换为高密度数据列表视图"
            >
              列表视图
            </button>
          </div>

          <!-- 新建任务主按钮 -->
          <button
            type="button"
            class="btn btn-primary"
            @click="openNewTaskModal"
            title="唤起参数配置弹窗，新建巡检任务或保存为新预设"
          >
            <span>+ 新建任务</span>
          </button>
        </div>
      </div>

      <!-- 搜索与筛选条 -->
      <div class="filter-bar">
        <input
          v-model.trim="searchKeyword"
          type="text"
          class="form-control filter-input"
          placeholder="搜索预设任务名称..."
        />
        <select v-model="filterApp" class="form-control filter-select">
          <option value="">全部矿山应用</option>
          <option v-for="app in options.apps" :key="app.key" :value="app.key">
            {{ app.name }}
          </option>
        </select>
        <select v-model="filterMode" class="form-control filter-select">
          <option value="">全部运行模式</option>
          <option value="explore">自主探索</option>
          <option value="smoke">全量冒烟</option>
          <option value="case">用例回放</option>
        </select>
        <button
          v-if="searchKeyword || filterApp || filterMode"
          type="button"
          class="btn btn-secondary"
          @click="resetFilters"
        >
          重置
        </button>
      </div>

      <!-- 空状态 -->
      <div v-if="filteredPresets.length === 0" class="empty-box">
        <div style="font-size: 28px; margin-bottom: 10px;">📭</div>
        <div v-if="presetTasks.length === 0">暂无预设任务方案。点击右上角「+ 新建任务」按需配置并保存为新预设。</div>
        <div v-else>没有符合当前筛选条件的预设任务，请尝试调整搜索词或筛选条件。</div>
      </div>

      <!-- 1. 卡片网格视图 -->
      <div v-else-if="presetViewMode === 'card'" class="grid-3" style="margin-top: 14px;">
        <div v-for="p in filteredPresets" :key="p.id" class="preset-card">
          <div>
            <div class="preset-card-top">
              <span
                class="badge"
                :class="(p.tour || p.mode === 'smoke') ? 'badge-running' : (p.mode === 'case' ? 'badge-low' : 'badge-high')"
              >
                {{ getPresetModeLabel(p) }}
              </span>
              <button
                type="button"
                class="icon-del-btn"
                @click="deletePreset(p)"
                title="彻底删除此预设"
              >
                删除
              </button>
            </div>

            <div class="preset-app-tag">
              <span style="color: var(--accent-cyan);">●</span>
              <span>{{ getAppName(p.app_name) }}</span>
            </div>

            <div class="preset-title">{{ p.title }}</div>

            <div class="preset-meta">
              <span>步数：<b style="color: var(--text-main);">{{ p.max_steps ? p.max_steps + ' 步' : '无限制' }}</b></span>
              <span class="meta-sep">·</span>
              <span>时限：<b style="color: var(--accent-warning);">{{ p.max_times }} 分钟</b></span>
            </div>
          </div>

          <div class="preset-card-actions">
            <button
              type="button"
              class="btn btn-secondary btn-xs"
              style="flex: 1;"
              @click="openPresetDetail(p)"
              title="查看完整提示词与高阶参数"
            >
              详情
            </button>
            <button
              type="button"
              class="btn btn-secondary btn-xs"
              style="flex: 1;"
              @click="loadPresetToForm(p)"
              title="弹窗编辑配置，可微调并直接覆盖或另存"
            >
              编辑
            </button>
            <button
              type="button"
              class="btn btn-primary btn-xs"
              style="flex: 1.2;"
              @click="launchPreset(p)"
              title="立即以当前预设创建并启动巡检任务"
            >
              立即运行
            </button>
          </div>
        </div>
      </div>

      <!-- 2. 数据列表视图 -->
      <div v-else class="table-responsive" style="margin-top: 14px;">
        <table class="data-table">
          <thead>
            <tr>
              <th style="text-align: center; width: 56px;">序号</th>
              <th style="cursor: pointer; user-select: none; min-width: 200px;" @click="togglePresetSort('title')" title="点击按任务名称排序">
                <div style="display: inline-flex; align-items: center;">
                  <span>任务名称</span>
                  <span class="sort-arrows">
                    <svg viewBox="0 0 10 5" width="8" height="4"><polygon points="5,0 10,5 0,5" :fill="presetSortField === 'title' && presetSortOrder === 'asc' ? 'var(--accent-cyan)' : '#475569'" /></svg>
                    <svg viewBox="0 0 10 5" width="8" height="4"><polygon points="0,0 10,0 5,5" :fill="presetSortField === 'title' && presetSortOrder === 'desc' ? 'var(--accent-cyan)' : '#475569'" /></svg>
                  </span>
                </div>
              </th>
              <th style="cursor: pointer; user-select: none; min-width: 130px;" @click="togglePresetSort('app_name')" title="点击按运行矿山排序">
                <div style="display: inline-flex; align-items: center;">
                  <span>运行矿山</span>
                  <span class="sort-arrows">
                    <svg viewBox="0 0 10 5" width="8" height="4"><polygon points="5,0 10,5 0,5" :fill="presetSortField === 'app_name' && presetSortOrder === 'asc' ? 'var(--accent-cyan)' : '#475569'" /></svg>
                    <svg viewBox="0 0 10 5" width="8" height="4"><polygon points="0,0 10,0 5,5" :fill="presetSortField === 'app_name' && presetSortOrder === 'desc' ? 'var(--accent-cyan)' : '#475569'" /></svg>
                  </span>
                </div>
              </th>
              <th style="cursor: pointer; user-select: none; min-width: 110px;" @click="togglePresetSort('mode')" title="点击按运行模式排序">
                <div style="display: inline-flex; align-items: center;">
                  <span>运行模式</span>
                  <span class="sort-arrows">
                    <svg viewBox="0 0 10 5" width="8" height="4"><polygon points="5,0 10,5 0,5" :fill="presetSortField === 'mode' && presetSortOrder === 'asc' ? 'var(--accent-cyan)' : '#475569'" /></svg>
                    <svg viewBox="0 0 10 5" width="8" height="4"><polygon points="0,0 10,0 5,5" :fill="presetSortField === 'mode' && presetSortOrder === 'desc' ? 'var(--accent-cyan)' : '#475569'" /></svg>
                  </span>
                </div>
              </th>
              <th style="cursor: pointer; user-select: none; min-width: 130px;" @click="togglePresetSort('max_steps')" title="点击按最大步数限制排序">
                <div style="display: inline-flex; align-items: center;">
                  <span>最大步数</span>
                  <span class="sort-arrows">
                    <svg viewBox="0 0 10 5" width="8" height="4"><polygon points="5,0 10,5 0,5" :fill="presetSortField === 'max_steps' && presetSortOrder === 'asc' ? 'var(--accent-cyan)' : '#475569'" /></svg>
                    <svg viewBox="0 0 10 5" width="8" height="4"><polygon points="0,0 10,0 5,5" :fill="presetSortField === 'max_steps' && presetSortOrder === 'desc' ? 'var(--accent-cyan)' : '#475569'" /></svg>
                  </span>
                </div>
              </th>
              <th style="cursor: pointer; user-select: none; min-width: 120px;" @click="togglePresetSort('max_times')" title="点击按最长运行时间排序">
                <div style="display: inline-flex; align-items: center;">
                  <span>超时时限</span>
                  <span class="sort-arrows">
                    <svg viewBox="0 0 10 5" width="8" height="4"><polygon points="5,0 10,5 0,5" :fill="presetSortField === 'max_times' && presetSortOrder === 'asc' ? 'var(--accent-cyan)' : '#475569'" /></svg>
                    <svg viewBox="0 0 10 5" width="8" height="4"><polygon points="0,0 10,0 5,5" :fill="presetSortField === 'max_times' && presetSortOrder === 'desc' ? 'var(--accent-cyan)' : '#475569'" /></svg>
                  </span>
                </div>
              </th>
              <th style="min-width: 260px;">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(p, index) in filteredPresets" :key="p.id">
              <td style="text-align: center; color: var(--text-muted); font-family: monospace;">
                {{ index + 1 }}
              </td>
              <td>
                <span style="font-weight: 600; color: var(--text-main);">{{ p.title }}</span>
              </td>
              <td>
                <span style="color: var(--accent-cyan); font-weight: 500; font-size: 12px;">
                  {{ getAppName(p.app_name) }}
                </span>
              </td>
              <td>
                <span
                  class="badge"
                  :class="(p.tour || p.mode === 'smoke') ? 'badge-running' : (p.mode === 'case' ? 'badge-low' : 'badge-high')"
                >
                  {{ getPresetModeLabel(p) }}
                </span>
              </td>
              <td>
                <span style="font-family: monospace;" :style="{ color: p.max_steps ? 'var(--text-main)' : 'var(--text-muted)' }">
                  {{ p.max_steps ? (p.max_steps + ' 步') : '无限制' }}
                </span>
              </td>
              <td>
                <span style="font-family: monospace; color: var(--accent-warning);">
                  {{ p.max_times }} 分钟
                </span>
              </td>
              <td style="white-space: nowrap;">
                <div style="display: inline-flex; align-items: center; gap: 6px;">
                  <button type="button" class="btn btn-secondary btn-xs" @click="openPresetDetail(p)" title="查看完整提示词与详细参数">详情</button>
                  <button type="button" class="btn btn-secondary btn-xs" @click="loadPresetToForm(p)" title="弹窗编辑配置">编辑</button>
                  <button type="button" class="btn btn-primary btn-xs" @click="launchPreset(p)" title="立即启动巡检">立即运行</button>
                  <button type="button" class="btn btn-danger btn-xs" @click="deletePreset(p)" title="删除此预设">删除</button>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  </div>
</template>

<script>
import { inject, ref, computed } from 'vue'

export default {
  name: 'DashboardView',
  setup() {
    const store = inject('platformStore')

    const searchKeyword = ref('')
    const filterApp = ref('')
    const filterMode = ref('')

    function resetFilters() {
      searchKeyword.value = ''
      filterApp.value = ''
      filterMode.value = ''
    }

    const filteredPresets = computed(() => {
      const list = store.sortedPresetTasks.value || []
      const kw = searchKeyword.value.toLowerCase()
      return list.filter((p) => {
        if (filterApp.value && p.app_name !== filterApp.value) return false
        if (filterMode.value) {
          const isSmoke = Boolean(p.tour || p.mode === 'smoke')
          const normalized = isSmoke ? 'smoke' : (p.mode || 'explore')
          if (normalized !== filterMode.value) return false
        }
        if (kw) {
          const title = String(p.title || '').toLowerCase()
          const appLabel = String(store.getAppName(p.app_name) || '').toLowerCase()
          if (!title.includes(kw) && !appLabel.includes(kw)) return false
        }
        return true
      })
    })

    const runningTasksCount = computed(() =>
      (store.tasks.value || []).filter((t) => t.status === 'running').length
    )

    const completedTasksCount = computed(() =>
      (store.tasks.value || []).filter((t) => t.status === 'completed').length
    )

    const totalActiveBugsCount = computed(() =>
      (store.tasks.value || []).reduce((acc, t) => acc + (Number(t.active_bugs_count) || 0), 0)
    )

    return {
      ...store,
      searchKeyword,
      filterApp,
      filterMode,
      resetFilters,
      filteredPresets,
      runningTasksCount,
      completedTasksCount,
      totalActiveBugsCount,
    }
  },
}
</script>

<style scoped>
.view-switch {
  display: inline-flex;
  background: var(--bg-elevated);
  border: 1px solid var(--border-color);
  border-radius: 6px;
  padding: 2px;
}

.view-switch-btn {
  padding: 4px 12px;
  font-size: 12px;
  border-radius: 4px;
  border: none;
  background: transparent;
  color: var(--text-muted);
  cursor: pointer;
  transition: all 0.15s ease;
}

.view-switch-btn.active {
  background: linear-gradient(135deg, #6366f1, #4f46e5);
  color: #ffffff;
  font-weight: 600;
  box-shadow: 0 2px 8px rgba(99, 102, 241, 0.35);
}

.filter-bar {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 10px;
  padding-bottom: 14px;
  border-bottom: 1px solid var(--border-color);
}

.filter-input {
  max-width: 260px;
  height: 32px;
  padding: 0 12px;
}

.filter-select {
  width: auto;
  min-width: 140px;
  height: 32px;
  padding: 0 10px;
}

.empty-box {
  padding: 40px 24px;
  text-align: center;
  color: var(--text-muted);
  font-size: 13px;
}

.preset-card {
  background: var(--bg-elevated);
  border: 1px solid var(--border-color);
  border-radius: 14px;
  padding: 16px 18px;
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  transition: transform 0.2s ease, border-color 0.2s ease, box-shadow 0.2s ease;
}

.preset-card:hover {
  transform: translateY(-2px);
  border-color: var(--border-strong);
  box-shadow: 0 10px 24px rgba(0, 0, 0, 0.4);
}

.preset-card-top {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 10px;
}

.icon-del-btn {
  background: transparent;
  border: 1px solid rgba(240, 82, 82, 0.25);
  border-radius: 4px;
  color: #ff6b6b;
  cursor: pointer;
  padding: 2px 8px;
  font-size: 11px;
  transition: all 0.15s ease;
}

.icon-del-btn:hover {
  background: rgba(240, 82, 82, 0.16);
  border-color: var(--accent-danger);
}

.preset-app-tag {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: var(--text-muted);
  margin-bottom: 6px;
}

.preset-title {
  font-weight: 600;
  font-size: 14px;
  color: var(--text-main);
  margin-bottom: 10px;
  line-height: 1.4;
}

.preset-meta {
  font-size: 12px;
  color: var(--text-muted);
  margin-bottom: 14px;
}

.meta-sep {
  margin: 0 6px;
}

.preset-card-actions {
  display: flex;
  gap: 8px;
  margin-top: auto;
  border-top: 1px solid var(--border-color);
  padding-top: 12px;
  align-items: center;
}

.btn-xs {
  height: 28px;
  padding: 0 10px;
  font-size: 12px;
}

.sort-arrows {
  display: inline-flex;
  flex-direction: column;
  align-items: center;
  vertical-align: middle;
  margin-left: 6px;
  gap: 2px;
}
</style>
