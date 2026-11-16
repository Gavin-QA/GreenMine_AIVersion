<template>
        <div v-show="currentTab === 'monitor'">

          <div style="margin-bottom: 16px; display: flex; align-items: center; justify-content: space-between;">

            <div style="display: flex; align-items: center; gap: 12px;">

              <span style="font-size: 13px; color: var(--text-muted);">当前查看维度:</span>

              <select class="form-control" style="width: 380px; font-weight: 600;" v-model="activeTaskId"
                @change="onMonitorTargetChange">

                <option value="__live__" style="color: #00e676; font-weight: 700;">⚡ [实时模式] 本机物理环境实时心电图 (无需启动测试)
                </option>

                <option disabled style="color: #64748b;">──────── 历史任务性能复盘 ────────</option>

                <option v-for="t in tasks" :key="t.id" :value="t.id">

                  [{{ t.status }}] {{ t.name }} ({{ t.id }})

                </option>

              </select>

            </div>



            <div v-if="activeTaskId === '__live__'" style="display: flex; align-items: center; gap: 8px;">
              <button class="btn btn-secondary" style="padding: 4px 10px; font-size: 12px; display: inline-flex; align-items: center; gap: 4px;" @click="manualRefreshLive" title="立即拉取当前物理环境切片">
                <span>🔄</span> 立即刷新
              </button>
              <button class="btn" :class="liveAutoRefresh ? 'btn-primary' : 'btn-secondary'" style="padding: 4px 10px; font-size: 12px; display: inline-flex; align-items: center; gap: 4px;" @click="toggleLiveAutoRefresh" title="切换是否开启 4 秒自动探针轮询">
                <span class="pulse-dot" v-if="liveAutoRefresh" style="display: inline-block; width: 6px; height: 6px; border-radius: 50%; background: #00e676;"></span>
                <span>{{ liveAutoRefresh ? '⏱️ 自动轮询: 开 (4s)' : '🤫 静默模式 (无轮询)' }}</span>
              </button>
            </div>

            <div v-else-if="activeTask">

              <button v-if="activeTask.status === 'running'" class="btn btn-danger" @click="stopTask(activeTask.id)">

                🛑 紧急停止任务

              </button>

              <button v-else-if="activeTask.status === 'pending' || activeTask.status === 'stopped'"
                class="btn btn-primary" @click="startTask(activeTask.id)">

                ▶️ 继续启动

              </button>

              <a v-if="activeTask.report_url" :href="formatReportUrl(activeTask.report_url)" target="_blank"
                class="btn btn-secondary" style="margin-left: 8px;">

                📑 查看专属报告

              </a>

            </div>

          </div>



          <!-- 实时心电图专属控制栏：分项目独立切换 + 状态微标 + 24小时回溯跨度 -->
          <div v-if="activeTaskId === '__live__'"
            style="margin-bottom: 16px; background: rgba(13, 20, 36, 0.95); padding: 10px 16px; border-radius: 8px; border: 1px solid #1e293b; display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 12px;">
            <div style="display: flex; align-items: center; gap: 10px; flex-wrap: wrap;">
              <span
                style="font-size: 13px; font-weight: 700; color: #94a3b8; display: flex; align-items: center; gap: 6px;">
                🎯 监控目标项目:
              </span>
              <div style="display: flex; gap: 8px;">
                <button v-for="app in liveAppsStatus" :key="app.app_name" @click="changeLiveApp(app.app_name)"
                  type="button" :style="{
                    background: liveSelectedApp === app.app_name ? 'rgba(0, 210, 255, 0.15)' : 'rgba(30, 41, 59, 0.5)',
                    border: liveSelectedApp === app.app_name ? '1px solid #00d2ff' : '1px solid #334155',
                    color: liveSelectedApp === app.app_name ? '#00d2ff' : '#cbd5e1',
                    padding: '6px 14px',
                    fontSize: '13px',
                    fontWeight: 600,
                    borderRadius: '6px',
                    cursor: 'pointer',
                    display: 'flex',
                    alignItems: 'center',
                    gap: '8px'
                  }">
                  <span :style="{
                      display: 'inline-block',
                      width: '8px',
                      height: '8px',
                      borderRadius: '50%',
                      background: app.online ? '#00e676' : '#64748b',
                      boxShadow: app.online ? '0 0 8px #00e676' : 'none'
                    }"></span>
                  <span>{{ app.title }}</span>
                  <span v-if="app.online && app.ue_commit_mb"
                    style="font-size: 11px; padding: 2px 6px; border-radius: 4px; background: rgba(255, 145, 0, 0.2); color: #ff9100; font-weight: 700;">
                    {{ (app.ue_commit_mb / 1024).toFixed(1) }}G Commit
                  </span>
                  <span v-else-if="app.online" style="font-size: 11px; color: #00e676; font-weight: 600;">
                    在线
                  </span>
                  <span v-else style="font-size: 11px; color: #64748b;">
                    待命
                  </span>
                </button>
              </div>
            </div>

            <!-- 时间跨度快捷切换器 -->
            <div style="display: flex; align-items: center; gap: 8px;">
              <span style="font-size: 12px; color: #94a3b8;">历史回溯:</span>
              <div
                style="display: flex; background: #0b1120; border: 1px solid #1e293b; border-radius: 6px; padding: 2px;">
                <button
                  v-for="span in [{'key':'15m','name':'15分钟'},{'key':'1h','name':'1小时'},{'key':'6h','name':'6小时'},{'key':'24h','name':'24小时'}]"
                  :key="span.key" @click="changeLiveTimeSpan(span.key)" type="button" :style="{
                    background: liveTimeSpan === span.key ? '#00d2ff' : 'transparent',
                    color: liveTimeSpan === span.key ? '#000' : '#94a3b8',
                    border: 'none',
                    padding: '4px 10px',
                    borderRadius: '4px',
                    fontSize: '12px',
                    fontWeight: 600,
                    cursor: 'pointer'
                  }">
                  {{ span.name }}
                </button>
              </div>
            </div>
          </div>

          <!-- 实时多核物理指标卡片 (环境与探针实时水位) -->
          <div class="grid-4" style="margin-bottom: 16px;">
            <div class="kpi-card"
              :title="liveSnapshot.cdp_online ? 'Chromium CDP 协议探针在线，实时抓取 2D 页面 DOM 树与事件监听器' : 'CDP 调试端口 (9223) 未激活\n启动大屏附带参数 --remote-debugging-port=9223 即可秒级点亮此卡片'"
              style="cursor: help;">
              <div class="kpi-title">CHROMIUM DOM 节点</div>
              <div class="kpi-val" style="color: #00d2ff;">{{ liveSnapshot.dom_count.toLocaleString() }}</div>
              <div class="kpi-sub">
                事件监听器: {{ liveSnapshot.listeners_count.toLocaleString() }}
                <span v-if="!liveSnapshot.cdp_online"
                  style="font-size: 10px; color: #ffb300; margin-left: 4px;">(端口离线)</span>
              </div>
            </div>

            <div class="kpi-card purple"
              :title="liveSnapshot.cdp_online ? 'V8 引擎堆内存实时水位，反映大屏前端是否存在内存泄漏' : 'CDP 调试端口未连接 (显示为安全退避 0 值)'"
              style="cursor: help;">
              <div class="kpi-title">V8 JS 堆内存</div>
              <div class="kpi-val" style="color: #9d4edd;">{{ liveSnapshot.js_heap_mb }} <span
                  style="font-size: 14px;">MB</span></div>
              <div class="kpi-sub">总容量: {{ liveSnapshot.js_heap_total_mb }} MB</div>
            </div>

            <div class="kpi-card green"
              :title="`Windows 任务管理器全景视点:\n物理内存 (RAM/WorkingSet): ${liveSnapshot.ue_memory_mb || 0} MB\n专用提交量 (Private Commit): ${liveSnapshot.ue_commit_mb ? (liveSnapshot.ue_commit_mb / 1024).toFixed(2) + ' GB (' + liveSnapshot.ue_commit_mb + ' MB)' : '0 MB'}\n整机虚拟提交负荷: ${liveSnapshot.host_commit_load_percent || 0}% (防 OOM 核心指标)\n整机物理内存负荷: ${liveSnapshot.host_ram_load_percent || 0}%\nCPU 占用: ${liveSnapshot.ue_cpu_percent || 0}% (${liveSnapshot.cpu_cores || 12}核对齐)`"
              style="cursor: help;">
              <div class="kpi-title">伴生 UE5 (Commit / RAM)</div>
              <div class="kpi-val" style="color: #00e676;">
                <span v-if="liveSnapshot.ue_commit_mb" style="color: #ff9100;">{{ (liveSnapshot.ue_commit_mb /
                  1024).toFixed(1) }} <span style="font-size: 13px;">GB Commit</span></span>
                <span v-else>{{ liveSnapshot.ue_memory_mb || 0 }} <span style="font-size: 14px;">MB</span></span>
                <span style="font-size: 12px; color: #a0aec0; margin-left: 6px;">/ {{ liveSnapshot.ue_memory_mb || 0 }}M
                  RAM</span>
              </div>
              <div class="kpi-sub">
                CPU: {{ liveSnapshot.ue_cpu_percent || 0 }}% | 宿主机Commit: {{ liveSnapshot.host_commit_load_percent || 0
                }}%
              </div>
            </div>

            <div class="kpi-card warning"
              :title="`NVIDIA 官方驱动实时 3D 核心硬件负载: ${liveSnapshot.gpu_usage_percent || 0}%\n采样源: nvidia-smi 驱动级瞬时切片 (包含 UE5 渲染引擎、DWM 桌面窗口管理器与 Chromium 画面合成器总计；任务管理器单进程估算约 24% 左右)`"
              style="cursor: help;">
              <div class="kpi-title">GPU 3D 渲染 / 显存</div>
              <div class="kpi-val" style="color: #ffb300;">{{ liveSnapshot.gpu_usage_percent || 0 }}%</div>
              <div class="kpi-sub">显存已用: {{ liveSnapshot.gpu_memory_mb || 0 }} MB <span
                  style="font-size: 11px; opacity: 0.8;">ℹ️</span></div>
            </div>
          </div>

          <!-- 双 ECharts 性能折线图 -->

          <div class="grid-2">

            <div class="card">

              <div id="domChart" class="chart-box"></div>

            </div>

            <div class="card">

              <div id="ueChart" class="chart-box"></div>

            </div>

          </div>



          <!-- 实时控制台终端日志流 -->

          <div class="card">

            <div class="card-header">

              <div class="card-title">🖥️ 实时控制台日志推流 (WebSocket 直连)</div>

              <span style="font-size: 12px; color: var(--text-muted);">实时缓存行数: {{ terminalLogs.length }}</span>

            </div>

            <div id="terminalWindow" class="terminal-window">

              <div v-if="terminalLogs.length === 0"
                style="color: var(--text-muted); text-align: center; padding: 40px;">

                暂无日志流或任务尚未启动，启动任务后将实时输出执行过程...

              </div>

              <div v-for="(log, idx) in terminalLogs" :key="idx" class="log-line" :class="{

                  error: log.includes('ERROR') || log.includes('❌') || log.includes('Traceback'),

                  warn: log.includes('WARNING') || log.includes('⚠️'),

                  info: log.includes('INFO'),

                  success: log.includes('圆满完成') || log.includes('✅')

                }">{{ log }}</div>

            </div>

          </div>

        </div>



        <!-- ============================================================= -->

        <!-- 3. 任务与产物库 (包含历史巡检任务与用例资产管理) -->

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
