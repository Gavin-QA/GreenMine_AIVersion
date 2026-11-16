<template>
        <div v-show="currentTab === 'dashboard'">

          <!-- 🌟 标准预设巡检任务库 -->
          <div class="card" style="border-left: 4px solid #00d2ff;">
            <div class="card-header" style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 12px;">
              <div>
                <div class="card-title" style="display: flex; align-items: center; gap: 8px;">
                  <span>🌟 标准预设巡检任务库</span>
                  <span class="badge" style="background: rgba(0, 210, 255, 0.15); color: #00d2ff; font-weight: normal; font-size: 11px;">共 {{ presetTasks.length }} 项方案</span>
                </div>
                <div style="font-size: 12px; color: var(--text-muted); margin-top: 4px;">系统标杆方案与用户个性化预设，支持卡片/列表无缝切换与参数微调</div>
              </div>

              <!-- 右侧操作工具条: 视图切换 + 新建任务 -->
              <div style="display: flex; align-items: center; gap: 12px;">
                <!-- 视图切换单选按钮组 -->
                <div style="display: inline-flex; background: rgba(13, 20, 36, 0.8); border: 1px solid #1a253c; border-radius: 6px; padding: 2px;">
                  <button
                    type="button"
                    class="btn"
                    :style="presetViewMode === 'card' ? 'background: #00d2ff; color: #05070d; font-weight: 700;' : 'background: transparent; color: var(--text-muted); border: none;'"
                    style="padding: 5px 12px; font-size: 12px; border-radius: 4px; border: none; cursor: pointer; transition: all 0.2s;"
                    @click="setPresetViewMode('card')"
                    title="切换为卡片网格视图">
                    🔲 卡片视图
                  </button>
                  <button
                    type="button"
                    class="btn"
                    :style="presetViewMode === 'list' ? 'background: #00d2ff; color: #05070d; font-weight: 700;' : 'background: transparent; color: var(--text-muted); border: none;'"
                    style="padding: 5px 12px; font-size: 12px; border-radius: 4px; border: none; cursor: pointer; transition: all 0.2s;"
                    @click="setPresetViewMode('list')"
                    title="切换为高密度数据列表视图">
                    📋 列表视图
                  </button>
                </div>

                <!-- ➕ 新建任务按钮 -->
                <button
                  type="button"
                  class="btn btn-primary"
                  style="padding: 7px 18px; font-size: 13px; font-weight: 600; display: flex; align-items: center; gap: 6px;"
                  @click="openNewTaskModal"
                  title="唤起参数配置弹窗，新建巡检任务或保存为新预设">
                  <span style="font-size: 14px;">➕</span> 新建任务
                </button>
              </div>
            </div>

            <!-- 空状态 -->
            <div v-if="presetTasks.length === 0"
              style="padding: 40px 24px; text-align: center; color: var(--text-muted); font-size: 13px;">
              <div style="font-size: 32px; margin-bottom: 12px;">📭</div>
              <div>暂无预设任务方案。您可以点击右上角【➕ 新建任务】按需配置参数并保存为新预设。</div>
            </div>

            <!-- 1. 卡片网格视图 (默认) -->
            <div v-else-if="presetViewMode === 'card'" class="grid-3" style="margin-top: 10px;">
              <div v-for="p in sortedPresetTasks" :key="p.id" class="card"
                style="background: #0d1424; margin-bottom: 0; display: flex; flex-direction: column; justify-content: space-between; border-color: #1a253c; border-radius: 8px;">
                <div>
                  <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
                    <!-- 运行模式徽标 (居左) -->
                    <span class="badge" style="white-space: nowrap;"
                      :class="(p.tour || p.mode === 'smoke') ? 'badge-running' : (p.mode === 'case' ? 'badge-low' : 'badge-high')">
                      {{ getPresetModeLabel(p) }}
                    </span>
                    <!-- 预设快速删除按钮 (图标+文字，居右) -->
                    <button
                      type="button"
                      style="background: transparent; border: 1px solid rgba(255,82,82,0.25); border-radius: 4px; color: #ff5252; cursor: pointer; padding: 2px 7px; font-size: 11px; transition: all 0.2s; display: inline-flex; align-items: center; gap: 4px;"
                      onmouseover="this.style.background='rgba(255,82,82,0.2)'; this.style.borderColor='#ff5252';"
                      onmouseout="this.style.background='transparent'; this.style.borderColor='rgba(255,82,82,0.25)';"
                      @click="deletePreset(p)" title="彻底删除此预设">
                      🗑️ 删除
                    </button>
                  </div>

                  <!-- 运行的矿山应用明确展示 -->
                  <div style="font-size: 12px; color: #00d2ff; font-weight: 600; margin-bottom: 6px;">
                    🎯 运行矿山: <span style="color: #fff;">{{ getAppName(p.app_name) }}</span>
                  </div>

                  <div style="font-weight: 700; font-size: 14px; margin-bottom: 12px; color: #fff;">{{ p.title }}</div>
                  <div style="font-size: 11px; color: #8b9bb4; margin-bottom: 14px;">
                    <span>步数: <b style="color: #00d2ff;">{{ p.max_steps ? p.max_steps + ' 步' : '无限制 (0步)' }}</b></span> &nbsp;|&nbsp;
                    <span>时限: <b style="color: #ffb300;">{{ p.max_times }}</b> 分钟</span>
                  </div>
                </div>

                <div
                  style="display: flex; gap: 6px; margin-top: auto; border-top: 1px solid #1a253c; padding-top: 10px; align-items: center;">
                  <button type="button" class="btn btn-secondary"
                    style="flex: 1; padding: 6px 4px; font-size: 11px; justify-content: center; white-space: nowrap;"
                    @click="openPresetDetail(p)" title="查看完整提示词与高阶参数">
                    🔍 详情
                  </button>
                  <button type="button" class="btn btn-secondary"
                    style="flex: 1; padding: 6px 4px; font-size: 11px; justify-content: center; white-space: nowrap;"
                    @click="loadPresetToForm(p)" title="弹窗编辑配置，可微调并直接覆盖或另存">
                    ✏️ 编辑
                  </button>
                  <button type="button" class="btn btn-primary"
                    style="flex: 1; padding: 6px 4px; font-size: 11px; justify-content: center; white-space: nowrap;"
                    @click="launchPreset(p)" title="立即以当前预设创建并启动巡检任务">
                    🚀 立即运行
                  </button>
                </div>
              </div>
            </div>

            <!-- 2. 数据列表视图 (高密度表格，字段严格对齐) -->
            <div v-else class="table-container" style="margin-top: 12px; overflow-x: auto;">
              <table class="data-table">
                <thead>
                  <tr>
                    <th style="text-align: center; width: 60px; min-width: 60px; white-space: nowrap;">序号</th>
                    <th style="cursor: pointer; user-select: none; width: 25%; min-width: 200px; white-space: nowrap;" @click="togglePresetSort('title')" title="点击按任务名称排序">
                      <div style="display: inline-flex; align-items: center;">
                        <span>任务名称</span>
                        <span style="display: inline-flex; flex-direction: column; align-items: center; vertical-align: middle; margin-left: 6px; gap: 2px;">
                          <svg viewBox="0 0 10 5" width="8" height="4"><polygon points="5,0 10,5 0,5" :fill="presetSortField === 'title' && presetSortOrder === 'asc' ? '#00d2ff' : '#475569'" /></svg>
                          <svg viewBox="0 0 10 5" width="8" height="4"><polygon points="0,0 10,0 5,5" :fill="presetSortField === 'title' && presetSortOrder === 'desc' ? '#00d2ff' : '#475569'" /></svg>
                        </span>
                      </div>
                    </th>
                    <th style="cursor: pointer; user-select: none; width: 14%; min-width: 130px; white-space: nowrap;" @click="togglePresetSort('app_name')" title="点击按运行矿山排序">
                      <div style="display: inline-flex; align-items: center;">
                        <span>运行矿山</span>
                        <span style="display: inline-flex; flex-direction: column; align-items: center; vertical-align: middle; margin-left: 6px; gap: 2px;">
                          <svg viewBox="0 0 10 5" width="8" height="4"><polygon points="5,0 10,5 0,5" :fill="presetSortField === 'app_name' && presetSortOrder === 'asc' ? '#00d2ff' : '#475569'" /></svg>
                          <svg viewBox="0 0 10 5" width="8" height="4"><polygon points="0,0 10,0 5,5" :fill="presetSortField === 'app_name' && presetSortOrder === 'desc' ? '#00d2ff' : '#475569'" /></svg>
                        </span>
                      </div>
                    </th>
                    <th style="cursor: pointer; user-select: none; width: 12%; min-width: 110px; white-space: nowrap;" @click="togglePresetSort('mode')" title="点击按运行模式排序">
                      <div style="display: inline-flex; align-items: center;">
                        <span>运行模式</span>
                        <span style="display: inline-flex; flex-direction: column; align-items: center; vertical-align: middle; margin-left: 6px; gap: 2px;">
                          <svg viewBox="0 0 10 5" width="8" height="4"><polygon points="5,0 10,5 0,5" :fill="presetSortField === 'mode' && presetSortOrder === 'asc' ? '#00d2ff' : '#475569'" /></svg>
                          <svg viewBox="0 0 10 5" width="8" height="4"><polygon points="0,0 10,0 5,5" :fill="presetSortField === 'mode' && presetSortOrder === 'desc' ? '#00d2ff' : '#475569'" /></svg>
                        </span>
                      </div>
                    </th>
                    <th style="cursor: pointer; user-select: none; width: 14%; min-width: 140px; white-space: nowrap;" @click="togglePresetSort('max_steps')" title="点击按最大步数限制排序">
                      <div style="display: inline-flex; align-items: center;">
                        <span>最大步数限制 (Steps)</span>
                        <span style="display: inline-flex; flex-direction: column; align-items: center; vertical-align: middle; margin-left: 6px; gap: 2px;">
                          <svg viewBox="0 0 10 5" width="8" height="4"><polygon points="5,0 10,5 0,5" :fill="presetSortField === 'max_steps' && presetSortOrder === 'asc' ? '#00d2ff' : '#475569'" /></svg>
                          <svg viewBox="0 0 10 5" width="8" height="4"><polygon points="0,0 10,0 5,5" :fill="presetSortField === 'max_steps' && presetSortOrder === 'desc' ? '#00d2ff' : '#475569'" /></svg>
                        </span>
                      </div>
                    </th>
                    <th style="cursor: pointer; user-select: none; width: 13%; min-width: 130px; white-space: nowrap;" @click="togglePresetSort('max_times')" title="点击按最长运行时间排序">
                      <div style="display: inline-flex; align-items: center;">
                        <span>最长运行时间 (分钟)</span>
                        <span style="display: inline-flex; flex-direction: column; align-items: center; vertical-align: middle; margin-left: 6px; gap: 2px;">
                          <svg viewBox="0 0 10 5" width="8" height="4"><polygon points="5,0 10,5 0,5" :fill="presetSortField === 'max_times' && presetSortOrder === 'asc' ? '#00d2ff' : '#475569'" /></svg>
                          <svg viewBox="0 0 10 5" width="8" height="4"><polygon points="0,0 10,0 5,5" :fill="presetSortField === 'max_times' && presetSortOrder === 'desc' ? '#00d2ff' : '#475569'" /></svg>
                        </span>
                      </div>
                    </th>
                    <th style="text-align: left; width: 20%; min-width: 300px; white-space: nowrap;">操作</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="(p, index) in sortedPresetTasks" :key="p.id">
                    <!-- 1. 序号 (动态行号，居中展示) -->
                    <td style="text-align: center; font-weight: 600; color: #94a3b8; font-family: monospace; font-size: 13px;">
                      {{ index + 1 }}
                    </td>

                    <!-- 2. 任务名称 (纯净标题展示) -->
                    <td>
                      <span style="font-weight: 600; font-size: 13px; color: #fff;">{{ p.title }}</span>
                    </td>

                    <!-- 2. 运行矿山 -->
                    <td>
                      <span style="color: #00d2ff; font-weight: 600; font-size: 12px; display: inline-flex; align-items: center; gap: 4px;">
                        <span>🎯</span> {{ getAppName(p.app_name) }}
                      </span>
                    </td>

                    <!-- 3. 运行模式 -->
                    <td>
                      <span class="badge"
                        :class="(p.tour || p.mode === 'smoke') ? 'badge-running' : (p.mode === 'case' ? 'badge-low' : 'badge-high')">
                        {{ getPresetModeLabel(p) }}
                      </span>
                    </td>

                    <!-- 4. 最大步数限制 (Steps) -->
                    <td>
                      <span style="font-family: monospace; font-weight: 600;" :style="p.max_steps ? 'color: #00d2ff;' : 'color: #64748b;'">
                        {{ p.max_steps ? (p.max_steps + ' 步') : '无限制 (0步)' }}
                      </span>
                    </td>

                    <!-- 5. 最长运行时间 (分钟) -->
                    <td>
                      <span style="font-family: monospace; font-weight: 600; color: #ffb300;">
                        {{ p.max_times }} 分钟
                      </span>
                    </td>

                    <!-- 6. 操作 (🔍 详情、✏️ 编辑、🚀 立即运行、🗑️ 删除，左对齐，强制单行不折行) -->
                    <td style="text-align: left; white-space: nowrap;">
                      <div style="display: inline-flex; align-items: center; gap: 6px; justify-content: flex-start; flex-wrap: nowrap;">
                        <button type="button" class="btn btn-secondary" style="padding: 4px 8px; font-size: 11px; border-color: #3b82f6; color: #93c5fd; white-space: nowrap;"
                          @click="openPresetDetail(p)" title="查看该预设的完整提示词与详细参数">
                          🔍 详情
                        </button>
                        <button type="button" class="btn btn-secondary" style="padding: 4px 8px; font-size: 11px; border-color: #64748b; color: #cbd5e1; white-space: nowrap;"
                          @click="loadPresetToForm(p)" title="弹窗编辑配置，可微调并直接覆盖或另存">
                          ✏️ 编辑
                        </button>
                        <button type="button" class="btn btn-primary" style="padding: 4px 10px; font-size: 11px; font-weight: 600; white-space: nowrap;"
                          @click="launchPreset(p)" title="立即以当前预设创建并启动巡检任务">
                          🚀 立即运行
                        </button>
                        <button
                          type="button"
                          style="background: transparent; border: 1px solid rgba(255,82,82,0.25); border-radius: 4px; color: #ff5252; cursor: pointer; padding: 4px 8px; font-size: 11px; transition: all 0.2s; white-space: nowrap; display: inline-flex; align-items: center; gap: 4px;"
                          onmouseover="this.style.background='rgba(255,82,82,0.2)'; this.style.borderColor='#ff5252';"
                          onmouseout="this.style.background='transparent'; this.style.borderColor='rgba(255,82,82,0.25)';"
                          @click="deletePreset(p)" title="彻底删除此预设">
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



        <!-- ============================================================= -->

        <!-- 2. 实时监控大屏 (ECharts 曲线 + 实时日志流推流) -->

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
