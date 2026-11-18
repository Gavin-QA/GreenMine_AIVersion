<template>
  <div v-show="currentTab === 'settings'" class="system-config-page">
    <!-- ==================== 子页面 1：配置总览 ==================== -->
    <template v-if="settingsSubTab === 'overview'">
    <!-- 顶部只读声明与全局刷新 -->
    <div class="cfg-banner">
      <div>
        <div class="cfg-banner-title">📋 系统生效配置总览</div>
        <div class="cfg-banner-sub">
          当前配置以只读模式展示，来源涵盖 <code>.env</code>、<code>config.yaml</code>、<code>config/settings.py</code> 与后端内置字典（密钥与密码已自动脱敏）。
        </div>
      </div>
      <div style="display: flex; align-items: center; gap: 10px;">
        <span v-if="cfg?.config_sources" class="source-pill" :class="cfg.config_sources.env_file_exists ? 'ok' : 'warn'">
          .env: {{ cfg.config_sources.env_file_exists ? '已加载' : '未检测到' }}
        </span>
        <span v-if="cfg?.config_sources" class="source-pill" :class="cfg.config_sources.config_yaml_exists ? 'ok' : 'warn'">
          config.yaml: {{ cfg.config_sources.config_yaml_exists ? '已加载' : '未检测到' }}
        </span>
        <button class="btn btn-secondary" @click="fetchSystemConfigOverview" :disabled="isLoadingConfigOverview">
          {{ isLoadingConfigOverview ? '⏳ 刷新中...' : '🔄 刷新配置' }}
        </button>
      </div>
    </div>
    </template>

    <!-- ==================== 子页面 2：磁盘清理 ==================== -->
    <section v-if="settingsSubTab === 'cleanup'" class="cfg-card">
      <div class="cfg-card-header">
        <div>
          <h3 class="cfg-card-title">🧹 磁盘清理与存储大盘</h3>
          <p class="cfg-card-desc">
            仅针对 <code>reports/runs/*/screenshots/</code> 下的过程临时截图进行清理或 WebP 转码；永久保全 <code>artifacts/</code>、<code>bugs/</code> 现场与 <code>checkpoint/</code> 记忆。
          </p>
        </div>
        <div style="display: flex; align-items: center; gap: 10px;">
          <span class="badge-chip">运行批次数: {{ storageSummary.runs_count ?? 0 }}</span>
          <button class="btn btn-secondary" @click="fetchStorageSummary">🔄 刷新统计</button>
        </div>
      </div>

      <div class="storage-grid">
        <div class="storage-stat highlight">
          <div class="stat-label">单次运行产物区 (reports/runs)</div>
          <div class="stat-value">{{ storageSummary.runs_total_human || '0 B' }}</div>
          <div class="stat-sub">过程截图占比 {{ storageSummary.screenshots_ratio ?? 0 }}%</div>
        </div>
        <div class="storage-stat">
          <div class="stat-label">临时过程截图 (可安全瘦身)</div>
          <div class="stat-value" style="color: #ffb300;">{{ storageSummary.screenshots_human || '0 B' }}</div>
          <div class="stat-sub">共 {{ storageSummary.screenshots_count ?? 0 }} 张</div>
        </div>
        <div class="storage-stat">
          <div class="stat-label">崩溃案发现场 (bugs/ 永久留存)</div>
          <div class="stat-value" style="color: #ff5252;">{{ storageSummary.bugs_human || '0 B' }}</div>
          <div class="stat-sub">检查点记忆: {{ storageSummary.checkpoint_human || '0 B' }}</div>
        </div>
        <div class="storage-stat">
          <div class="stat-label">全局持久资产库 (artifacts/)</div>
          <div class="stat-value" style="color: #00d2ff;">{{ storageSummary.artifacts_human || '0 B' }}</div>
          <div class="stat-sub">Bug库 {{ storageSummary.global_bugs_human || '0 B' }} · 拓扑 {{ storageSummary.topology_human || '0 B' }}</div>
        </div>
      </div>

      <div class="cleanup-toolbar">
        <div class="cleanup-controls">
          <label class="ctrl-item">
            <span>保留最近天数：</span>
            <select v-model.number="cleanupOpts.retain_days" class="cfg-select">
              <option :value="0">0 天（清理全部历史过程图）</option>
              <option :value="3">3 天</option>
              <option :value="7">7 天（推荐）</option>
              <option :value="14">14 天</option>
              <option :value="30">30 天</option>
            </select>
          </label>

          <label class="ctrl-checkbox">
            <input type="checkbox" v-model="cleanupOpts.protect_active_bugs" />
            <span>保护含「激活」Bug 的报告</span>
          </label>

          <label class="ctrl-checkbox">
            <input type="checkbox" v-model="cleanupOpts.compress_webp" />
            <span>原地转码为 WebP（保留画面但大幅压缩体积）</span>
          </label>
        </div>

        <div class="cleanup-actions">
          <button
            class="btn btn-secondary"
            :disabled="isCleaningStorage"
            @click="runCleanup(true)"
          >
            {{ isCleaningStorage ? '⏳ 处理中...' : '🔍 预演估算 (Dry Run)' }}
          </button>
          <button
            class="btn btn-primary"
            :disabled="isCleaningStorage"
            @click="runCleanup(false)"
            style="background: linear-gradient(135deg, #10b981, #059669); border: none;"
          >
            {{ isCleaningStorage ? '⏳ 瘦身中...' : '🧹 立即执行瘦身' }}
          </button>
        </div>
      </div>

      <div v-if="lastCleanupResult" class="cleanup-result">
        <div>
          {{ lastCleanupResult.dry_run ? '🔍 [预演估算]' : '✅ [已执行瘦身]' }}
          ({{ lastCleanupResult.timestamp }})：
          {{ lastCleanupResult.dry_run ? '预计可释放' : '已释放' }}
          <b>{{ lastCleanupResult.freed_human || '0 B' }}</b>，
          涉及 <b>{{ lastCleanupResult.cleaned_files || 0 }}</b> 个文件
          <template v-if="lastCleanupResult.protected_count > 0">
            ，自动跳过 <b>{{ lastCleanupResult.protected_count }}</b> 个含激活 Bug 的报告
          </template>。
        </div>

        <div v-if="lastCleanupResult.protected_runs?.length" class="cleanup-protected-list">
          <div style="font-weight: 600; color: #fbbf24; margin-bottom: 4px;">🛡️ 已保护跳过的目录：</div>
          <div v-for="pr in lastCleanupResult.protected_runs" :key="pr.run_id" class="protected-item">
            ⏭️ <code>{{ pr.run_id }}</code>（关联激活 Bug: {{ (pr.bug_ids || []).join(', ') }}）
          </div>
        </div>

        <div v-if="lastCleanupResult.affected_runs?.length" class="cleanup-files-panel">
          <div style="font-weight: 600; margin-bottom: 6px; color: #e2e8f0;">
            📋 {{ lastCleanupResult.dry_run ? '待清理' : '已清理' }}文件清单（共 {{ lastCleanupResult.affected_runs.length }} 个运行目录，点击目录可展开文件名）：
          </div>
          <div v-for="ar in lastCleanupResult.affected_runs" :key="ar.run_id" class="affected-run-box">
            <div class="affected-run-head" @click="toggleRunExpand(ar.run_id)">
              <span>
                {{ expandedRuns[ar.run_id] ? '▼' : '▶' }}
                📁 <code>{{ ar.dir }}</code>
              </span>
              <span style="color: #94a3b8; font-size: 11px;">
                {{ ar.file_count }} 个文件 · {{ ar.freed_human }}
              </span>
            </div>
            <div v-if="expandedRuns[ar.run_id]" class="affected-files-list">
              <div v-for="fname in ar.files" :key="fname" class="affected-file-item">
                {{ fname }}
              </div>
            </div>
          </div>
        </div>
      </div>
    </section>

    <template v-if="settingsSubTab === 'overview'">
    <!-- 二、多应用项目配置 (config.yaml / 内置字典) -->
    <section class="cfg-card">
      <div class="cfg-card-header">
        <div>
          <h3 class="cfg-card-title">🖥️ 多应用与环境基线配置 (config.yaml + 内置字典)</h3>
          <p class="cfg-card-desc">
            当前默认激活应用：<code>{{ cfg?.active_app || '-' }}</code>
          </p>
        </div>
        <span class="badge-chip">共 {{ cfg?.apps?.length || 0 }} 个应用</span>
      </div>

      <div class="apps-grid">
        <div v-for="app in (cfg?.apps || [])" :key="app.key" class="app-cfg-box" :class="{ active: app.is_active }">
          <div class="app-cfg-head">
            <div>
              <span class="app-name">{{ app.name }}</span>
              <code class="app-key">{{ app.key }}</code>
            </div>
            <div style="display: flex; gap: 6px;">
              <span v-if="app.is_active" class="tag tag-active">当前激活</span>
              <span class="tag" :class="app.in_yaml ? 'tag-yaml' : 'tag-builtin'">
                {{ app.in_yaml ? 'config.yaml' : '仅内置字典' }}
              </span>
            </div>
          </div>
          <div v-if="app.desc" class="app-desc">{{ app.desc }}</div>

          <div class="kv-list">
            <div class="kv-row">
              <span class="kv-k">启动路径 (exe_path)</span>
              <span class="kv-v mono">{{ app.exe_path || '未配置' }}</span>
            </div>
            <div class="kv-row">
              <span class="kv-k">CDP 调试端口 / UE 进程</span>
              <span class="kv-v mono">{{ app.debug_port }} / {{ app.ue_process_name }}</span>
            </div>
            <div class="kv-row">
              <span class="kv-k">视口分辨率 / DPR</span>
              <span class="kv-v mono">{{ app.viewport?.width }} × {{ app.viewport?.height }} (DPR {{ app.viewport?.device_pixel_ratio }})</span>
            </div>
            <div class="kv-row">
              <span class="kv-k">就绪目标 (URL / Title)</span>
              <span class="kv-v mono">{{ app.expected_page_url }} · {{ app.expected_page_title }}</span>
            </div>
            <div class="kv-row">
              <span class="kv-k">启动等待 (延迟 / 超时)</span>
              <span class="kv-v mono">{{ app.start_delay }}s / {{ app.startup_timeout }}s</span>
            </div>
            <div class="kv-row">
              <span class="kv-k">探索规则文件</span>
              <span class="kv-v mono">{{ app.rules_file }}</span>
            </div>
            <div class="kv-row">
              <span class="kv-k">禅道三元组 (产品/项目/迭代)</span>
              <span class="kv-v mono">
                {{ app.zentao_product_id ?? '-' }} / {{ app.zentao_project_id ?? '-' }} / {{ app.zentao_execution_id ?? '-' }}
              </span>
            </div>
            <div class="kv-row" v-if="app.env_check && Object.keys(app.env_check).length > 0">
              <span class="kv-k">环境基线校验 (env_check)</span>
              <span class="kv-v mono">{{ JSON.stringify(app.env_check) }}</span>
            </div>
          </div>
        </div>
      </div>
    </section>

    <!-- 三、大模型引擎 & 禅道与运行时配置 -->
    <div class="two-col-grid">
      <section class="cfg-card">
        <div class="cfg-card-header">
          <div>
            <h3 class="cfg-card-title">🧠 大模型与探索引擎参数 (.env / config.yaml)</h3>
            <p class="cfg-card-desc">视觉定位、缺陷查重与探索规划核心参数</p>
          </div>
        </div>
        <div class="kv-list" v-if="cfg?.llm">
          <div class="kv-row"><span class="kv-k">Provider</span><span class="kv-v mono">{{ cfg.llm.provider }}</span></div>
          <div class="kv-row"><span class="kv-k">Base URL</span><span class="kv-v mono">{{ cfg.llm.base_url }}</span></div>
          <div class="kv-row"><span class="kv-k">主视觉模型 (model)</span><span class="kv-v mono">{{ cfg.llm.model }}</span></div>
          <div class="kv-row"><span class="kv-k">缺陷分析模型</span><span class="kv-v mono">{{ cfg.llm.bug_analysis_model }}</span></div>
          <div class="kv-row">
            <span class="kv-k">API Key 状态</span>
            <span class="kv-v mono" :style="{ color: cfg.llm.api_key_configured ? '#00e676' : '#ff5252' }">
              {{ cfg.llm.api_key_configured ? `已配置 (${cfg.llm.api_key_masked})` : '未配置' }}
            </span>
          </div>
          <div class="kv-row"><span class="kv-k">Temperature / Max Tokens</span><span class="kv-v mono">{{ cfg.llm.temperature }} / {{ cfg.llm.max_tokens }}</span></div>
          <div class="kv-row"><span class="kv-k">请求超时 / 重试次数</span><span class="kv-v mono">{{ cfg.llm.timeout }}s / {{ cfg.llm.max_retries }} 次</span></div>
          <div class="kv-row"><span class="kv-k">单步超时 / 连续失败上限</span><span class="kv-v mono">{{ cfg.llm.step_timeout }}s / {{ cfg.llm.max_planner_failures }} 次</span></div>
          <div class="kv-row"><span class="kv-k">OOM 自动熔断</span><span class="kv-v mono">{{ cfg.llm.oom_kill_enabled ? '开启' : '关闭' }}</span></div>
        </div>
      </section>

      <section class="cfg-card">
        <div class="cfg-card-header">
          <div>
            <h3 class="cfg-card-title">🐞 禅道集成与运行时策略 (.env / settings.py)</h3>
            <p class="cfg-card-desc">缺陷推送目标地址、默认归属及日志策略</p>
          </div>
        </div>
        <div class="kv-list" v-if="cfg?.zentao">
          <div class="kv-row"><span class="kv-k">禅道服务地址</span><span class="kv-v mono">{{ cfg.zentao.url || '未配置' }}</span></div>
          <div class="kv-row"><span class="kv-k">禅道账号</span><span class="kv-v mono">{{ cfg.zentao.account || '未配置' }}</span></div>
          <div class="kv-row">
            <span class="kv-k">禅道密码状态</span>
            <span class="kv-v mono" :style="{ color: cfg.zentao.password_configured ? '#00e676' : '#ffb300' }">
              {{ cfg.zentao.password_configured ? '已配置 (已脱敏)' : '未配置' }}
            </span>
          </div>
          <div class="kv-row">
            <span class="kv-k">默认产品 / 项目 / 迭代</span>
            <span class="kv-v mono">{{ cfg.zentao.default_product_id }} / {{ cfg.zentao.default_project_id }} / {{ cfg.zentao.default_execution_id }}</span>
          </div>
        </div>
        <div class="kv-list" style="margin-top: 12px; padding-top: 12px; border-top: 1px dashed var(--border-color);" v-if="cfg?.runtime">
          <div class="kv-row"><span class="kv-k">无头模式 (Headless)</span><span class="kv-v mono">{{ cfg.runtime.headless ? '是' : '否' }}</span></div>
          <div class="kv-row">
            <span class="kv-k">测试登录账号</span>
            <span class="kv-v mono">{{ cfg.runtime.test_username_configured ? `${cfg.runtime.test_username} (密码已配置: ${cfg.runtime.test_password_configured ? '是' : '否'})` : '未配置' }}</span>
          </div>
          <div class="kv-row"><span class="kv-k">日志级别 / 失败截图</span><span class="kv-v mono">{{ cfg.runtime.log_level }} / {{ cfg.runtime.screenshot_on_failure ? '开启' : '关闭' }}</span></div>
          <div class="kv-row"><span class="kv-k">日志输出路径</span><span class="kv-v mono">{{ cfg.runtime.log_file_path }}</span></div>
        </div>
      </section>
    </div>

    <!-- 四、后端内置模式与 Prompt 模板字典 -->
    <section class="cfg-card">
      <div class="cfg-card-header">
        <div>
          <h3 class="cfg-card-title">📚 后端内置测试模式与 Prompt 模板字典 (server/routers/system.py)</h3>
          <p class="cfg-card-desc">以下选项当前硬编码于后端服务路由，供任务控制台下拉与快速填充使用</p>
        </div>
      </div>

      <div class="modes-row" v-if="cfg?.modes">
        <div v-for="m in cfg.modes" :key="m.key" class="mode-chip">
          <div class="mode-chip-title">{{ m.name }} <code>{{ m.key }}</code></div>
          <div class="mode-chip-desc">{{ m.desc }}</div>
        </div>
      </div>

      <div class="templates-list" v-if="cfg?.prompt_templates">
        <div v-for="(tpl, idx) in cfg.prompt_templates" :key="idx" class="tpl-item">
          <div class="tpl-title">✨ {{ tpl.title }}</div>
          <pre class="tpl-body">{{ tpl.prompt }}</pre>
        </div>
      </div>
    </section>
    </template>
  </div>
</template>

<script>
import { inject, reactive, computed } from 'vue'

export default {
  name: 'SystemConfigView',
  setup() {
    const store = inject('platformStore')
    const cfg = computed(() => store.systemConfigOverview.value)

    const cleanupOpts = reactive({
      retain_days: 7,
      protect_active_bugs: true,
      compress_webp: false,
    })

    const expandedRuns = reactive({})

    function toggleRunExpand(runId) {
      expandedRuns[runId] = !expandedRuns[runId]
    }

    function refreshAll() {
      store.fetchSystemConfigOverview()
      store.fetchStorageSummary()
    }

    function runCleanup(dryRun) {
      Object.keys(expandedRuns).forEach((k) => delete expandedRuns[k])
      store.triggerStorageCleanup({
        ...cleanupOpts,
        dry_run: dryRun,
      })
    }

    return {
      ...store,
      cfg,
      cleanupOpts,
      expandedRuns,
      toggleRunExpand,
      refreshAll,
      runCleanup,
    }
  },
}
</script>

<style scoped>
.system-config-page {
  display: flex;
  flex-direction: column;
  gap: 18px;
  padding-bottom: 32px;
}

.cfg-banner {
  background: linear-gradient(135deg, rgba(0, 210, 255, 0.08), rgba(58, 123, 213, 0.08));
  border: 1px solid var(--border-color);
  border-radius: 10px;
  padding: 16px 20px;
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 12px;
}

.cfg-banner-title {
  font-size: 16px;
  font-weight: 700;
  color: var(--text-main);
}

.cfg-banner-sub {
  font-size: 12px;
  color: var(--text-muted);
  margin-top: 4px;
}

.source-pill {
  font-size: 11px;
  padding: 4px 10px;
  border-radius: 999px;
  font-weight: 600;
}

.source-pill.ok {
  background: rgba(0, 230, 118, 0.12);
  color: #00e676;
  border: 1px solid rgba(0, 230, 118, 0.3);
}

.source-pill.warn {
  background: rgba(255, 179, 0, 0.12);
  color: #ffb300;
  border: 1px solid rgba(255, 179, 0, 0.3);
}

.cfg-card {
  background: var(--bg-card);
  border: 1px solid var(--border-color);
  border-radius: 10px;
  padding: 18px 20px;
}

.cfg-card-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 12px;
  margin-bottom: 14px;
}

.cfg-card-title {
  font-size: 15px;
  font-weight: 700;
  color: var(--text-main);
}

.cfg-card-desc {
  font-size: 12px;
  color: var(--text-muted);
  margin-top: 3px;
}

.badge-chip {
  font-size: 12px;
  padding: 4px 10px;
  border-radius: 6px;
  background: rgba(0, 210, 255, 0.1);
  color: var(--accent-cyan);
  border: 1px solid rgba(0, 210, 255, 0.25);
  white-space: nowrap;
}

.storage-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(210px, 1fr));
  gap: 12px;
  margin-bottom: 14px;
}

.storage-stat {
  background: rgba(11, 15, 25, 0.65);
  border: 1px solid var(--border-color);
  border-radius: 8px;
  padding: 12px 14px;
}

.storage-stat.highlight {
  border-color: rgba(0, 210, 255, 0.45);
}

.stat-label {
  font-size: 12px;
  color: var(--text-muted);
}

.stat-value {
  font-size: 20px;
  font-weight: 700;
  color: var(--text-main);
  margin: 4px 0;
}

.stat-sub {
  font-size: 11px;
  color: var(--text-muted);
}

.cleanup-toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 12px;
  padding: 12px 14px;
  background: rgba(11, 15, 25, 0.55);
  border: 1px solid var(--border-color);
  border-radius: 8px;
}

.cleanup-controls {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 16px;
  font-size: 12px;
  color: var(--text-main);
}

.ctrl-item {
  display: flex;
  align-items: center;
  gap: 6px;
}

.cfg-select {
  background: #0d1424;
  color: var(--text-main);
  border: 1px solid var(--border-color);
  border-radius: 6px;
  padding: 5px 8px;
  font-size: 12px;
}

.ctrl-checkbox {
  display: flex;
  align-items: center;
  gap: 6px;
  cursor: pointer;
}

.cleanup-actions {
  display: flex;
  align-items: center;
  gap: 10px;
}

.cleanup-result {
  margin-top: 10px;
  padding: 12px 14px;
  border-radius: 6px;
  background: rgba(16, 185, 129, 0.08);
  border: 1px solid rgba(16, 185, 129, 0.3);
  color: #a7f3d0;
  font-size: 12px;
}

.cleanup-protected-list {
  margin-top: 8px;
  padding-top: 8px;
  border-top: 1px dashed rgba(255, 255, 255, 0.12);
}

.protected-item {
  font-size: 11px;
  color: #fde68a;
  margin-top: 2px;
}

.cleanup-files-panel {
  margin-top: 10px;
  padding-top: 10px;
  border-top: 1px dashed rgba(255, 255, 255, 0.12);
}

.affected-run-box {
  background: rgba(11, 15, 25, 0.65);
  border: 1px solid var(--border-color);
  border-radius: 6px;
  margin-bottom: 6px;
  overflow: hidden;
}

.affected-run-head {
  padding: 7px 10px;
  display: flex;
  justify-content: space-between;
  align-items: center;
  cursor: pointer;
  color: var(--text-main);
  user-select: none;
}

.affected-run-head:hover {
  background: rgba(255, 255, 255, 0.04);
}

.affected-files-list {
  max-height: 220px;
  overflow-y: auto;
  padding: 6px 12px 8px 24px;
  border-top: 1px solid rgba(255, 255, 255, 0.06);
  background: rgba(0, 0, 0, 0.25);
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  font-size: 11px;
  color: #cbd5e1;
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
  gap: 3px 12px;
}

.affected-file-item {
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.apps-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(360px, 1fr));
  gap: 14px;
}

.app-cfg-box {
  background: rgba(11, 15, 25, 0.6);
  border: 1px solid var(--border-color);
  border-radius: 8px;
  padding: 14px;
}

.app-cfg-box.active {
  border-color: rgba(0, 210, 255, 0.6);
  box-shadow: 0 0 0 1px rgba(0, 210, 255, 0.15);
}

.app-cfg-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 8px;
  margin-bottom: 6px;
}

.app-name {
  font-weight: 700;
  font-size: 14px;
  margin-right: 8px;
}

.app-key {
  font-size: 11px;
  padding: 2px 6px;
  border-radius: 4px;
  background: rgba(255, 255, 255, 0.06);
  color: var(--accent-cyan);
}

.app-desc {
  font-size: 12px;
  color: var(--text-muted);
  margin-bottom: 10px;
}

.tag {
  font-size: 11px;
  padding: 2px 7px;
  border-radius: 4px;
}

.tag-active {
  background: rgba(0, 210, 255, 0.15);
  color: #00d2ff;
}

.tag-yaml {
  background: rgba(0, 230, 118, 0.12);
  color: #00e676;
}

.tag-builtin {
  background: rgba(255, 179, 0, 0.12);
  color: #ffb300;
}

.two-col-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(380px, 1fr));
  gap: 18px;
}

.kv-list {
  display: flex;
  flex-direction: column;
  gap: 7px;
}

.kv-row {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 12px;
  font-size: 12px;
  padding-bottom: 5px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.04);
}

.kv-k {
  color: var(--text-muted);
  flex-shrink: 0;
}

.kv-v {
  color: var(--text-main);
  text-align: right;
  word-break: break-all;
}

.mono {
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
}

.modes-row {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
  gap: 10px;
  margin-bottom: 14px;
}

.mode-chip {
  background: rgba(11, 15, 25, 0.6);
  border: 1px solid var(--border-color);
  border-radius: 8px;
  padding: 10px 12px;
}

.mode-chip-title {
  font-size: 13px;
  font-weight: 600;
  margin-bottom: 4px;
}

.mode-chip-desc {
  font-size: 12px;
  color: var(--text-muted);
}

.templates-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.tpl-item {
  background: rgba(11, 15, 25, 0.6);
  border: 1px solid var(--border-color);
  border-radius: 8px;
  padding: 12px;
}

.tpl-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--accent-cyan);
  margin-bottom: 6px;
}

.tpl-body {
  font-size: 12px;
  color: var(--text-muted);
  white-space: pre-wrap;
  line-height: 1.5;
  font-family: inherit;
}
</style>
