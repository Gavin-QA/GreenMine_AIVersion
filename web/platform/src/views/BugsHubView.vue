<template>
        <div v-show="currentTab === 'bugs'">

          <!-- 1. 独立筛选栏卡片 (同级第 1 个 div，与下方缺陷列表清晰分离) -->
          <div class="card"
            style="margin-bottom: 16px; padding: 14px 18px; border: 1px solid rgba(56, 189, 248, 0.25); background: linear-gradient(135deg, rgba(15, 23, 42, 0.96), rgba(13, 20, 36, 0.98));">
            <div style="display: flex; flex-wrap: wrap; gap: 10px; align-items: center;">
              <!-- 1. 全局关键字检索 (Bug编号、标题、报错堆栈、禅道单号) -->
              <div style="flex: 1; min-width: 240px; position: relative;">
                <input type="text" class="form-control" style="width: 100%; padding-right: 30px;"
                  placeholder="🔍 检索 Bug 编号 / 标题 / 报错堆栈 / 禅道单号..." v-model="bugSearch" @input="onBugSearchInput"
                  @keydown.enter="fetchBugs">
                <span v-if="isBugsLoading"
                  style="position: absolute; right: 10px; top: 50%; transform: translateY(-50%); font-size: 12px; color: #00d2ff;"
                  title="正在快速过滤...">
                  ⚡
                </span>
              </div>

              <!-- 2. 所属应用 / 矿山下拉项 -->
              <div style="width: 175px;">
                <select class="form-control" style="width: 100%;" v-model="bugAppFilter"
                  @change="fetchBugs({ resetPage: true })">
                  <option value="">🏔️ 全部矿山 (应用)</option>
                  <option v-for="a in options.apps" :key="a.key" :value="a.key">
                    🏔️ {{ a.name }} ({{ a.key }})
                  </option>
                </select>
              </div>

              <!-- 3. 严重程度下拉项 -->
              <div style="width: 135px;">
                <select class="form-control" style="width: 100%;" v-model="bugSeverityFilter"
                  @change="fetchBugs({ resetPage: true })">
                  <option value="">⚡ 全部严重程度</option>
                  <option value="High">🔴 High (高)</option>
                  <option value="Medium">🟡 Medium (中)</option>
                  <option value="Low">🟢 Low (低)</option>
                </select>
              </div>

              <!-- 4. 责任人下拉项 -->
              <div style="width: 145px;">
                <select class="form-control" style="width: 100%;" v-model="bugAssigneeFilter"
                  @change="fetchBugs({ resetPage: true })">
                  <option value="">👤 全部责任人</option>
                  <option value="陈贻雄">👨‍💻 陈贻雄 (前端)</option>
                  <option value="梅本霞">👩‍💻 梅本霞 (后端)</option>
                  <option value="李云骢">📡 李云骢 (数据接入)</option>
                  <option value="靳正武">📡 靳正武 (数据接入)</option>
                </select>
              </div>

              <!-- 5. 状态下拉项 -->
              <div style="width: 130px;">
                <select class="form-control" style="width: 100%;" v-model="bugStatusFilter"
                  @change="fetchBugs({ resetPage: true })">
                  <option value="">📌 全部状态</option>
                  <option value="激活">🔥 激活 (Open)</option>
                  <option value="已提单">📋 已提单</option>
                  <option value="误报">⚪ 误报</option>
                  <option value="已解决">✅ 已解决</option>
                </select>
              </div>

              <!-- 6. 频次范围 3 个区间下拉项 -->
              <div style="width: 160px;">
                <select class="form-control" style="width: 100%;" v-model="bugOccurrencesFilter"
                  @change="fetchBugs({ resetPage: true })">
                  <option value="">🔄 全部频次</option>
                  <option value="1-2">🌱 偶发/初现 (1~2 次)</option>
                  <option value="3-9">⚡ 多发/频现 (3~9 次)</option>
                  <option value="10+">💥 顽固/高频 (≥ 10 次)</option>
                </select>
              </div>

              <button class="btn btn-secondary" @click="resetBugFilters" style="padding: 5px 12px; font-size: 12px; white-space: nowrap;"
                title="清空全部筛选条件">
                ↺ 重置筛选
              </button>
            </div>
          </div>

          <!-- 2. 缺陷列表卡片 (同级第 2 个 div) -->
          <div class="card">

            <div class="card-header" style="display: flex; justify-content: space-between; align-items: center;">
              <div class="card-title">🐛 全局缺陷治理中枢 (AI 智能查重去重与分流)</div>
              <span style="font-size: 12px; color: var(--text-muted);">✨ 智能关联实时过滤</span>
            </div>



            <div class="table-responsive">

              <table class="data-table">

                <thead>

                  <tr>

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

                    <td colspan="9" style="text-align: center; padding: 28px; color: #00d2ff;">

                      ⚡ 正在极速检索缺陷资产...

                    </td>

                  </tr>

                  <tr v-else-if="!bugs || bugs.length === 0">

                    <td colspan="9" style="text-align: center; padding: 28px; color: var(--text-muted);">

                      🔍 未检索到匹配的缺陷记录

                    </td>

                  </tr>

                  <tr v-else v-for="b in paginatedBugs" :key="b.id"
                    :style="deletingBugId === b.id ? 'opacity: 0.45; transition: opacity 0.3s; pointer-events: none;' : ''">

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
