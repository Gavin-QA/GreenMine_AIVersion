<template>
        <div v-show="currentTab === 'tasks'">

          <!-- 子模块 1: 历史巡检任务 -->
          <div v-show="assetsSubTab === 'runs'">

            <!-- 1. 独立筛选栏卡片 (同级第 1 个 div，与下方列表清晰分离) -->
            <div class="card"
              style="margin-bottom: 16px; padding: 14px 18px; border: 1px solid rgba(56, 189, 248, 0.25); background: linear-gradient(135deg, rgba(15, 23, 42, 0.96), rgba(13, 20, 36, 0.98));">
              <div style="display: flex; flex-wrap: wrap; justify-content: space-between; align-items: center; gap: 14px;">

                <div style="display: flex; flex-wrap: wrap; align-items: center; gap: 18px;">
                  <!-- 筛选项 1: 开始时间 (Element Plus daterange + 快捷切换) -->
                  <div style="display: flex; align-items: center; gap: 10px; flex-wrap: wrap;">
                    <span style="font-size: 12px; font-weight: 600; color: #94a3b8; white-space: nowrap;">📅 开始时间:</span>
                    <el-date-picker
                      v-model="taskDateRange"
                      type="daterange"
                      range-separator="-"
                      start-placeholder="开始日期"
                      end-placeholder="结束日期"
                      format="YYYY-MM-DD"
                      value-format="YYYY-MM-DD"
                      :shortcuts="dateShortcuts"
                      size="small"
                      style="width: 260px;"
                      @change="onTaskDateInputChange()"
                    />

                    <div style="display: inline-flex; gap: 4px; margin-left: 4px;">
                      <button type="button" class="btn btn-secondary"
                        @click="applyQuickTaskDateRange('all')"
                        :style="taskQuickDateRange === 'all' ? 'padding: 4px 10px; font-size: 11px; border-color: #00d2ff; color: #00d2ff; background: rgba(0, 210, 255, 0.12);' : 'padding: 4px 10px; font-size: 11px;'">
                        全部
                      </button>
                      <button type="button" class="btn btn-secondary"
                        @click="applyQuickTaskDateRange('today')"
                        :style="taskQuickDateRange === 'today' ? 'padding: 4px 10px; font-size: 11px; border-color: #00d2ff; color: #00d2ff; background: rgba(0, 210, 255, 0.12);' : 'padding: 4px 10px; font-size: 11px;'">
                        今天
                      </button>
                      <button type="button" class="btn btn-secondary"
                        @click="applyQuickTaskDateRange('7d')"
                        :style="taskQuickDateRange === '7d' ? 'padding: 4px 10px; font-size: 11px; border-color: #00d2ff; color: #00d2ff; background: rgba(0, 210, 255, 0.12);' : 'padding: 4px 10px; font-size: 11px;'">
                        近 7 天
                      </button>
                      <button type="button" class="btn btn-secondary"
                        @click="applyQuickTaskDateRange('month')"
                        :style="taskQuickDateRange === 'month' ? 'padding: 4px 10px; font-size: 11px; border-color: #00d2ff; color: #00d2ff; background: rgba(0, 210, 255, 0.12);' : 'padding: 4px 10px; font-size: 11px;'">
                        本月
                      </button>
                    </div>
                  </div>

                  <!-- 筛选项 2: 应用 -->
                  <div style="display: flex; align-items: center; gap: 8px;">
                    <span style="font-size: 12px; font-weight: 600; color: #94a3b8; white-space: nowrap;">🎯 应用:</span>
                    <select v-model="taskAppFilter" @change="onTaskPageSizeChange()"
                      style="background: #0b1120; color: #e2e8f0; border: 1px solid var(--border); border-radius: 6px; padding: 5px 12px; font-size: 12px; outline: none; cursor: pointer; min-width: 150px;">
                      <option value="all">全部矿山应用</option>
                      <option v-for="app in options.apps" :key="app.key" :value="app.key">{{ app.name }}</option>
                    </select>
                  </div>
                </div>

                <div style="display: flex; align-items: center; gap: 10px;">
                  <button type="button" class="btn btn-secondary" @click="resetTaskFilters()"
                    style="padding: 5px 12px; font-size: 12px; white-space: nowrap;" title="清空全部筛选条件">
                    ↺ 重置筛选
                  </button>
                </div>

              </div>
            </div>

            <!-- 2. 历史巡检任务列表卡片 (同级第 2 个 div) -->
            <div class="card">

              <div class="card-header">

                <div class="card-title">📁 历史巡检任务列表</div>

              </div>

              <div class="table-responsive">

                <table class="data-table">

                  <thead>
                    <tr>
                      <th>任务 ID / 名称</th>
                      <th>触发方式</th>
                      <th>开始时间</th>
                      <th>应用</th>
                      <th>模式</th>
                      <th>状态</th>
                      <th>步数 / 覆盖率</th>
                      <th>激活缺陷</th>
                      <th>发现缺陷</th>
                      <th>运行时长</th>
                      <th>操作</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr v-if="!filteredTasks || filteredTasks.length === 0">
                      <td colspan="11" style="text-align: center; padding: 28px; color: var(--text-muted);">
                        📁 暂无符合筛选条件的历史巡检任务记录
                      </td>
                    </tr>
                    <tr v-else v-for="t in paginatedTasks" :key="t.id"
                      :style="deletingTaskId === t.id ? 'opacity: 0.45; transition: opacity 0.3s; pointer-events: none;' : ''">
                      <td>
                        <div style="font-weight: 600;">{{ t.name }}</div>
                        <div style="font-size: 11px; color: var(--text-muted); font-family: monospace;">{{ t.id }}</div>
                      </td>
                      <td>
                        <span v-if="t.trigger_type === 'scheduled'" class="badge"
                          style="background: rgba(0, 210, 255, 0.15); color: #00d2ff; border: 1px solid rgba(0, 210, 255, 0.3); font-weight: 600; padding: 2px 8px; font-size: 11px; white-space: nowrap;">
                          ⏱️ 计划排程
                        </span>
                        <span v-else class="badge"
                          style="background: rgba(160, 174, 192, 0.15); color: #cbd5e0; border: 1px solid rgba(160, 174, 192, 0.25); font-weight: 600; padding: 2px 8px; font-size: 11px; white-space: nowrap;">
                          ⚡ 手动创建
                        </span>
                      </td>
                      <td style="font-size: 12px; color: #a0aec0; white-space: nowrap; font-family: monospace;">
                        {{ formatDateTime(t.start_time) }}
                      </td>
                      <td>{{ t.app_name }}</td>
                      <td>{{ formatTaskMode(t.mode) }}</td>
                      <td>
                        <span class="badge" :class="'badge-' + t.status">{{ formatTaskStatus(t.status) }}</span>
                      </td>

                      <td>{{ t.total_steps }} 步 ({{ t.coverage_rate }}%)</td>

                      <td>
                        <span v-if="(t.active_bugs_count || 0) > 0" class="badge"
                          style="background: rgba(255, 82, 82, 0.16); color: #ff6b6b; border: 1px solid rgba(255, 82, 82, 0.35); font-weight: 700; padding: 2px 8px; font-size: 12px;">
                          {{ t.active_bugs_count }}
                        </span>
                        <span v-else style="color: var(--text-muted);">0</span>
                      </td>

                      <td style="color: #ff5252; font-weight: 600;">{{ t.bugs_count }}</td>

                      <td>{{ formatDuration(t.duration) }}</td>

                      <td>

                        <button class="btn btn-secondary" style="padding: 4px 10px; font-size: 12px;"
                          @click="switchActiveTask(t); currentTab = 'monitor'">

                          监控

                        </button>

                        <a v-if="t.report_url" :href="formatReportUrl(t.report_url)" target="_blank"
                          class="btn btn-secondary" style="padding: 4px 10px; font-size: 12px; margin-left: 6px;">

                          报告

                        </a>

                        <button class="btn btn-secondary"
                          style="padding: 4px 10px; font-size: 12px; margin-left: 6px; border-color: #00d2ff; color: #00d2ff;"
                          @click="openEnvInfoModal(t)">

                          运行环境

                        </button>

                        <button v-if="t.status === 'running'" class="btn btn-secondary"
                          style="padding: 4px 10px; font-size: 12px; margin-left: 6px; border-color: #ff9100; color: #ff9100;"
                          @click="stopTask(t.id)" title="终止任务执行">
                          🛑 终止
                        </button>

                        <button class="btn btn-secondary"
                          style="padding: 4px 10px; font-size: 12px; margin-left: 6px; border-color: #ff5252; color: #ff5252; min-width: 76px; justify-content: center;"
                          :disabled="deletingTaskId === t.id"
                          title="彻底清理该任务记录及关联产物"
                          @click="deleteTaskRun(t)">
                          <span v-if="deletingTaskId === t.id" class="spinner-icon"></span>
                          <span v-if="deletingTaskId === t.id">清理中...</span>
                          <span v-else>🗑️ 删除</span>
                        </button>

                      </td>

                    </tr>

                  </tbody>

                </table>

              </div>

              <!-- 任务列表分页工具栏 -->
              <div class="pagination-container" v-if="filteredTasks && filteredTasks.length > 0">
                <div class="pagination-left">
                  <span>共 <strong style="color: #00d2ff;">{{ filteredTasks.length }}</strong> 个任务批次</span>
                  <span style="color: var(--border-color);">|</span>
                  <span>每页显示</span>
                  <select class="pagination-select" v-model.number="taskPageSize" @change="onTaskPageSizeChange">
                    <option v-for="size in taskPageSizes" :key="size" :value="size">{{ size }} 条/页</option>
                  </select>
                </div>

                <div class="pagination-right">
                  <button class="page-btn" :disabled="taskPage <= 1" @click="setTaskPage(taskPage - 1)" title="上一页">
                    &lt;
                  </button>

                  <template v-for="(p, idx) in getPageNumbers(taskPage, totalTaskPages)" :key="'tp-' + idx">
                    <span v-if="p === '...'" class="page-btn ellipsis">...</span>
                    <button v-else class="page-btn" :class="{ active: p === taskPage }" @click="setTaskPage(p)">
                      {{ p }}
                    </button>
                  </template>

                  <button class="page-btn" :disabled="taskPage >= totalTaskPages" @click="setTaskPage(taskPage + 1)"
                    title="下一页">
                    &gt;
                  </button>

                  <span style="margin: 0 4px; color: var(--text-muted);">第 {{ taskPage }} / {{ totalTaskPages }}
                    页</span>

                  <span style="margin-left: 6px;">跳至</span>
                  <input type="number" class="page-jump-input" min="1" :max="totalTaskPages"
                    v-model.number="taskPageJump" @keydown.enter="jumpToTaskPage">
                  <span>页</span>
                  <button class="page-btn" style="padding: 0 10px; margin-left: 4px;"
                    @click="jumpToTaskPage">确定</button>
                </div>
              </div>

            </div>

          </div>

          <!-- 子模块 2: 调度执行队列 (RPA Worker 看板) -->
          <div v-show="assetsSubTab === 'queue'">
            <div class="card">
              <div class="card-header" style="display: flex; justify-content: space-between; align-items: center;">
                <div class="card-title">⏱️ 调度执行队列与定时任务</div>
                <div style="display: flex; gap: 10px; align-items: center;">
                  <button class="btn btn-primary"
                    style="font-size: 12px; padding: 6px 14px; background: linear-gradient(135deg, #00d2ff, #0072ff); border: none; font-weight: 600; display: inline-flex; align-items: center; gap: 6px;"
                    @click="openCreateScheduleModal">
                    <span>➕ 新建调度计划</span>
                  </button>
                  <button class="btn btn-secondary" style="font-size: 12px; padding: 6px 12px;" @click="fetchTaskQueue">
                    🔄 刷新队列
                  </button>
                </div>
              </div>

              <div
                style="padding: 12px 20px; background: rgba(0, 210, 255, 0.05); border-bottom: 1px solid #1a253c; font-size: 13px; color: var(--text-muted); display: flex; align-items: center; gap: 8px;">
                <span>💡 <strong>执行器机制说明：</strong>
                  系统单机独占运行，待执行任务将按顺序依次拉起。前序任务结束或终止后，执行器会自动深度清洗进程环境、释放显存并无缝执行下一个项目。</span>
              </div>

              <div class="table-responsive">
                <table class="data-table">
                  <thead>
                    <tr>
                      <th style="width: 100px;">优先级</th>
                      <th style="width: 120px;">目标系统</th>
                      <th>计划名称与关联流程</th>
                      <th>巡检模式</th>
                      <th>有效期与执行时间窗口</th>
                      <th style="width: 100px;">状态</th>
                      <th>下次预约执行时间</th>
                      <th style="width: 80px;">累计执行</th>
                      <th style="white-space: nowrap;">操作</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr v-if="!taskQueue || taskQueue.length === 0">
                      <td colspan="9" style="text-align: center; padding: 28px; color: var(--text-muted);">
                        ⏱️ 当前暂无已配置的调度计划。点击上方【➕ 新建调度计划】即可添加定时自动化排程！
                      </td>
                    </tr>
                    <tr v-else v-for="q in taskQueue" :key="q.id">
                      <td>
                        <span class="badge"
                          :style="{ background: formatPriorityLabel(q.priority).bg, color: formatPriorityLabel(q.priority).color, fontWeight: '700', whiteSpace: 'nowrap', display: 'inline-flex', alignItems: 'center', justifyContent: 'center', padding: '3px 8px', minWidth: '70px' }">
                          {{ formatPriorityLabel(q.priority).text }}
                        </span>
                      </td>
                      <td>
                        <span style="font-weight: 600; color: #fff;">{{ q.app_name }}</span>
                      </td>
                      <td>
                        <div style="font-weight: 600; color: #fff;">{{ q.name || q.task_name }}</div>
                        <div style="font-size: 11px; color: var(--text-muted); font-family: monospace;">
                          流程: {{ q.preset_title || q.mode }} ({{ q.max_steps }}步 / {{ q.max_times }}分)
                        </div>
                      </td>
                      <td>
                        <span v-if="q.cron_mode === 'daily'" class="badge"
                          style="background: rgba(0, 230, 118, 0.15); color: #00e676; border: 1px solid rgba(0, 230, 118, 0.3); font-weight: 600; font-size: 11px; white-space: nowrap;">
                          🔄 每天 (每{{ q.cron_spec || 1 }}天)
                        </span>
                        <span v-else-if="q.cron_mode === 'weekly'" class="badge"
                          style="background: rgba(157, 78, 221, 0.15); color: #c77dff; border: 1px solid rgba(157, 78, 221, 0.3); font-weight: 600; font-size: 11px; white-space: nowrap;">
                          🔄 每周 (周{{ formatWeekdays(q.cron_spec) }})
                        </span>
                        <span v-else-if="q.cron_mode === 'monthly'" class="badge"
                          style="background: rgba(255, 179, 0, 0.15); color: #ffb300; border: 1px solid rgba(255, 179, 0, 0.3); font-weight: 600; font-size: 11px; white-space: nowrap;">
                          🔄 每月 ({{ q.cron_spec || 1 }}日)
                        </span>
                        <span v-else-if="q.cron_mode === 'minute'" class="badge"
                          style="background: rgba(0, 210, 255, 0.15); color: #00d2ff; border: 1px solid rgba(0, 210, 255, 0.3); font-weight: 600; font-size: 11px; white-space: nowrap;">
                          ⚡ 每 {{ q.cron_spec || 30 }} 分钟
                        </span>
                        <span v-else-if="q.cron_mode === 'hour'" class="badge"
                          style="background: rgba(0, 210, 255, 0.15); color: #00d2ff; border: 1px solid rgba(0, 210, 255, 0.3); font-weight: 600; font-size: 11px; white-space: nowrap;">
                          ⏱️ 每 {{ q.cron_spec || 1 }} 小时
                        </span>
                        <span v-else class="badge"
                          style="background: rgba(160, 174, 192, 0.1); color: #a0aec0; border: 1px solid rgba(160, 174, 192, 0.2); font-size: 11px; white-space: nowrap;">
                          单次执行
                        </span>
                      </td>
                      <td>
                        <div style="font-size: 11px; color: #cbd5e1; font-family: monospace;">{{ q.start_date || '-' }} 至 {{ q.end_date || '长期有效' }}</div>
                        <div style="font-size: 11px; color: var(--text-muted); font-family: monospace;">时刻: {{ q.start_time || '18:35:00' }} ~ {{ q.end_time || '23:59:59' }}</div>
                      </td>
                      <td>
                        <span v-if="q.status === 'running'" class="badge badge-running">🚀 正在执行</span>
                        <span v-else-if="q.status === 'pending'" class="badge" style="background: rgba(255, 179, 0, 0.15); color: #ffb300; border: 1px solid rgba(255, 179, 0, 0.3);">⏳ 排队等待</span>
                        <span v-else-if="q.is_active === 1 && q.status === 'active'" class="badge badge-success">🟢 启用中</span>
                        <span v-else-if="q.status === 'expired'" class="badge" style="background: rgba(160, 174, 192, 0.15); color: #a0aec0;">⌛ 已到期</span>
                        <span v-else-if="q.status === 'completed'" class="badge badge-completed">✅ 已完成</span>
                        <span v-else class="badge" style="background: rgba(100, 116, 139, 0.2); color: #94a3b8;">⚪ 已停用</span>
                      </td>
                      <td style="font-size: 12px; color: #ffb300; font-family: monospace; font-weight: 600;">
                        {{ q.next_run_time || q.scheduled_at || '--' }}
                      </td>
                      <td style="font-size: 12px; color: #cbd5e1; text-align: center;">
                        {{ q.run_count || 0 }} 次
                      </td>
                      <td style="text-align: left; white-space: nowrap;">
                        <div style="display: inline-flex; align-items: center; gap: 6px; justify-content: flex-start; flex-wrap: nowrap;">
                          <button v-if="q.status === 'running'" type="button" class="btn btn-secondary"
                            style="padding: 4px 8px; font-size: 11px; border-color: #ff5252; color: #ff5252; white-space: nowrap;"
                            @click="stopTask(q.task_id)" title="终止当前正在执行的任务">
                            🛑 终止
                          </button>
                          <button v-else type="button" class="btn btn-primary"
                            style="padding: 4px 10px; font-size: 11px; font-weight: 600; white-space: nowrap;"
                            @click="runScheduleNow(q)" title="立即下发执行一次该计划">
                            ⚡ 立即执行
                          </button>

                          <button v-if="q.status !== 'pending'" type="button" class="btn btn-secondary"
                            style="padding: 4px 8px; font-size: 11px; white-space: nowrap;"
                            :style="q.is_active ? 'color: #ffb300; border-color: rgba(255, 179, 0, 0.4);' : 'color: #00e676; border-color: rgba(0, 230, 118, 0.4);'"
                            @click="toggleScheduleActive(q)" :title="q.is_active ? '停用该调度计划' : '启用该调度计划'">
                            {{ q.is_active ? '⏸️ 停用' : '▶️ 启用' }}
                          </button>

                          <button v-if="q.status !== 'pending'" type="button" class="btn btn-secondary"
                            style="padding: 4px 8px; font-size: 11px; border-color: #64748b; color: #cbd5e1; white-space: nowrap;"
                            @click="openEditScheduleModal(q)" title="编辑调度计划">
                            ✏️ 编辑
                          </button>

                          <button type="button"
                            style="background: transparent; border: 1px solid rgba(255,82,82,0.25); border-radius: 4px; color: #ff5252; cursor: pointer; padding: 4px 8px; font-size: 11px; transition: all 0.2s; white-space: nowrap; display: inline-flex; align-items: center; gap: 4px;"
                            onmouseover="this.style.background='rgba(255,82,82,0.2)'; this.style.borderColor='#ff5252';"
                            onmouseout="this.style.background='transparent'; this.style.borderColor='rgba(255,82,82,0.25)';"
                            @click="deleteSchedule(q)" title="彻底删除此记录">
                            🗑️ 删除
                          </button>
                        </div>
                      </td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </div>
          </div>

          <!-- 子模块 3: 用例资产管理 -->
          <div v-show="assetsSubTab === 'cases'">

            <div class="card">

              <div class="card-header"
                style="flex-direction: column; align-items: stretch; gap: 14px; padding-bottom: 16px;">

                <div style="display: flex; justify-content: space-between; align-items: center; width: 100%;">

                  <div class="card-title" style="display: flex; align-items: center; gap: 10px;">

                    <span>🧪 测试用例资产管理 (双引擎协同)</span>

                  </div>

                  <div style="display: flex; align-items: center; gap: 10px;">

                    <button class="btn btn-secondary" @click="fetchCases" style="padding: 5px 12px; font-size: 12px;">

                      🔄 刷新用例

                    </button>

                    <button class="btn btn-primary" @click="currentTab = 'dashboard'"
                      style="padding: 5px 12px; font-size: 12px;">

                      🚀 前往控制台发起测试

                    </button>

                  </div>

                </div>

                <!-- 顶部两档分段器 (无括号、无数字) -->
                <div
                  style="display: flex; background: rgba(5, 7, 13, 0.8); padding: 4px; border-radius: 8px; border: 1px solid #1a253c; width: fit-content;">

                  <button type="button" @click="casesSubTab = 'manual'" :style="{
                    background: casesSubTab === 'manual' ? '#00d2ff' : 'transparent',
                    color: casesSubTab === 'manual' ? '#000' : '#8b9bb4',
                    border: 'none',
                    padding: '8px 22px',
                    borderRadius: '6px',
                    fontSize: '13px',
                    fontWeight: 700,
                    cursor: 'pointer'
                  }">
                    <span>✍️ 手工编写用例</span>
                  </button>

                  <button type="button" @click="casesSubTab = 'auto'" :style="{
                    background: casesSubTab === 'auto' ? '#00d2ff' : 'transparent',
                    color: casesSubTab === 'auto' ? '#000' : '#8b9bb4',
                    border: 'none',
                    padding: '8px 22px',
                    borderRadius: '6px',
                    fontSize: '13px',
                    fontWeight: 700,
                    cursor: 'pointer'
                  }">
                    <span>🤖 AI 自动生成用例</span>
                  </button>

                </div>

              </div>

              <!-- 1. 手工用例表格 -->
              <div class="table-responsive" v-show="casesSubTab === 'manual'">

                <table class="data-table">

                  <thead>

                    <tr>

                      <th>用例名称</th>

                      <th>相对路径</th>

                      <th>步骤数</th>

                      <th>大小</th>

                      <th>最后更新时间</th>

                      <th>操作</th>

                    </tr>

                  </thead>

                  <tbody>

                    <tr v-if="manualCases.length === 0">

                      <td colspan="6" style="text-align: center; padding: 28px; color: var(--text-muted);">

                        📁 test_cases/ 下暂无手工 YAML 用例

                      </td>

                    </tr>

                    <tr v-else v-for="c in manualCases" :key="c.path">

                      <td>

                        <div style="font-weight: 600; color: #fff;">{{ c.name }}</div>

                        <div style="font-size: 11px; color: var(--text-muted);">{{ c.description || c.filename }}</div>

                      </td>

                      <td style="font-family: monospace; font-size: 12px; color: #8b9bb4;">{{ c.path }}</td>

                      <td><b style="color: #00d2ff;">{{ c.steps_count }}</b> 步</td>

                      <td style="color: var(--text-muted); font-size: 12px;">{{ c.size_kb }} KB</td>

                      <td style="font-size: 12px; color: #a0aec0; font-family: monospace;">{{ c.modified_at }}</td>

                      <td>

                        <button class="btn btn-secondary" style="padding: 4px 10px; font-size: 12px;"
                          @click="openCasePreview(c)">

                          🔍 查看 YAML

                        </button>

                        <button class="btn btn-primary" style="padding: 4px 10px; font-size: 12px; margin-left: 6px;"
                          @click="runCaseInDashboard(c)">

                          🚀 载入运行

                        </button>

                      </td>

                    </tr>

                  </tbody>

                </table>

              </div>

              <!-- 2. AI 自动生成用例表格 -->
              <div class="table-responsive" v-show="casesSubTab === 'auto'">

                <table class="data-table">

                  <thead>

                    <tr>

                      <th>生成批次 (Run ID)</th>

                      <th>所属矿山</th>

                      <th>用例文件名</th>

                      <th>探索步骤数</th>

                      <th>文件大小</th>

                      <th>生成时间</th>

                      <th>操作</th>

                    </tr>

                  </thead>

                  <tbody>

                    <tr v-if="autoCases.length === 0">

                      <td colspan="7" style="text-align: center; padding: 28px; color: var(--text-muted);">

                        📁 reports/runs/ 下暂未发现自动沉淀的 YAML 用例

                      </td>

                    </tr>

                    <tr v-else v-for="c in autoCases" :key="c.path">

                      <td>

                        <div style="font-weight: 600; font-family: monospace; color: #00d2ff;">{{ c.run_id }}</div>

                      </td>

                      <td>

                        <span class="badge badge-low">{{ c.app_name }}</span>

                      </td>

                      <td>

                        <div style="font-size: 12px; color: #cbd5e1; font-family: monospace;">{{ c.filename }}</div>

                      </td>

                      <td><b style="color: #00e676;">{{ c.steps_count }}</b> 步</td>

                      <td style="color: var(--text-muted); font-size: 12px;">{{ c.size_kb }} KB</td>

                      <td style="font-size: 12px; color: #a0aec0; font-family: monospace;">{{ c.created_at }}</td>

                      <td>

                        <button class="btn btn-secondary" style="padding: 4px 10px; font-size: 12px;"
                          @click="openCasePreview(c)">

                          🔍 查看 YAML

                        </button>

                        <button class="btn btn-secondary"
                          style="padding: 4px 10px; font-size: 12px; margin-left: 6px; border-color: #00e676; color: #00e676;"
                          @click="promoteCase(c)" title="固化转存到 test_cases/ 作为常态用例">

                          📌 固化转存

                        </button>

                        <button class="btn btn-primary" style="padding: 4px 10px; font-size: 12px; margin-left: 6px;"
                          @click="runCaseInDashboard(c)">

                          🚀 载入运行

                        </button>

                      </td>

                    </tr>

                  </tbody>

                </table>

              </div>

            </div>

          </div>

        </div>



        <!-- ============================================================= -->

        <!-- 4. 缺陷治理中枢 (Bug List & 禅道一键推单) -->

        <!-- ============================================================= -->

</template>

<script>
import { inject } from 'vue'
export default {
  setup() {
    return inject('platformStore')
  }
}
</script>
