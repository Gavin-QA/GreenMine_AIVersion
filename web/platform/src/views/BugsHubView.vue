<template>
        <div v-show="currentTab === 'bugs'">

          <!-- 1. 独立筛选栏卡片 (同级第 1 个 div，与下方缺陷列表清晰分离) -->
          <div class="card"
            style="margin-bottom: 16px; padding: 14px 18px; border: 1px solid rgba(56, 189, 248, 0.25); background: linear-gradient(135deg, rgba(15, 23, 42, 0.96), rgba(13, 20, 36, 0.98));">
            <div style="display: flex; flex-wrap: wrap; justify-content: space-between; align-items: center; gap: 14px;">

              <div style="display: flex; flex-wrap: wrap; align-items: center; gap: 14px;">
                <!-- 1. 全局关键字检索 (适中固定宽度) -->
                <div style="width: 240px; position: relative;">
                  <input type="text"
                    style="width: 100%; background: #0b1120; color: #e2e8f0; border: 1px solid var(--border-color); border-radius: 6px; padding: 5px 28px 5px 10px; font-size: 12px; outline: none;"
                    placeholder="🔍 检索编号 / 标题 / 报错 / 禅道..." v-model="bugSearch" @input="onBugSearchInput"
                    @keydown.enter="fetchBugs">
                  <span v-if="isBugsLoading"
                    style="position: absolute; right: 9px; top: 50%; transform: translateY(-50%); font-size: 12px; color: #00d2ff;"
                    title="正在快速过滤...">
                    ⚡
                  </span>
                </div>

                <!-- 2. 矿山(应用) -->
                <div style="display: flex; align-items: center; gap: 6px;">
                  <span style="font-size: 12px; font-weight: 600; color: #94a3b8; white-space: nowrap;">🎯 矿山(应用):</span>
                  <select v-model="bugAppFilter" @change="fetchBugs({ resetPage: true })"
                    style="background: #0b1120; color: #e2e8f0; border: 1px solid var(--border-color); border-radius: 6px; padding: 5px 10px; font-size: 12px; outline: none; cursor: pointer; min-width: 120px;">
                    <option value="">全部</option>
                    <option v-for="a in options.apps" :key="a.key" :value="a.key">
                      {{ a.name }}
                    </option>
                  </select>
                </div>

                <!-- 3. 严重程度 -->
                <div style="display: flex; align-items: center; gap: 6px;">
                  <span style="font-size: 12px; font-weight: 600; color: #94a3b8; white-space: nowrap;">⚡ 严重程度:</span>
                  <select v-model="bugSeverityFilter" @change="fetchBugs({ resetPage: true })"
                    style="background: #0b1120; color: #e2e8f0; border: 1px solid var(--border-color); border-radius: 6px; padding: 5px 10px; font-size: 12px; outline: none; cursor: pointer; min-width: 105px;">
                    <option value="">全部</option>
                    <option value="High">🔴 High (高)</option>
                    <option value="Medium">🟡 Medium (中)</option>
                    <option value="Low">🟢 Low (低)</option>
                  </select>
                </div>

                <!-- 4. 责任人 -->
                <div style="display: flex; align-items: center; gap: 6px;">
                  <span style="font-size: 12px; font-weight: 600; color: #94a3b8; white-space: nowrap;">👤 责任人:</span>
                  <select v-model="bugAssigneeFilter" @change="fetchBugs({ resetPage: true })"
                    style="background: #0b1120; color: #e2e8f0; border: 1px solid var(--border-color); border-radius: 6px; padding: 5px 10px; font-size: 12px; outline: none; cursor: pointer; min-width: 115px;">
                    <option value="">全部</option>
                    <option value="陈贻雄">👨‍💻 陈贻雄 (前端)</option>
                    <option value="梅本霞">👩‍💻 梅本霞 (后端)</option>
                    <option value="李云骢">📡 李云骢 (数据接入)</option>
                    <option value="靳正武">📡 靳正武 (数据接入)</option>
                  </select>
                </div>

                <!-- 5. 状态 -->
                <div style="display: flex; align-items: center; gap: 6px;">
                  <span style="font-size: 12px; font-weight: 600; color: #94a3b8; white-space: nowrap;">📌 状态:</span>
                  <select v-model="bugStatusFilter" @change="fetchBugs({ resetPage: true })"
                    style="background: #0b1120; color: #e2e8f0; border: 1px solid var(--border-color); border-radius: 6px; padding: 5px 10px; font-size: 12px; outline: none; cursor: pointer; min-width: 95px;">
                    <option value="">全部</option>
                    <option value="激活">🔥 激活 (Open)</option>
                    <option value="已提单">📋 已提单</option>
                    <option value="误报">⚪ 误报</option>
                    <option value="已解决">✅ 已解决</option>
                  </select>
                </div>

                <!-- 6. 复现频次 -->
                <div style="display: flex; align-items: center; gap: 6px;">
                  <span style="font-size: 12px; font-weight: 600; color: #94a3b8; white-space: nowrap;">🔄 复现频次:</span>
                  <select v-model="bugOccurrencesFilter" @change="fetchBugs({ resetPage: true })"
                    style="background: #0b1120; color: #e2e8f0; border: 1px solid var(--border-color); border-radius: 6px; padding: 5px 10px; font-size: 12px; outline: none; cursor: pointer; min-width: 120px;">
                    <option value="">全部</option>
                    <option value="1-2">🌱 偶发/初现 (1~2 次)</option>
                    <option value="3-9">⚡ 多发/频现 (3~9 次)</option>
                    <option value="10+">💥 顽固/高频 (≥ 10 次)</option>
                  </select>
                </div>
              </div>

              <button class="btn btn-secondary" @click="resetBugFilters" style="padding: 5px 12px; font-size: 12px; white-space: nowrap;"
                title="清空全部筛选条件">
                ↺ 重置筛选
              </button>

            </div>
          </div>

          <!-- 2. 缺陷列表卡片 (同级第 2 个 div) -->
          <div class="card">

            <div class="card-header" style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 10px;">
              <div class="card-title">🐛 全局缺陷治理中枢 (AI 智能查重去重与分流)</div>

              <div style="display: flex; align-items: center; gap: 10px; flex-wrap: wrap;">
                <!-- 后台批量推禅道进度条 -->
                <div v-if="batchZentaoJob && batchZentaoJob.status === 'running'"
                  style="display: flex; align-items: center; gap: 8px; padding: 4px 10px; border-radius: 6px; background: rgba(0, 210, 255, 0.1); border: 1px solid rgba(0, 210, 255, 0.35); font-size: 12px; color: #00d2ff;">
                  <span class="spinner-icon"></span>
                  <span>
                    后台推禅道中: <strong>{{ batchZentaoJob.processed }}/{{ batchZentaoJob.total }}</strong>
                    (成功 {{ batchZentaoJob.succeeded }}<template v-if="batchZentaoJob.skipped"> · 跳过 {{ batchZentaoJob.skipped }}</template><template v-if="batchZentaoJob.failed"> · 失败 {{ batchZentaoJob.failed }}</template>)
                  </span>
                </div>

                <!-- 勾选批量操作栏 -->
                <template v-if="selectedBugIds && selectedBugIds.length > 0">
                  <span style="font-size: 12px; color: #94a3b8;">
                    已选 <strong style="color: #00d2ff;">{{ selectedBugIds.length }}</strong> 条
                  </span>
                  <button class="btn btn-primary"
                    style="padding: 5px 12px; font-size: 12px;"
                    :disabled="batchZentaoJob && batchZentaoJob.status === 'running'"
                    @click="batchSyncZenTao">
                    🚀 批量推禅道 ({{ selectedBugIds.length }})
                  </button>
                  <button class="btn btn-secondary"
                    style="padding: 5px 10px; font-size: 12px;"
                    @click="clearBugSelection">
                    清空选择
                  </button>
                </template>

                <span v-else-if="!batchZentaoJob || batchZentaoJob.status !== 'running'"
                  style="font-size: 12px; color: var(--text-muted);">✨ 智能关联实时过滤</span>
              </div>
            </div>



            <div class="table-responsive">

              <table class="data-table">

                <thead>

                  <tr>

                    <th style="width: 38px; text-align: center;">
                      <input type="checkbox"
                        :checked="isAllPageBugsSelected"
                        :indeterminate.prop="isSomePageBugsSelected"
                        :disabled="!selectableBugsOnPage || selectableBugsOnPage.length === 0"
                        @change="toggleSelectAllPageBugs"
                        title="全选/取消全选当前页未提单缺陷"
                        style="cursor: pointer; accent-color: #00d2ff; width: 15px; height: 15px;">
                    </th>

                    <th>Bug 编号</th>

                    <th>标题与报错信息</th>

                    <th>严重程度</th>

                    <th>责任人</th>

                    <th>状态</th>

                    <th>禅道单号</th>

                    <th>频次</th>
                    <th>最近一次出现</th>

                    <th>操作</th>

                  </tr>

                </thead>

                <tbody>

                  <tr v-if="isBugsLoading && (!bugs || bugs.length === 0)">

                    <td colspan="10" style="text-align: center; padding: 28px; color: #00d2ff;">

                      ⚡ 正在极速检索缺陷资产...

                    </td>

                  </tr>

                  <tr v-else-if="!bugs || bugs.length === 0">

                    <td colspan="10" style="text-align: center; padding: 28px; color: var(--text-muted);">

                      🔍 未检索到匹配的缺陷记录

                    </td>

                  </tr>

                  <tr v-else v-for="b in paginatedBugs" :key="b.id"
                    :style="deletingBugId === b.id ? 'opacity: 0.45; transition: opacity 0.3s; pointer-events: none;' : ''">

                    <td style="text-align: center;">
                      <input type="checkbox"
                        :checked="selectedBugIds.includes(b.id)"
                        :disabled="!!b.zentao_id"
                        @change="toggleBugSelection(b)"
                        :title="b.zentao_id ? '已提交禅道 (#' + b.zentao_id + ')，无需重复勾选' : '勾选该缺陷用于批量推禅道'"
                        style="accent-color: #00d2ff; width: 15px; height: 15px;"
                        :style="{ cursor: b.zentao_id ? 'not-allowed' : 'pointer', opacity: b.zentao_id ? 0.35 : 1 }">
                    </td>

                    <td style="font-family: monospace; font-weight: 600; color: #00d2ff;">
                      {{ b.id }}
                      <div v-if="b.app_name" style="font-size: 10px; color: #64748b; margin-top: 2px;">
                        {{ getAppName(b.app_name) }}
                      </div>
                    </td>

                    <td>

                      <div style="font-weight: 500; cursor: pointer;" @click="viewBugDetail(b)">{{ b.title }}</div>

                      <div
                        style="font-size: 11px; color: var(--text-muted); max-width: 450px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">

                        {{ b.actual_error }}

                      </div>

                    </td>

                    <td>

                      <span class="badge" :class="'badge-' + b.severity.toLowerCase()">{{ b.severity }}</span>

                    </td>

                    <td>{{ b.assignee }}</td>

                    <td>{{ b.status }}</td>

                    <td>

                      <a v-if="b.zentao_id" :href="formatZenTaoUrl(b.zentao_id)" target="_blank"
                        style="color: #00e676; font-weight: 600; text-decoration: underline; text-underline-offset: 3px;"
                        title="点击跳转至禅道查看缺陷详情">

                        #{{ b.zentao_id }} ↗

                      </a>

                      <span v-else style="color: var(--text-muted);">-</span>

                    </td>

                    <td>{{ b.occurrences }} 次</td>

                    <td style="font-size: 12px; color: #a0aec0; font-family: monospace; white-space: nowrap;">
                      {{ formatDateTime(b.last_seen) }}
                    </td>

                    <td style="white-space: nowrap;">

                      <button class="btn btn-secondary" style="padding: 4px 8px; font-size: 12px;"
                        @click="viewBugDetail(b)">

                        详情

                      </button>

                      <button class="btn btn-secondary"
                        style="padding: 4px 8px; font-size: 12px; margin-left: 6px; border-color: #00d2ff; color: #00d2ff;"
                        @click="openEditBugModal(b)">

                        编辑

                      </button>

                      <button v-if="!b.zentao_id" class="btn btn-primary"
                        style="padding: 4px 8px; font-size: 12px; margin-left: 6px;" :disabled="b._syncing"
                        @click="syncZenTao(b)">
                        {{ b._syncing ? '提单中...' : '推禅道' }}
                      </button>

                      <!-- 仅未提交禅道的缺陷开放物理删除权限，已提单缺陷严禁随意删除 -->
                      <button v-if="!b.zentao_id" class="btn btn-secondary"
                        style="padding: 4px 8px; font-size: 12px; margin-left: 6px; border-color: #ff5252; color: #ff5252;"
                        :disabled="deletingBugId === b.id"
                        @click="deleteBug(b)"
                        :title="'彻底清理未提单缺陷 ' + b.id">
                        <span v-if="deletingBugId === b.id" class="spinner-icon"></span>
                        <span v-if="deletingBugId === b.id">清理中</span>
                        <span v-else>🗑️ 删除</span>
                      </button>

                    </td>

                  </tr>

                </tbody>

              </table>

            </div>

            <!-- 缺陷治理中枢分页工具栏 -->
            <div class="pagination-container" v-if="totalBugs > 0">
              <div class="pagination-left">
                <span>共筛选出 <strong style="color: #00d2ff;">{{ totalBugs }}</strong> 条缺陷</span>
                <span style="color: var(--border-color);">|</span>
                <span>每页显示</span>
                <select class="pagination-select" v-model.number="bugPageSize" @change="onBugPageSizeChange">
                  <option v-for="size in bugPageSizes" :key="size" :value="size">{{ size }} 条/页</option>
                </select>
              </div>

              <div class="pagination-right">
                <button class="page-btn" :disabled="bugPage <= 1" @click="setBugPage(bugPage - 1)" title="上一页">
                  &lt;
                </button>

                <template v-for="(p, idx) in getPageNumbers(bugPage, totalBugPages)" :key="'bp-' + idx">
                  <span v-if="p === '...'" class="page-btn ellipsis">...</span>
                  <button v-else class="page-btn" :class="{ active: p === bugPage }" @click="setBugPage(p)">
                    {{ p }}
                  </button>
                </template>

                <button class="page-btn" :disabled="bugPage >= totalBugPages" @click="setBugPage(bugPage + 1)"
                  title="下一页">
                  &gt;
                </button>

                <span style="margin: 0 4px; color: var(--text-muted);">第 {{ bugPage }} / {{ totalBugPages }} 页</span>

                <span style="margin-left: 6px;">跳至</span>
                <input type="number" class="page-jump-input" min="1" :max="totalBugPages" v-model.number="bugPageJump"
                  @keydown.enter="jumpToBugPage">
                <span>页</span>
                <button class="page-btn" style="padding: 0 10px; margin-left: 4px;" @click="jumpToBugPage">确定</button>
              </div>
            </div>

          </div>

        </div>

</template>

<script>
import { inject } from 'vue'
export default {
  setup() {
    return inject('platformStore')
  }
}
</script>
