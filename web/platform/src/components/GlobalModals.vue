<template>
          <!-- 缺陷详情弹窗 -->

          <div class="modal-overlay" v-if="selectedBug" @click.self="selectedBug = null">

            <div class="modal-content">

              <div class="modal-header">

                <div>

                  <h3 style="display: flex; align-items: center; gap: 10px;">

                    <span>[{{ selectedBug.id }}] 缺陷详细诊断分析</span>

                    <a v-if="selectedBug.zentao_id" :href="formatZenTaoUrl(selectedBug.zentao_id)" target="_blank"
                      class="badge"
                      style="background: rgba(0, 230, 118, 0.15); color: #00e676; border: 1px solid rgba(0, 230, 118, 0.3); text-decoration: none;">

                      禅道工单 #{{ selectedBug.zentao_id }} ↗

                    </a>

                  </h3>

                </div>

                <button class="modal-close" @click="selectedBug = null">&times;</button>

              </div>

              <div class="form-group">

                <label class="form-label">缺陷标题</label>

                <div style="font-weight: 600;">{{ selectedBug.title }}</div>

              </div>

              <div class="grid-2">

                <div class="form-group">

                  <label class="form-label">责任人 (自动分流)</label>

                  <div>{{ selectedBug.assignee }}</div>

                </div>

                <div class="form-group">

                  <label class="form-label">当前状态</label>

                  <div style="display: flex; align-items: center; gap: 10px;">

                    <span>{{ selectedBug.status }} (复现 {{ selectedBug.occurrences }} 次)</span>

                    <a v-if="selectedBug.zentao_id" :href="formatZenTaoUrl(selectedBug.zentao_id)" target="_blank"
                      style="color: #00e676; font-size: 13px; font-weight: 600; text-decoration: underline;">

                      进入禅道查看 #{{ selectedBug.zentao_id }}

                    </a>

                  </div>

                </div>

              </div>

              <div class="grid-2">

                <div class="form-group">

                  <label class="form-label">首次发现时间</label>

                  <div style="font-family: monospace; color: #cbd5e1;">{{ formatDateTime(selectedBug.first_seen) || '-' }}</div>

                </div>

                <div class="form-group">

                  <label class="form-label">最近复现时间</label>

                  <div style="font-family: monospace; color: #38bdf8; font-weight: 600;">{{ formatDateTime(selectedBug.last_seen) || '-' }}</div>

                </div>

              </div>

              <div class="form-group" v-if="selectedBug.run_id || selectedBug.task_id">

                <label class="form-label">📍 案发运行批次 (Run ID / Task ID)</label>

                <div style="display: flex; align-items: center; gap: 10px; flex-wrap: wrap;">

                  <code v-if="selectedBug.run_id"
                    style="background: #0f172a; color: #38bdf8; padding: 4px 8px; border-radius: 4px; font-size: 12px; border: 1px solid #1e293b; font-family: monospace;">{{ selectedBug.run_id }}</code>

                  <code v-if="selectedBug.task_id"
                    style="background: #0f172a; color: #94a3b8; padding: 4px 8px; border-radius: 4px; font-size: 12px; border: 1px solid #1e293b; font-family: monospace;">{{ selectedBug.task_id }}</code>

                  <button type="button" class="btn btn-secondary"
                    style="padding: 4px 10px; font-size: 12px; border-color: #00d2ff; color: #00d2ff;"
                    @click="jumpToBugMonitor(selectedBug)">
                    📈 前往监控大屏复盘
                  </button>

                  <a v-if="selectedBug.run_id" :href="'reports/runs/' + (selectedBug.app_name || 'zhaiwan') + '/' + selectedBug.run_id + '/report.html'"
                    target="_blank"
                    style="color: #60a5fa; font-size: 13px; text-decoration: underline; font-weight: 500;">

                    查看该批次完整测试报告 ↗

                  </a>

                </div>

              </div>

              <div class="form-group" v-if="selectedBug.step">

                <label class="form-label">🎯 案发交互步骤 (Step)</label>

                <div style="background: #111827; padding: 10px 12px; border-radius: 6px; font-size: 13px; color: #f1f5f9; border-left: 3px solid #38bdf8; word-break: break-all;">
                  {{ selectedBug.step }}
                </div>

              </div>

              <div class="form-group">

                <label class="form-label">案发现场实际报错</label>

                <pre
                  style="background: #05070d; padding: 12px; border-radius: 6px; font-size: 12px; color: #ff6b6b; white-space: pre-wrap; word-break: break-all;">{{ selectedBug.actual_error || '（该早期归档缺陷未留存独立报错堆栈，请参考上方标题或下方 AI 智能诊断）' }}</pre>

              </div>

              <div class="form-group">

                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px;">
                  <label class="form-label" style="margin: 0;">🤖 AI 智能初诊与排查指引</label>
                  <button class="btn btn-secondary"
                    style="padding: 3px 10px; font-size: 11px; color: #38bdf8; border-color: rgba(56, 189, 248, 0.4); display: flex; align-items: center; gap: 4px;"
                    :disabled="reanalyzingBugId === selectedBug.id"
                    @click="reanalyzeBug(selectedBug)">
                    <span v-if="reanalyzingBugId === selectedBug.id">⏳ AI 诊断中...</span>
                    <span v-else>🔄 重新AI深度研判</span>
                  </button>
                </div>

                <div v-if="selectedBug.analysis_notes"
                  style="background: #111827; padding: 12px; border-radius: 6px; font-size: 13px; line-height: 1.6; white-space: pre-wrap;">
                  {{ selectedBug.analysis_notes }}</div>
                <div v-else
                  style="background: #111827; padding: 12px; border-radius: 6px; font-size: 12px; color: var(--text-muted);">
                  暂无 AI 归因研判，可点击上方“重新AI深度研判”按钮在线生成。</div>

              </div>

              <div class="form-group" v-if="selectedBug.remark">

                <label class="form-label">📌 处理备注 / 关闭原因</label>

                <div
                  style="background: rgba(16, 185, 129, 0.1); border: 1px solid rgba(16, 185, 129, 0.3); color: #34d399; padding: 12px; border-radius: 6px; font-size: 13px; line-height: 1.6; white-space: pre-wrap;">
                  {{ selectedBug.remark }}</div>

              </div>

              <div class="form-group" v-if="selectedBug.screenshot_path || selectedBug.before_screenshot_path">

                <label class="form-label">
                  {{ (selectedBug.before_screenshot_path && selectedBug.screenshot_path) ? '双图现场溯源对比 (操作前 vs 案发瞬间)' : '现场快照截图' }}
                </label>

                <!-- 双图并排对比模式 -->
                <div v-if="selectedBug.before_screenshot_path && selectedBug.screenshot_path"
                  style="display: grid; grid-template-columns: 1fr 1fr; gap: 12px; background: #05070d; border-radius: 8px; padding: 12px; border: 1px solid var(--border-color);">

                  <div style="text-align: center; position: relative; border: 1px solid rgba(16, 185, 129, 0.4); border-radius: 6px; padding: 8px; background: rgba(16, 185, 129, 0.04);">
                    <span style="display: inline-block; font-size: 11px; font-weight: 700; padding: 2px 8px; border-radius: 4px; color: #fff; background: rgba(16, 185, 129, 0.85); margin-bottom: 6px;">
                      操作前 (目标位置)
                    </span>
                    <a :href="formatScreenshotUrl(selectedBug.before_screenshot_path)" target="_blank" title="点击查看操作前高清大图" style="display: block;">
                      <img :src="formatScreenshotUrl(selectedBug.before_screenshot_path)"
                        style="max-width: 100%; max-height: 420px; object-fit: contain; border-radius: 4px;"
                        alt="操作前现场截图">
                    </a>
                    <div style="font-size: 10px; color: var(--text-muted); margin-top: 6px; font-family: monospace; word-break: break-all;">
                      {{ formatScreenshotUrl(selectedBug.before_screenshot_path) }}
                    </div>
                  </div>

                  <div style="text-align: center; position: relative; border: 1px solid rgba(244, 63, 94, 0.4); border-radius: 6px; padding: 8px; background: rgba(244, 63, 94, 0.04);">
                    <span style="display: inline-block; font-size: 11px; font-weight: 700; padding: 2px 8px; border-radius: 4px; color: #fff; background: rgba(244, 63, 94, 0.85); margin-bottom: 6px;">
                      案发瞬间 (报错现场)
                    </span>
                    <a :href="formatScreenshotUrl(selectedBug.screenshot_path)" target="_blank" title="点击查看案发现场高清大图" style="display: block;">
                      <img :src="formatScreenshotUrl(selectedBug.screenshot_path)"
                        style="max-width: 100%; max-height: 420px; object-fit: contain; border-radius: 4px;"
                        alt="缺陷案发现场截图">
                    </a>
                    <div style="font-size: 10px; color: var(--text-muted); margin-top: 6px; font-family: monospace; word-break: break-all;">
                      {{ formatScreenshotUrl(selectedBug.screenshot_path) }}
                    </div>
                  </div>

                </div>

                <!-- 单图降级模式 -->
                <div v-else
                  style="text-align: center; background: #05070d; border-radius: 8px; padding: 10px; border: 1px solid var(--border-color);">

                  <a :href="formatScreenshotUrl(selectedBug.screenshot_path || selectedBug.before_screenshot_path)" target="_blank" title="点击查看大图">

                    <img :src="formatScreenshotUrl(selectedBug.screenshot_path || selectedBug.before_screenshot_path)"
                      style="max-width: 100%; max-height: 520px; object-fit: contain; border-radius: 6px;"
                      alt="缺陷案发现场截图">

                  </a>

                  <div style="font-size: 11px; color: var(--text-muted); margin-top: 6px; font-family: monospace;">

                    {{ formatScreenshotUrl(selectedBug.screenshot_path || selectedBug.before_screenshot_path) }} (点击可在新标签页查看原始高清大图)

                  </div>

                </div>

              </div>

              <!-- 历史复现时间轴轨迹 (按时间倒序展开最近复现记录) -->
              <div class="form-group" v-if="selectedBug.recurrence_history && selectedBug.recurrence_history.length">
                <label class="form-label" style="display: flex; justify-content: space-between; align-items: center;">
                  <span>🕒 历史复现轨迹时间轴 (近 {{ selectedBug.recurrence_history.length }} 次)</span>
                  <span style="font-size: 11px; color: var(--text-muted);">累计复现 {{ selectedBug.occurrences }} 次</span>
                </label>
                <div style="background: #0b1120; border: 1px solid var(--border-color); border-radius: 6px; padding: 12px; max-height: 240px; overflow-y: auto;">
                  <div v-for="(h, idx) in selectedBug.recurrence_history.slice().reverse()" :key="idx" 
                       style="border-left: 2px solid #00d2ff; padding-left: 10px; margin-bottom: 12px; position: relative;">
                    <div style="font-size: 12px; color: #94a3b8; display: flex; justify-content: space-between;">
                      <span style="color: #38bdf8; font-weight: bold;">批次: {{ h.run_id }}</span>
                      <span>{{ h.timestamp }}</span>
                    </div>
                    <div style="font-size: 12px; color: #e2e8f0; margin-top: 3px;" v-if="h.step">
                      <strong>步骤:</strong> {{ h.step }}
                    </div>
                    <div style="font-size: 11px; color: #f87171; margin-top: 2px; word-break: break-all;" v-if="h.actual_error">
                      <strong>报错:</strong> {{ h.actual_error.length > 200 ? h.actual_error.substring(0, 200) + '...' : h.actual_error }}
                    </div>
                    <div style="margin-top: 4px; display: flex; gap: 12px;" v-if="h.before_screenshot || h.screenshot">
                      <a v-if="h.before_screenshot" :href="formatScreenshotUrl(h.before_screenshot)" target="_blank" style="font-size: 11px; color: #34d399; text-decoration: underline;">
                        🖼️ 操作前快照
                      </a>
                      <a v-if="h.screenshot" :href="formatScreenshotUrl(h.screenshot)" target="_blank" style="font-size: 11px; color: #38bdf8; text-decoration: underline;">
                        🖼️ 案发现场快照
                      </a>
                    </div>
                  </div>
                </div>
              </div>

              <div style="display: flex; justify-content: flex-end; gap: 10px; margin-top: 20px;">

                <button class="btn btn-secondary" @click="selectedBug = null">关闭</button>

                <button class="btn btn-secondary" style="border-color: #00d2ff; color: #00d2ff;"
                  @click="openEditBugModal(selectedBug)">

                  ✏️ 编辑缺陷属性

                </button>

                <button v-if="!selectedBug.zentao_id" class="btn btn-primary" :disabled="selectedBug._syncing"
                  @click="syncZenTao(selectedBug)">
                  {{ selectedBug._syncing ? '正在提交至禅道...' : '提交至禅道' }}
                </button>

              </div>

            </div>

          </div>



          <!-- 禅道提单预览与微调弹窗 -->
          <div class="modal-overlay" v-if="zentaoPreviewVisible" style="z-index: 1200;" @click.self="closeZentaoPreview">
            <div class="modal-content" style="width: min(1240px, 96vw); max-width: 96vw; max-height: 92vh; display: flex; flex-direction: column; padding: 0; overflow: hidden;">
              <div class="modal-header" style="padding: 16px 22px; border-bottom: 1px solid rgba(148, 163, 184, 0.16); margin-bottom: 0; flex-shrink: 0;">
                <div style="display: flex; align-items: center; gap: 10px; flex-wrap: wrap;">
                  <h3 style="margin: 0; display: flex; align-items: center; gap: 8px;">
                    <span>📤 禅道提单预览与微调</span>
                    <code style="background: rgba(56, 189, 248, 0.14); color: #38bdf8; padding: 2px 8px; border-radius: 4px; font-size: 13px;">{{ zentaoPreviewForm.bug_id }}</code>
                  </h3>
                  <span v-if="zentaoPreviewForm.app_name" class="badge" style="background: rgba(99, 102, 241, 0.18); color: #a5b4fc; border: 1px solid rgba(99, 102, 241, 0.35);">
                    {{ zentaoPreviewForm.app_name }}
                  </span>
                  <span class="badge" style="background: rgba(16, 185, 129, 0.16); color: #34d399; border: 1px solid rgba(16, 185, 129, 0.35);">
                    状态: {{ zentaoPreviewForm.status_label || '激活' }}
                  </span>
                  <span v-if="zentaoPreviewMetadataLoading" style="font-size: 12px; color: #38bdf8;">⏳ 正在同步禅道级联字典...</span>
                </div>
                <button class="modal-close" @click="closeZentaoPreview">&times;</button>
              </div>

              <div style="padding: 18px 22px; overflow-y: auto; overflow-x: hidden; flex: 1;">
                <div v-if="zentaoPreviewLoading" style="padding: 60px 20px; text-align: center; color: #94a3b8;">
                  <div style="font-size: 28px; margin-bottom: 10px;">⏳</div>
                  <div>正在实时连接禅道拉取项目、执行、模块、最近构建版本及成员字典...</div>
                </div>

                <div v-else-if="zentaoPreviewError" style="padding: 20px; background: rgba(239, 68, 68, 0.12); border: 1px solid rgba(239, 68, 68, 0.35); border-radius: 8px; color: #fca5a5;">
                  ⚠️ {{ zentaoPreviewError }}
                </div>

                <div v-else>
                  <div v-if="zentaoPreviewMeta.warning" style="margin-bottom: 14px; padding: 8px 12px; background: rgba(245, 158, 11, 0.12); border: 1px solid rgba(245, 158, 11, 0.35); border-radius: 6px; color: #fcd34d; font-size: 12px;">
                    ⚠️ {{ zentaoPreviewMeta.warning }}
                  </div>

                  <div class="zentao-preview-layout">
                    <!-- 左侧：标题与重现步骤富文本预览 -->
                    <div style="min-width: 0;">
                      <div class="form-group">
                        <label class="form-label">缺陷标题 <span style="color: #f87171;">*</span></label>
                        <input type="text" class="form-control" style="width: 100%; box-sizing: border-box;" v-model="zentaoPreviewForm.title" placeholder="请输入提交至禅道的缺陷标题" />
                      </div>

                      <div class="form-group" style="margin-bottom: 0;">
                        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
                          <label class="form-label" style="margin: 0;">重现步骤 &amp; 案发现场详单</label>
                          <div style="display: flex; gap: 6px;">
                            <button type="button" class="btn btn-secondary"
                              :style="zentaoPreviewTab === 'preview' ? 'padding: 3px 10px; font-size: 12px; border-color: #38bdf8; color: #38bdf8; background: rgba(56, 189, 248, 0.12);' : 'padding: 3px 10px; font-size: 12px;'"
                              @click="zentaoPreviewTab = 'preview'">
                              👁️ 禅道效果预览
                            </button>
                            <button type="button" class="btn btn-secondary"
                              :style="zentaoPreviewTab === 'html' ? 'padding: 3px 10px; font-size: 12px; border-color: #38bdf8; color: #38bdf8; background: rgba(56, 189, 248, 0.12);' : 'padding: 3px 10px; font-size: 12px;'"
                              @click="zentaoPreviewTab = 'html'">
                              📝 HTML 源码微调
                            </button>
                          </div>
                        </div>

                        <div v-if="zentaoPreviewTab === 'preview'"
                          class="zentao-steps-preview"
                          v-html="zentaoPreviewForm.steps_html">
                        </div>

                        <textarea v-else class="form-control" v-model="zentaoPreviewForm.steps_html" rows="18"
                          style="width: 100%; box-sizing: border-box; font-family: monospace; font-size: 12px; line-height: 1.5; min-height: 420px;"></textarea>
                      </div>
                    </div>

                    <!-- 右侧：禅道结构化属性 -->
                    <div class="zentao-preview-sidebar">
                      <div style="font-size: 13px; font-weight: 700; color: #e2e8f0; margin-bottom: 12px; padding-bottom: 8px; border-bottom: 1px solid rgba(148, 163, 184, 0.14);">
                        📋 基本信息 &amp; 项目/迭代归属
                      </div>

                      <div class="grid-2" style="gap: 10px;">
                        <div class="form-group" style="margin-bottom: 10px; min-width: 0;">
                          <label class="form-label">所属产品</label>
                          <select class="form-control" v-model.number="zentaoPreviewForm.product_id" @change="onZentaoCascadedChange('product')">
                            <option v-for="p in zentaoPreviewMeta.options.products" :key="p.id" :value="Number(p.id)">
                              {{ p.name }} (#{{ p.id }})
                            </option>
                            <option v-if="!zentaoPreviewMeta.options.products.length" :value="zentaoPreviewForm.product_id">
                              产品 #{{ zentaoPreviewForm.product_id }}
                            </option>
                          </select>
                        </div>

                        <div class="form-group" style="margin-bottom: 10px; min-width: 0;">
                          <label class="form-label">所属模块</label>
                          <select class="form-control" v-model.number="zentaoPreviewForm.module_id">
                            <option v-for="m in zentaoPreviewMeta.options.modules" :key="m.id" :value="Number(m.id)">
                              {{ m.name }}
                            </option>
                            <option v-if="!zentaoPreviewMeta.options.modules.length" :value="0">/</option>
                          </select>
                        </div>
                      </div>

                      <div class="grid-2" style="gap: 10px;">
                        <div class="form-group" style="margin-bottom: 10px; min-width: 0;">
                          <label class="form-label">所属项目</label>
                          <select class="form-control" v-model.number="zentaoPreviewForm.project_id" @change="onZentaoCascadedChange('project')">
                            <option v-for="p in zentaoPreviewMeta.options.projects" :key="p.id" :value="Number(p.id)">
                              {{ p.name }} (#{{ p.id }})
                            </option>
                            <option v-if="!zentaoPreviewMeta.options.projects.length" :value="zentaoPreviewForm.project_id">
                              项目 #{{ zentaoPreviewForm.project_id }}
                            </option>
                          </select>
                        </div>

                        <div class="form-group" style="margin-bottom: 10px; min-width: 0;">
                          <label class="form-label">所属执行</label>
                          <select class="form-control" v-model.number="zentaoPreviewForm.execution_id">
                            <option :value="0">不关联执行</option>
                            <option v-for="e in zentaoPreviewMeta.options.executions" :key="e.id" :value="Number(e.id)">
                              {{ e.name }} (#{{ e.id }})
                            </option>
                          </select>
                        </div>
                      </div>

                      <div class="form-group" style="margin-bottom: 10px;">
                        <div style="display: flex; justify-content: space-between; align-items: center; gap: 8px; margin-bottom: 4px;">
                          <label class="form-label" style="margin: 0; white-space: nowrap;">影响版本 <span style="color: #38bdf8; font-weight: 400; font-size: 11px;">(默认最近2条: UE+Web)</span></label>
                          <span style="font-size: 11px; color: #94a3b8; white-space: nowrap;">已选 {{ zentaoPreviewForm.opened_build.length }} 项</span>
                        </div>
                        <div style="background: #0b1220; border: 1px solid rgba(148, 163, 184, 0.2); border-radius: 6px; padding: 6px 8px; max-height: 138px; overflow-y: auto; display: flex; flex-direction: column; gap: 4px;">
                          <label v-for="b in zentaoPreviewMeta.options.builds" :key="b.id"
                            style="display: flex; align-items: center; gap: 8px; padding: 4px 6px; border-radius: 4px; cursor: pointer; font-size: 12px; min-width: 0;"
                            :style="zentaoPreviewForm.opened_build.includes(String(b.id)) ? 'background: rgba(56, 189, 248, 0.14); color: #f8fafc;' : 'color: #cbd5e1;'">
                            <input type="checkbox" :checked="zentaoPreviewForm.opened_build.includes(String(b.id))" @change="toggleZentaoBuild(b.id)" />
                            <span v-if="b.tag === 'web'" style="background: rgba(59, 130, 246, 0.22); color: #60a5fa; padding: 1px 5px; border-radius: 3px; font-size: 10px; font-weight: 700; flex-shrink: 0;">WEB</span>
                            <span v-else-if="b.tag === 'ue'" style="background: rgba(168, 85, 247, 0.22); color: #c084fc; padding: 1px 5px; border-radius: 3px; font-size: 10px; font-weight: 700; flex-shrink: 0;">UE</span>
                            <span v-else-if="b.tag === 'trunk'" style="background: rgba(148, 163, 184, 0.2); color: #cbd5e1; padding: 1px 5px; border-radius: 3px; font-size: 10px; flex-shrink: 0;">主干</span>
                            <span style="flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;" :title="b.name">{{ b.name }}</span>
                            <span v-if="b.date" style="font-size: 11px; color: #64748b; font-family: monospace; flex-shrink: 0;">{{ b.date }}</span>
                          </label>
                        </div>
                      </div>

                      <div class="grid-2" style="gap: 10px;">
                        <div class="form-group" style="margin-bottom: 10px; min-width: 0;">
                          <label class="form-label" style="white-space: nowrap;">Bug 类型</label>
                          <select class="form-control" v-model="zentaoPreviewForm.type">
                            <option v-for="t in zentaoPreviewMeta.options.bug_types" :key="t.id" :value="t.id">
                              {{ t.name }}
                            </option>
                          </select>
                        </div>

                        <div class="form-group" style="margin-bottom: 10px; min-width: 0;">
                          <label class="form-label" style="white-space: nowrap;">严重程度</label>
                          <select class="form-control" v-model.number="zentaoPreviewForm.severity">
                            <option :value="1">1 - 致命 (Fatal)</option>
                            <option :value="2">2 - 严重 (Critical)</option>
                            <option :value="3">3 - 一般 (Normal)</option>
                            <option :value="4">4 - 轻微 (Minor)</option>
                          </select>
                        </div>
                      </div>

                      <div class="grid-2" style="gap: 10px;">
                        <div class="form-group" style="margin-bottom: 10px; min-width: 0;">
                          <label class="form-label" style="white-space: nowrap;">优先级</label>
                          <select class="form-control" v-model.number="zentaoPreviewForm.pri">
                            <option :value="1">1 - 最高</option>
                            <option :value="2">2 - 高</option>
                            <option :value="3">3 - 中</option>
                            <option :value="4">4 - 低</option>
                          </select>
                        </div>

                        <div class="form-group" style="margin-bottom: 10px; min-width: 0;">
                          <label class="form-label" style="white-space: nowrap;">截止日期 <span style="font-size: 11px; color: #94a3b8;">(+7天)</span></label>
                          <input type="date" class="form-control" v-model="zentaoPreviewForm.deadline" />
                        </div>
                      </div>

                      <div class="form-group" style="margin-bottom: 10px;">
                        <label class="form-label">指派给</label>
                        <el-select
                          v-model="zentaoPreviewForm.assigned_to"
                          filterable
                          :teleported="false"
                          placeholder="输入姓名或账号搜索..."
                          style="width: 100%;"
                        >
                          <el-option-group label="常用分流责任人">
                            <el-option
                              v-for="u in zentaoPreviewMeta.options.users.filter(x => ['chenyixiong', 'meibenxia', 'liyuncong', 'jinzhengwu', 'tongjiabao'].includes(x.account))"
                              :key="'core-' + u.account"
                              :label="`${u.realname} (${u.account})`"
                              :value="u.account"
                            />
                          </el-option-group>
                          <el-option-group label="禅道全部成员">
                            <el-option
                              v-for="u in zentaoPreviewMeta.options.users.filter(x => !['chenyixiong', 'meibenxia', 'liyuncong', 'jinzhengwu', 'tongjiabao'].includes(x.account))"
                              :key="'all-' + u.account"
                              :label="`${u.realname} (${u.account})`"
                              :value="u.account"
                            />
                          </el-option-group>
                        </el-select>
                        <div v-if="zentaoPreviewForm.assignee_reason" style="font-size: 11px; color: #38bdf8; margin-top: 4px;">
                          🤖 AI 分流依据: {{ zentaoPreviewForm.assignee_reason }}
                        </div>
                      </div>

                      <div class="grid-2" style="gap: 10px;">
                        <div class="form-group" style="margin-bottom: 0; min-width: 0;">
                          <label class="form-label">操作系统</label>
                          <input type="text" class="form-control" v-model="zentaoPreviewForm.os" />
                        </div>
                        <div class="form-group" style="margin-bottom: 0; min-width: 0;">
                          <label class="form-label">浏览器</label>
                          <input type="text" class="form-control" v-model="zentaoPreviewForm.browser" />
                        </div>
                      </div>
                    </div>
                  </div>
                </div>
              </div>

              <div style="padding: 14px 22px; border-top: 1px solid rgba(148, 163, 184, 0.16); display: flex; justify-content: flex-end; gap: 10px; flex-shrink: 0; background: rgba(15, 23, 42, 0.45);">
                <button class="btn btn-secondary" :disabled="zentaoPreviewSubmitting" @click="closeZentaoPreview">取消</button>
                <button class="btn btn-primary"
                  :disabled="zentaoPreviewSubmitting || zentaoPreviewLoading || !!zentaoPreviewError"
                  @click="confirmSyncZenTao">
                  {{ zentaoPreviewSubmitting ? '⏳ 正在提交至禅道...' : '🚀 确认提交至禅道' }}
                </button>
              </div>
            </div>
          </div>


          <!-- 缺陷在线编辑弹窗 -->

          <div class="modal-overlay" v-if="editingBug" @click.self="editingBug = null">

            <div class="modal-content">

              <div class="modal-header">

                <h3>✏️ 编辑缺陷属性 [{{ editForm.id }}]</h3>

                <button class="modal-close" @click="editingBug = null">&times;</button>

              </div>



              <div class="form-group">

                <label class="form-label">缺陷标题</label>

                <input type="text" class="form-control" v-model="editForm.title" placeholder="请输入缺陷摘要标题">

              </div>



              <div class="grid-2">

                <div class="form-group">

                  <label class="form-label">严重程度</label>

                  <select class="form-control" v-model="editForm.severity">

                    <option value="High">High (高)</option>

                    <option value="Medium">Medium (中)</option>

                    <option value="Low">Low (低)</option>

                  </select>

                </div>

                <div class="form-group">

                  <label class="form-label">缺陷状态</label>

                  <select class="form-control" v-model="editForm.status">

                    <option value="激活">激活 (Open)</option>

                    <option value="已提单">已提单 (Submitted)</option>

                    <option value="已解决">已解决 (Resolved)</option>

                    <option value="误报">误报 (False Positive)</option>

                    <option value="已关闭">已关闭 (Closed)</option>

                  </select>

                </div>

              </div>



              <div class="grid-2">

                <div class="form-group">

                  <label class="form-label">责任人 (支持输入姓名/账号模糊搜索)</label>

                  <el-select
                    v-model="editForm.assignee"
                    filterable
                    allow-create
                    default-first-option
                    :teleported="false"
                    placeholder="输入姓名或账号搜索..."
                    style="width: 100%;"
                  >
                    <el-option-group label="常用分流责任人">
                      <el-option
                        v-for="u in zentaoUsers.filter(x => ['chenyixiong', 'meibenxia', 'liyuncong', 'jinzhengwu', 'tongjiabao'].includes(x.account))"
                        :key="'edit-core-' + u.account"
                        :label="`${u.realname} (${u.account})`"
                        :value="u.realname"
                      />
                    </el-option-group>
                    <el-option-group label="禅道全部成员">
                      <el-option
                        v-for="u in zentaoUsers.filter(x => !['chenyixiong', 'meibenxia', 'liyuncong', 'jinzhengwu', 'tongjiabao'].includes(x.account))"
                        :key="'edit-all-' + u.account"
                        :label="`${u.realname} (${u.account})`"
                        :value="u.realname"
                      />
                    </el-option-group>
                  </el-select>

                </div>

                <div class="form-group">

                  <label class="form-label">关联禅道 Bug 单号</label>

                  <input type="text" class="form-control" v-model="editForm.zentao_id" placeholder="如 1188 (可手动补录或修改)">

                </div>

              </div>



              <div class="form-group">

                <label class="form-label">业务页面层级路径 (UI Path)</label>

                <input type="text" class="form-control" v-model="editForm.ui_path" placeholder="如 首页 > 矿山简介 > 生产指标">

              </div>



              <div class="form-group">

                <label class="form-label">AI 初诊与排查指引说明</label>

                <textarea class="form-control" rows="5" v-model="editForm.analysis_notes"
                  placeholder="输入根因分析或开发排查指引..."></textarea>

              </div>



              <div class="form-group">

                <label class="form-label">📌 备注 / 关闭说明 (非必填)</label>

                <textarea class="form-control" rows="3" v-model="editForm.remark"
                  placeholder="如：核验无误非Bug、关闭原因或补充排查备注..."></textarea>

              </div>



              <div style="display: flex; justify-content: flex-end; gap: 10px; margin-top: 20px;">

                <button class="btn btn-secondary" @click="editingBug = null">取消</button>

                <button class="btn btn-primary" @click="submitBugEdit">

                  💾 保存并多端同步

                </button>

              </div>

            </div>

          </div>

        <!-- 🌐 运行环境与配置基线快照弹窗 (env_info.json) -->
        <div class="modal-overlay" v-if="selectedEnvInfo" @click.self="selectedEnvInfo = null">
          <div class="modal-content" style="max-width: 820px;">
            <div class="modal-header">
              <div>
                <h3 style="display: flex; align-items: center; gap: 10px;">
                  <span>🌐 巡检任务运行环境与配置基线</span>
                  <span class="badge badge-low" style="font-family: monospace;">{{ selectedEnvInfo.task_id }}</span>
                </h3>
              </div>
              <button class="modal-close" @click="selectedEnvInfo = null">&times;</button>
            </div>

            <div v-if="envInfoLoading" style="text-align: center; padding: 40px; color: #00d2ff;">
              ⚡ 正在读取该批次的环境基线快照...
            </div>

            <div v-else-if="!selectedEnvInfo.exists" style="text-align: center; padding: 36px 20px;">
              <div style="font-size: 36px; margin-bottom: 12px;">📁</div>
              <div style="font-size: 15px; font-weight: 600; color: #cbd5e1; margin-bottom: 6px;">
                {{ selectedEnvInfo.message || '未采集到该批次的环境基线快照记录' }}
              </div>
              <div style="font-size: 12px; color: var(--text-muted);">
                该运行目录中未发现 env_info.json，可能是早期版本运行或执行被强制中断。
              </div>
            </div>

            <div v-else>
              <!-- 顶部视图切换工具栏 -->
              <div
                style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px; border-bottom: 1px solid #1a253c; padding-bottom: 10px;">
                <div style="display: flex; gap: 8px;">
                  <button class="btn" :class="envInfoViewMode === 'card' ? 'btn-primary' : 'btn-secondary'"
                    style="padding: 4px 12px; font-size: 12px;" @click="envInfoViewMode = 'card'">
                    📋 结构化卡片
                  </button>
                  <button class="btn" :class="envInfoViewMode === 'json' ? 'btn-primary' : 'btn-secondary'"
                    style="padding: 4px 12px; font-size: 12px;" @click="envInfoViewMode = 'json'">
                    💻 原始 JSON
                  </button>
                </div>
                <div>
                  <button class="btn btn-secondary" style="padding: 4px 12px; font-size: 12px;"
                    @click="copyEnvInfoJson">
                    📋 复制完整 JSON
                  </button>
                </div>
              </div>

              <!-- 结构化卡片视图 -->
              <div v-if="envInfoViewMode === 'card'">
                <div class="grid-2" style="margin-bottom: 12px;">
                  <div class="form-group"
                    style="background: rgba(13, 20, 36, 0.6); padding: 12px; border-radius: 6px; border: 1px solid #1a253c; margin-bottom: 0;">
                    <label class="form-label" style="color: #00d2ff; display: flex; justify-content: space-between; align-items: center;">
                      <span>🏢 目标系统与启动器</span>
                      <span v-if="selectedEnvInfo.env_info.launcher_version" class="badge" style="background: rgba(0, 210, 255, 0.15); color: #00d2ff; font-weight: bold; font-size: 11px;">
                        版本: {{ selectedEnvInfo.env_info.launcher_version }}
                      </span>
                    </label>
                    <div style="font-weight: 600; font-size: 14px; display: flex; align-items: center; gap: 8px;">
                      <span>{{ selectedEnvInfo.env_info.app_name || '-' }}</span>
                      <span v-if="selectedEnvInfo.env_info.machine_id" style="font-size: 11px; color: #8b9bb4; font-weight: normal; font-family: monospace;">
                        (设备ID: {{ selectedEnvInfo.env_info.machine_id }})
                      </span>
                    </div>
                  </div>
                  <div class="form-group"
                    style="background: rgba(13, 20, 36, 0.6); padding: 12px; border-radius: 6px; border: 1px solid #1a253c; margin-bottom: 0;">
                    <label class="form-label" style="color: #00e676;">🌍 部署环境代号</label>
                    <div style="font-weight: 600; font-size: 14px;">{{ selectedEnvInfo.env_info.env_name ||
                      selectedEnvInfo.env_info.env_key || '-' }}</div>
                  </div>
                </div>

                <!-- 🎙️ 语音播报模块 (TTS) 与 NATS 告警消息流 -->
                <div class="form-group"
                  style="background: rgba(13, 20, 36, 0.6); padding: 12px; border-radius: 6px; border: 1px solid #1a253c; margin-bottom: 12px;">
                  <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
                    <label class="form-label" style="color: #a78bfa; margin-bottom: 0; display: flex; align-items: center; gap: 6px;">
                      <span>🎙️ 语音播报模块 (TTS) 与 NATS 告警网关</span>
                    </label>
                    <div>
                      <span v-if="selectedEnvInfo.env_info.tts_enabled" class="badge badge-success" style="font-size: 11px;">
                        🟢 TTS 已启用 (监听并语音播报)
                      </span>
                      <span v-else class="badge" style="background: rgba(100, 116, 139, 0.2); color: #94a3b8; font-size: 11px;">
                        ⚪ TTS 未启用
                      </span>
                    </div>
                  </div>

                  <div style="display: grid; grid-template-columns: 1fr; gap: 8px; font-size: 12px;">
                    <div>
                      <span style="color: #8b9bb4;">📡 NATS 网关地址: </span>
                      <span style="font-family: monospace; color: #cbd5e1; word-break: break-all;">
                        {{ selectedEnvInfo.env_info.nats_ws_url || '未配置' }}
                      </span>
                    </div>
                    <div v-if="selectedEnvInfo.env_info.nats_subjects && selectedEnvInfo.env_info.nats_subjects.length > 0">
                      <span style="color: #8b9bb4;">🎯 订阅主题 (Subjects): </span>
                      <span v-for="subj in selectedEnvInfo.env_info.nats_subjects" :key="subj" 
                        class="badge" style="background: rgba(167, 139, 250, 0.15); color: #c4b5fd; font-family: monospace; font-size: 11px; margin-right: 6px;">
                        {{ subj }}
                      </span>
                    </div>
                    <div v-if="selectedEnvInfo.env_info.nats_trace_id">
                      <span style="color: #8b9bb4;">🔍 Trace ID: </span>
                      <span style="font-family: monospace; color: #cbd5e1;">{{ selectedEnvInfo.env_info.nats_trace_id }}</span>
                    </div>
                  </div>
                </div>

                <div class="form-group"
                  style="background: rgba(13, 20, 36, 0.6); padding: 12px; border-radius: 6px; border: 1px solid #1a253c; margin-bottom: 12px;">
                  <label class="form-label" style="color: #ffb300;">🌐 2D 前端发布包版本路径 (big_screen_dist)</label>
                  <div
                    style="font-family: monospace; font-size: 12px; word-break: break-all; color: #cbd5e1; background: #05070d; padding: 6px 10px; border-radius: 4px;">
                    {{ selectedEnvInfo.env_info.big_screen_dist || '未配置' }}
                  </div>
                </div>

                <div class="form-group"
                  style="background: rgba(13, 20, 36, 0.6); padding: 12px; border-radius: 6px; border: 1px solid #1a253c; margin-bottom: 12px;">
                  <label class="form-label" style="color: #ff9100;">🎮 3D UE 孪生工程包版本路径 (ue_dist)</label>
                  <div
                    style="font-family: monospace; font-size: 12px; word-break: break-all; color: #cbd5e1; background: #05070d; padding: 6px 10px; border-radius: 4px;">
                    {{ selectedEnvInfo.env_info.ue_dist || '未配置' }}
                  </div>
                </div>

                <div class="grid-2" style="margin-bottom: 12px;">
                  <div class="form-group"
                    style="background: rgba(13, 20, 36, 0.6); padding: 12px; border-radius: 6px; border: 1px solid #1a253c; margin-bottom: 0;">
                    <label class="form-label" style="color: #00d2ff;">🔗 N+1 业务后端接口基地址</label>
                    <div style="font-family: monospace; font-size: 12px; word-break: break-all; color: #cbd5e1;">
                      {{ selectedEnvInfo.env_info.nplusone_url || '-' }}
                    </div>
                  </div>
                  <div class="form-group"
                    style="background: rgba(13, 20, 36, 0.6); padding: 12px; border-radius: 6px; border: 1px solid #1a253c; margin-bottom: 0;">
                    <label class="form-label" style="color: #00e676;">📺 像素流送端口</label>
                    <div style="font-family: monospace; font-size: 13px; font-weight: 600; color: #00e676;">
                      {{ selectedEnvInfo.env_info.start_port || '9527' }}
                    </div>
                  </div>
                </div>

                <div class="form-group"
                  style="background: rgba(13, 20, 36, 0.6); padding: 12px; border-radius: 6px; border: 1px solid #1a253c; margin-bottom: 0;">
                  <label class="form-label" style="color: var(--text-muted);">⚙️ 启动器配置文件路径</label>
                  <div style="font-family: monospace; font-size: 11px; word-break: break-all; color: #8b9bb4;">
                    {{ selectedEnvInfo.env_info.config_file || '-' }}
                  </div>
                </div>
              </div>

              <!-- 原始 JSON 视图 -->
              <div v-else>
                <pre
                  style="background: #05070d; border: 1px solid #1a253c; border-radius: 6px; padding: 14px; font-family: monospace; font-size: 12px; color: #00e676; max-height: 400px; overflow-y: auto;">{{ selectedEnvInfo.raw_json }}</pre>
              </div>
            </div>
          </div>
        </div>

        <!-- 📄 用例 YAML 源码预览弹窗 -->
        <div class="modal-overlay" v-if="previewingCase" @click.self="previewingCase = null">
          <div class="modal-content" style="max-width: 860px; max-height: 85vh; display: flex; flex-direction: column;">
            <div class="modal-header">
              <div>
                <h3 style="display: flex; align-items: center; gap: 10px;">
                  <span>📄 用例 YAML 脚本预览</span>
                  <span class="badge badge-low" style="font-family: monospace;">{{ previewingCase.filename }}</span>
                </h3>
                <div style="font-size: 11px; color: var(--text-muted); margin-top: 4px;">
                  {{ previewingCase.path }} (共 {{ previewingCase.steps_count }} 步)
                </div>
              </div>
              <button class="modal-close" @click="previewingCase = null">&times;</button>
            </div>

            <div style="flex: 1; overflow-y: auto; margin: 12px 0;">
              <div v-if="previewCaseLoading" style="text-align: center; padding: 40px; color: #00d2ff;">
                ⚡ 正在读取 YAML 源码...
              </div>
              <pre v-else
                style="background: #05070d; border: 1px solid #1a253c; border-radius: 6px; padding: 16px; font-family: monospace; font-size: 12px; line-height: 1.6; color: #cbd5e1; margin: 0; white-space: pre-wrap; word-break: break-all;">{{ previewCaseContent }}</pre>
            </div>

            <div
              style="display: flex; justify-content: space-between; align-items: center; border-top: 1px solid #1a253c; padding-top: 12px;">
              <div>
                <button class="btn btn-secondary" style="padding: 6px 14px; font-size: 12px;" @click="copyCaseYaml">
                  📋 复制 YAML 全文
                </button>
              </div>
              <div style="display: flex; gap: 10px;">
                <button class="btn btn-secondary" @click="previewingCase = null">关闭</button>
                <button class="btn btn-primary" @click="runCaseInDashboard(previewingCase)">
                  🚀 在控制台以此脚本启动测试
                </button>
              </div>
            </div>
          </div>
        </div>

        <!-- 调度入队预约弹窗 (新建调度执行计划) -->
        <div class="modal-overlay" v-if="showEnqueueModal" @click.self="showEnqueueModal = false">
          <div class="modal-content" style="max-width: 600px; padding: 24px;">
            <div class="modal-header" style="border-bottom: 1px solid #1a253c; padding-bottom: 12px; margin-bottom: 16px;">
              <div style="display: flex; gap: 24px; align-items: center;">
                <span style="font-size: 15px; font-weight: 700; cursor: pointer; padding-bottom: 8px; transition: all 0.2s;"
                  :style="scheduleModalTab === 'basic' ? 'color: #00d2ff; border-bottom: 2px solid #00d2ff;' : 'color: #718096;'"
                  @click="scheduleModalTab = 'basic'">基本配置</span>
                <span style="font-size: 15px; font-weight: 700; cursor: pointer; padding-bottom: 8px; transition: all 0.2s;"
                  :style="scheduleModalTab === 'advanced' ? 'color: #00d2ff; border-bottom: 2px solid #00d2ff;' : 'color: #718096;'"
                  @click="scheduleModalTab = 'advanced'">高级配置</span>
              </div>
              <button class="modal-close" @click="showEnqueueModal = false">&times;</button>
            </div>

            <!-- TAB 1: 基本配置 -->
            <div v-show="scheduleModalTab === 'basic'">
              <!-- 1. 任务名称 与 优先级 -->
              <div style="display: flex; gap: 14px; margin-bottom: 14px; align-items: center;">
                <label style="width: 72px; font-size: 13px; color: var(--text-muted); text-align: right; flex-shrink: 0;">任务名称:</label>
                <input type="text" class="form-control" v-model="scheduleForm.name" placeholder="请输入调度计划名称..." style="flex: 1;">
                <label style="font-size: 13px; color: var(--text-muted); margin-left: 8px; flex-shrink: 0;">优先级:</label>
                <select class="form-control" v-model.number="scheduleForm.priority" style="width: 100px; flex-shrink: 0;">
                  <option :value="1">紧急 (P1)</option>
                  <option :value="2">高 (P2)</option>
                  <option :value="3">普通 (P3)</option>
                  <option :value="4">低 (P4)</option>
                </select>
              </div>

              <!-- 2. 目标矿山应用 -->
              <div style="display: flex; gap: 14px; margin-bottom: 14px; align-items: center;">
                <label style="width: 72px; font-size: 13px; color: var(--text-muted); text-align: right; flex-shrink: 0;">目标应用:</label>
                <select class="form-control" v-model="scheduleForm.app_name" @change="onScheduleAppChange" style="flex: 1;">
                  <option v-for="a in options.apps" :key="a.key" :value="a.key">
                    {{ a.name }}
                  </option>
                </select>
              </div>

              <!-- 3. 流程名称 (预设巡检任务模板) -->
              <div style="display: flex; gap: 14px; margin-bottom: 14px; align-items: center;">
                <label style="width: 72px; font-size: 13px; color: var(--text-muted); text-align: right; flex-shrink: 0;">流程名称:</label>
                <select class="form-control" v-model="scheduleForm.preset_id" @change="onSchedulePresetChange" style="flex: 1;">
                  <option value="" disabled>-- 请选择属于该应用的巡检任务模板 --</option>
                  <option v-for="p in filteredSchedulePresets" :key="p.id" :value="p.id">
                    [{{ getPresetModeLabel(p) }}] {{ p.title }}
                  </option>
                </select>
              </div>

              <!-- 4. 执行日期 (开始日期 至 结束日期) -->
              <div style="display: flex; gap: 14px; margin-bottom: 14px; align-items: center;">
                <label style="width: 72px; font-size: 13px; color: var(--text-muted); text-align: right; flex-shrink: 0;">执行日期:</label>
                <div style="display: flex; align-items: center; gap: 10px; flex: 1;">
                  <input type="date" class="form-control" v-model="scheduleForm.startDate" style="color-scheme: dark; flex: 1;">
                  <span style="color: var(--text-muted); font-size: 13px;">至</span>
                  <input type="date" class="form-control" v-model="scheduleForm.endDate" style="color-scheme: dark; flex: 1;" title="到期后计划自动停止">
                </div>
              </div>

              <!-- 5. 执行时间 (触发时刻 至 时间窗口截止) -->
              <div style="display: flex; gap: 14px; margin-bottom: 16px; align-items: center;">
                <label style="width: 72px; font-size: 13px; color: var(--text-muted); text-align: right; flex-shrink: 0;">执行时间:</label>
                <div style="display: flex; align-items: center; gap: 10px; flex: 1;">
                  <div style="position: relative; flex: 1;">
                    <input type="time" step="1" class="form-control" v-model="scheduleForm.executionTime"
                      style="color-scheme: dark; padding-right: 36px; font-family: monospace;">
                    <button type="button" @click="setCurrentExecutionTime" title="获取系统当前时间"
                      style="position: absolute; right: 8px; top: 50%; transform: translateY(-50%); background: none; border: none; cursor: pointer; font-size: 15px; opacity: 0.85;"
                      onmouseover="this.style.opacity='1'" onmouseout="this.style.opacity='0.85'">
                      🕒
                    </button>
                  </div>
                  <span style="color: var(--text-muted); font-size: 13px;">至</span>
                  <input type="time" step="1" class="form-control" v-model="scheduleForm.endTime"
                    style="color-scheme: dark; flex: 1; font-family: monospace;" title="每日最晚允许执行时间窗口截止">
                </div>
              </div>

              <!-- 6. 模式选择 (单次 / 分钟 / 小时 / 天 / 每周 / 每月) -->
              <div style="display: flex; gap: 14px; margin-bottom: 20px; align-items: flex-start;">
                <label style="width: 72px; font-size: 13px; color: var(--text-muted); text-align: right; flex-shrink: 0; padding-top: 4px;">模式选择:</label>
                <div style="flex: 1; display: flex; gap: 14px;">
                  <!-- 左侧单选按钮组 -->
                  <div style="display: flex; flex-direction: column; gap: 9px; min-width: 90px; padding-top: 4px;">
                    <label style="cursor: pointer; display: flex; align-items: center; gap: 6px; font-size: 13px;">
                      <input type="radio" value="once" v-model="scheduleForm.cron_mode"> 单次
                    </label>
                    <label style="cursor: pointer; display: flex; align-items: center; gap: 6px; font-size: 13px;">
                      <input type="radio" value="minute" v-model="scheduleForm.cron_mode"> 分钟
                    </label>
                    <label style="cursor: pointer; display: flex; align-items: center; gap: 6px; font-size: 13px;">
                      <input type="radio" value="hour" v-model="scheduleForm.cron_mode"> 小时
                    </label>
                    <label style="cursor: pointer; display: flex; align-items: center; gap: 6px; font-size: 13px;">
                      <input type="radio" value="daily" v-model="scheduleForm.cron_mode"> 天
                    </label>
                    <label style="cursor: pointer; display: flex; align-items: center; gap: 6px; font-size: 13px;">
                      <input type="radio" value="weekly" v-model="scheduleForm.cron_mode"> 每周
                    </label>
                    <label style="cursor: pointer; display: flex; align-items: center; gap: 6px; font-size: 13px;">
                      <input type="radio" value="monthly" v-model="scheduleForm.cron_mode"> 每月
                    </label>
                  </div>

                  <!-- 右侧详细规则配置卡片 -->
                  <div style="flex: 1; background: rgba(0, 210, 255, 0.03); border: 1px solid #1a253c; border-radius: 6px; padding: 14px; min-height: 120px; display: flex; align-items: center;">
                    <!-- 分钟模式 -->
                    <div v-if="scheduleForm.cron_mode === 'minute'" style="display: flex; align-items: center; gap: 8px; font-size: 13px;">
                      <span>每</span>
                      <input type="number" min="1" max="1440" class="form-control" v-model.number="scheduleForm.minuteInterval"
                        style="width: 76px; text-align: center; font-weight: 600;">
                      <span>分钟高频巡检一次</span>
                    </div>

                    <!-- 小时模式 -->
                    <div v-else-if="scheduleForm.cron_mode === 'hour'" style="display: flex; align-items: center; gap: 8px; font-size: 13px;">
                      <span>每</span>
                      <input type="number" min="1" max="24" class="form-control" v-model.number="scheduleForm.hourInterval"
                        style="width: 76px; text-align: center; font-weight: 600;">
                      <span>小时定时执行一次</span>
                    </div>

                    <!-- 天模式 -->
                    <div v-else-if="scheduleForm.cron_mode === 'daily'" style="display: flex; align-items: center; gap: 8px; font-size: 13px;">
                      <span>每</span>
                      <input type="number" min="1" max="365" class="form-control" v-model.number="scheduleForm.dailyInterval"
                        style="width: 76px; text-align: center; font-weight: 600;">
                      <span>天在设定时间执行一次</span>
                    </div>

                    <!-- 每周模式 -->
                    <div v-else-if="scheduleForm.cron_mode === 'weekly'" style="display: flex; flex-direction: column; gap: 10px; width: 100%;">
                      <div style="font-size: 13px; color: var(--text-muted);">每周选择执行日（支持多选）：</div>
                      <div style="display: flex; gap: 6px; flex-wrap: wrap;">
                        <label v-for="d in [1,2,3,4,5,6,7]" :key="d"
                          style="cursor: pointer; display: flex; align-items: center; gap: 4px; font-size: 12px; padding: 4px 8px; border-radius: 4px; transition: all 0.2s;"
                          :style="scheduleForm.weeklyDays.includes(d) ? 'background: rgba(0,210,255,0.18); border: 1px solid #00d2ff; color: #00d2ff;' : 'background: rgba(255,255,255,0.03); border: 1px solid #233354; color: #a0aec0;'">
                          <input type="checkbox" :value="d" v-model="scheduleForm.weeklyDays" style="display: none;">
                          <span>周{{ ['一','二','三','四','五','六','日'][d-1] }}</span>
                        </label>
                      </div>
                    </div>

                    <!-- 每月模式 -->
                    <div v-else-if="scheduleForm.cron_mode === 'monthly'" style="display: flex; align-items: center; gap: 8px; font-size: 13px;">
                      <span>每月</span>
                      <input type="number" min="1" max="31" class="form-control" v-model.number="scheduleForm.monthlyDay"
                        style="width: 76px; text-align: center; font-weight: 600;">
                      <span>日自动执行一次</span>
                    </div>

                    <!-- 单次执行 -->
                    <div v-else style="font-size: 13px; color: var(--text-muted); line-height: 1.6;">
                      将在执行日期（<strong>{{ scheduleForm.startDate }}</strong>）的 <strong>{{ scheduleForm.executionTime }}</strong> 执行一次，执行完成后自动归档。
                    </div>
                  </div>
                </div>
              </div>
            </div>

            <!-- TAB 2: 高级配置 -->
            <div v-show="scheduleModalTab === 'advanced'" style="min-height: 260px; padding: 6px 0;">
              <!-- 队列阻塞冲突策略 -->
              <div class="form-group" style="background: rgba(13, 20, 36, 0.6); padding: 14px; border-radius: 6px; border: 1px solid #1a253c; margin-bottom: 14px;">
                <label class="form-label" style="color: #00d2ff; font-weight: 600; margin-bottom: 8px;">⏳ 队列阻塞冲突策略</label>
                <div style="display: flex; flex-direction: column; gap: 8px; font-size: 13px;">
                  <label style="cursor: pointer; display: flex; align-items: center; gap: 8px;">
                    <input type="radio" value="wait" v-model="scheduleForm.conflict_policy">
                    <span><strong>顺延排队（推荐）</strong>：到达触发时刻若前序任务正在运行，自动等待其完成后立即执行</span>
                  </label>
                  <label style="cursor: pointer; display: flex; align-items: center; gap: 8px;">
                    <input type="radio" value="skip" v-model="scheduleForm.conflict_policy">
                    <span><strong>超时跳过</strong>：若到达触发时刻执行器仍在忙或已超过时间窗口，则直接跳过本次执行</span>
                  </label>
                </div>
              </div>

              <!-- 失败自动重试策略 -->
              <div class="form-group" style="background: rgba(13, 20, 36, 0.6); padding: 14px; border-radius: 6px; border: 1px solid #1a253c; margin-bottom: 14px;">
                <label class="form-label" style="color: #ffb300; font-weight: 600; margin-bottom: 8px;">🔁 异常失败重试策略</label>
                <div style="display: flex; gap: 20px; font-size: 13px;">
                  <label style="cursor: pointer; display: flex; align-items: center; gap: 8px;">
                    <input type="radio" :value="0" v-model.number="scheduleForm.auto_retry">
                    <span>不自动重试（默认）</span>
                  </label>
                  <label style="cursor: pointer; display: flex; align-items: center; gap: 8px;">
                    <input type="radio" :value="1" v-model.number="scheduleForm.auto_retry">
                    <span>发生异常自动重试 1 次</span>
                  </label>
                </div>
              </div>

              <!-- 运行环境前置准入校验 -->
              <div class="form-group" style="background: rgba(13, 20, 36, 0.6); padding: 14px; border-radius: 6px; border: 1px solid #1a253c; margin-bottom: 14px;">
                <label class="form-label" style="color: #00e676; font-weight: 600; margin-bottom: 8px;">🛡️ 运行环境前置准入校验</label>
                <div style="display: flex; gap: 20px; font-size: 13px;">
                  <label style="cursor: pointer; display: flex; align-items: center; gap: 8px;">
                    <input type="radio" :value="0" v-model.number="scheduleForm.ignore_env_check">
                    <span>严格校验环境（推荐，拦截错位环境）</span>
                  </label>
                  <label style="cursor: pointer; display: flex; align-items: center; gap: 8px;">
                    <input type="radio" :value="1" v-model.number="scheduleForm.ignore_env_check">
                    <span>跳过环境校验直接运行</span>
                  </label>
                </div>
              </div>
            </div>

            <!-- 底部操作栏: 启用勾选 + 保存 / 取消 -->
            <div style="display: flex; justify-content: space-between; align-items: center; border-top: 1px solid #1a253c; padding-top: 16px; margin-top: 10px;">
              <label style="cursor: pointer; display: flex; align-items: center; gap: 8px; font-size: 13px; font-weight: 600; color: #fff;">
                <input type="checkbox" v-model="scheduleForm.is_active" :true-value="1" :false-value="0" style="width: 16px; height: 16px; cursor: pointer;">
                <span>启用该计划</span>
              </label>

              <div style="display: flex; gap: 10px;">
                <button class="btn btn-secondary" @click="showEnqueueModal = false" style="padding: 6px 16px;">取消</button>
                <button class="btn btn-primary" :disabled="isSubmittingEnqueue" @click="confirmCreateSchedulePlan"
                  style="padding: 6px 20px; background: linear-gradient(135deg, #00d2ff, #0072ff); font-weight: 600;">
                  {{ isSubmittingEnqueue ? '保存中...' : '保存' }}
                </button>
              </div>
            </div>
          </div>
        </div>

    <!-- 📝 自定义巡检任务配置 / 微调弹窗 -->
    <div class="modal-overlay" v-if="taskModalVisible" style="z-index: 9999;" @click.self="taskModalVisible = false">
      <div class="modal-content" style="max-width: 960px; width: 95%; max-height: 90vh; display: flex; flex-direction: column; padding: 0; overflow: hidden; border-radius: 12px; box-shadow: 0 20px 60px rgba(0,0,0,0.8); border: 1px solid #1a253c; background: #0b1120;">
        <!-- 弹窗头部 -->
        <div class="modal-header" style="padding: 16px 24px; border-bottom: 1px solid #1a253c; display: flex; align-items: center; justify-content: space-between; background: #0d1424;">
          <h3 style="font-size: 16px; margin: 0; color: #fff; font-weight: 700; display: flex; align-items: center; gap: 8px;">
            <span>{{ taskForm.preset_id ? '✏️ 微调预设任务' : '📝 新建自定义巡检任务' }}</span>
            <span v-if="taskForm.preset_id" class="badge" style="background: rgba(0, 210, 255, 0.15); color: #00d2ff; font-weight: normal; font-size: 11px;">#{{ taskForm.preset_id }}</span>
          </h3>
          <button type="button" style="background: transparent; border: none; color: #64748b; font-size: 22px; cursor: pointer; line-height: 1;" @click="taskModalVisible = false" title="关闭">&times;</button>
        </div>

        <!-- 弹窗主体 (可滚动) -->
        <div style="flex: 1; overflow-y: auto; padding: 20px 24px;">
          <!-- 当前编辑预设状态提示条 -->
          <div v-if="taskForm.preset_id"
            style="margin-bottom: 16px; background: rgba(0, 210, 255, 0.08); border: 1px solid #00d2ff; padding: 10px 16px; border-radius: 6px; display: flex; justify-content: space-between; align-items: center;">
            <span style="font-size: 13px; color: #00d2ff;">
              📌 正在微调载入的预设: <strong style="color: #fff;">【{{ taskForm.preset_title || taskForm.name }}】</strong>
              <span style="font-size: 11px; color: var(--text-muted); margin-left: 8px;">(ID: {{ taskForm.preset_id }})</span>
            </span>
            <button type="button" class="btn btn-secondary"
              style="padding: 4px 10px; font-size: 12px; border-color: #64748b; color: #cbd5e1;"
              @click="clearLoadedPreset" title="解除当前预设绑定，切换为全新任务配置">
              ✕ 切换为新建空白任务
            </button>
          </div>

          <div class="grid-2">
            <div>
              <div class="form-group">
                <label class="form-label">任务名称</label>
                <input type="text" class="form-control" v-model="taskForm.name" placeholder="请输入本次巡检任务名称">
              </div>

              <div class="form-group">
                <label class="form-label">矿山应用</label>
                <select class="form-control" v-model="taskForm.app_name" @change="changeLiveApp(taskForm.app_name)">
                  <option v-for="app in options.apps" :key="app.key" :value="app.key">
                    {{ app.name }}
                  </option>
                </select>
              </div>

              <div class="form-group">
                <label class="form-label">运行模式</label>
                <select class="form-control" v-model="taskForm.mode">
                  <option v-for="m in options.modes" :key="m.key" :value="m.key">
                    {{ m.name }} - {{ m.desc }}
                  </option>
                </select>
              </div>

              <!-- 自主探索模式 (explore) 专属配置 -->
              <div v-if="taskForm.mode === 'explore'">
                <div class="grid-2">
                  <div class="form-group">
                    <label class="form-label">最大步数限制 (Steps)</label>
                    <input type="number" class="form-control" v-model.number="taskForm.max_steps" min="5" max="3000">
                  </div>
                  <div class="form-group">
                    <label class="form-label">最长运行时间 (分钟)</label>
                    <input type="number" class="form-control" v-model.number="taskForm.max_times" min="1" max="1440">
                  </div>
                </div>

                <div class="form-group" style="display: flex; gap: 20px; align-items: center; margin-top: 10px;">
                  <label style="display: flex; align-items: center; gap: 8px; cursor: pointer; font-size: 13px;">
                    <input type="checkbox" v-model="taskForm.ignore_errors">
                    <span>容错继续 (报错时不阻断流程)</span>
                  </label>
                  <label style="display: flex; align-items: center; gap: 8px; cursor: pointer; font-size: 13px;">
                    <input type="checkbox" v-model="taskForm.reset_memory">
                    <span>重置长期记忆 (从零开始探索)</span>
                  </label>
                </div>
              </div>

              <!-- 全量冒烟巡检模式 (smoke) 专属配置 -->
              <div v-else-if="taskForm.mode === 'smoke'">
                <div class="form-group">
                  <label class="form-label">最长超时时间 (分钟)</label>
                  <input type="number" class="form-control" v-model.number="taskForm.max_times" min="1" max="1440">
                </div>
                <div class="form-group" style="display: flex; gap: 20px; align-items: center; margin-top: 10px;">
                  <label style="display: flex; align-items: center; gap: 8px; cursor: pointer; font-size: 13px;">
                    <input type="checkbox" v-model="taskForm.ignore_errors">
                    <span>容错继续 (单个页面巡检遇到异常时不阻断剩余菜单)</span>
                  </label>
                </div>
              </div>

              <!-- 确定性用例模式 (case) 专属配置 -->
              <div v-else-if="taskForm.mode === 'case'">
                <div class="form-group">
                  <label class="form-label">YAML 用例脚本选择</label>
                  <select class="form-control" v-model="taskForm.case_path">
                    <option
                      v-if="taskForm.case_path && !(options.yaml_cases || []).some(item => item.path === taskForm.case_path)"
                      :value="taskForm.case_path"
                    >
                      📄 {{ taskForm.case_path }}
                    </option>
                    <option v-for="c in options.yaml_cases" :key="c.path" :value="c.path">
                      {{ c.name }} {{ c.path ? '(' + c.path + ')' : '' }}
                    </option>
                  </select>
                </div>
                <div class="form-group" style="display: flex; gap: 20px; align-items: center; margin-top: 10px;">
                  <label style="display: flex; align-items: center; gap: 8px; cursor: pointer; font-size: 13px;">
                    <input type="checkbox" v-model="taskForm.ignore_errors">
                    <span>用例容错继续 (单步断言异常时不强行中断)</span>
                  </label>
                </div>
              </div>
            </div>

            <div>
              <!-- 自主探索模式 (explore) 专属右栏: 宏观提示词与模版 -->
              <div v-if="taskForm.mode === 'explore'">
                <div class="form-group">
                  <label class="form-label">预置高质量探索提示词库 (一键套用)</label>
                  <div class="select-pills" style="margin-bottom: 12px;">
                    <span class="pill-item" v-for="(tpl, idx) in options.prompt_templates" :key="idx"
                      @click="applyTemplate(tpl)">
                      🎯 {{ tpl.title }}
                    </span>
                  </div>

                  <label class="form-label">宏观探索目标提示词 (Macro Objective Prompt)</label>
                  <textarea class="form-control" v-model="taskForm.macro_objective" rows="7"
                    placeholder="输入自然语言意图，引导 AI 发起针对性探测..."></textarea>
                </div>
              </div>

              <!-- 全量冒烟巡检模式 (smoke) 专属右栏: 说明卡片 -->
              <div v-else-if="taskForm.mode === 'smoke'">
                <div style="background: rgba(13, 20, 36, 0.7); border: 1px solid #1a253c; border-radius: 8px; padding: 18px 20px;">
                  <div style="font-weight: 700; color: #00d2ff; margin-bottom: 10px; display: flex; align-items: center; gap: 8px; font-size: 14px;">
                    <span>🚀 全量二级业务菜单极速冒烟巡检 (Smoke Tour)</span>
                    <span style="font-size: 11px; background: rgba(0, 210, 255, 0.15); color: #00d2ff; padding: 2px 8px; border-radius: 10px; border: 1px solid rgba(0, 210, 255, 0.3);">零配置 · 全自动</span>
                  </div>
                  <p style="font-size: 13px; color: var(--text-muted); line-height: 1.6; margin-bottom: 12px;">
                    系统将跳过大模型自由规划路径，按权威菜单骨架<strong>100% 顺序遍历当前系统的全部二级业务菜单</strong>，确保零遗漏。
                  </p>
                  <div style="background: rgba(0, 210, 255, 0.04); border: 1px solid rgba(0, 210, 255, 0.15); border-radius: 6px; padding: 10px 14px; margin-bottom: 12px; font-size: 12px; line-height: 1.7; color: #8b9bb4;">
                    <div style="font-weight: 600; color: #00d2ff; margin-bottom: 4px;">🛡️ 每一站严格执行三阶健康度体检门禁：</div>
                    <div>1. <strong>无声崩溃嗅探</strong>：监听控制台 TypeError / Vue 渲染期崩溃 / WebGL 上下文丢失；</div>
                    <div>2. <strong>接口通信校验</strong>：校验滑动窗口网络通信，拦截 5xx 服务端错误、404 与超时；</div>
                    <div>3. <strong>视觉与物理感知</strong>：多模态视觉核验页面白屏、骨架屏假死与遮罩残留。</div>
                  </div>
                </div>
              </div>

              <!-- 确定性用例模式 (case) 专属右栏: 说明卡片 -->
              <div v-else-if="taskForm.mode === 'case'">
                <div style="background: rgba(13, 20, 36, 0.7); border: 1px solid #1a253c; border-radius: 8px; padding: 20px;">
                  <div style="font-weight: 700; color: #00d2ff; margin-bottom: 8px;">📋 YAML 确定性业务回归模式说明</div>
                  <p style="font-size: 13px; color: var(--text-muted); line-height: 1.6; margin-bottom: 12px;">
                    系统将由 <strong>ActionRunner</strong> 机械臂精确执行所选自然语言 YAML 脚本，执行确定性点击、输入、物理拖拽以及与底层网络 API 的双向交叉校验。
                  </p>
                </div>
              </div>
            </div>
          </div>

          <!-- ⚙️ 高级运行与韧性参数配置 (折叠面板) -->
          <div style="margin-top: 20px; border-top: 1px dashed #1a253c; padding-top: 14px;">
            <div
              style="cursor: pointer; display: flex; align-items: center; justify-content: space-between; user-select: none;"
              @click="taskForm.show_advanced = !taskForm.show_advanced">
              <span
                style="font-size: 13px; font-weight: 600; color: #00d2ff; display: flex; align-items: center; gap: 6px;">
                <span>⚙️ 高级运行与韧性参数配置 (CLI 选项)</span>
                <span
                  style="font-size: 11px; background: rgba(0, 210, 255, 0.15); color: #00d2ff; padding: 2px 8px; border-radius: 10px;">{{
                  taskForm.show_advanced ? '收起' : '展开' }}</span>
              </span>
              <span style="font-size: 12px; color: var(--text-muted);">{{ taskForm.show_advanced ? '▲' : '▼' }}</span>
            </div>

            <div v-show="taskForm.show_advanced"
              style="margin-top: 14px; background: rgba(5, 7, 13, 0.7); padding: 18px; border-radius: 8px; border: 1px solid #1a253c;">
              <div class="grid-2">
                <div class="form-group">
                  <label class="form-label">断点续传历史运行目录 (--resume-from)</label>
                  <input type="text" class="form-control" v-model="taskForm.resume_from"
                    placeholder="如 reports/runs/zhaiwan/explore_xxx (选填)">
                </div>
                <div class="form-group" v-if="taskForm.mode === 'explore'">
                  <label class="form-label">强制重新探索业务模块 (--reexplore)</label>
                  <input type="text" class="form-control" v-model="taskForm.reexplore" placeholder="如 智能通风、采掘设备 (选填)">
                </div>
                <div class="form-group">
                  <label class="form-label">启动缓冲等待时间 (秒, --start-delay)</label>
                  <input type="number" class="form-control" v-model.number="taskForm.start_delay"
                    placeholder="默认 15 秒">
                </div>
                <div class="form-group">
                  <label class="form-label">视觉智能就绪自然语言条件 (--wait-ready)</label>
                  <input type="text" class="form-control" v-model="taskForm.wait_ready"
                    placeholder="如 主看板加载就绪 (持续截屏轮询直到满足)">
                </div>
                <div class="form-group">
                  <label class="form-label">视觉就绪最大超时 (秒, --wait-timeout)</label>
                  <input type="number" class="form-control" v-model.number="taskForm.wait_timeout"
                    placeholder="默认 60 秒">
                </div>
                <div class="form-group" style="display: flex; align-items: center; margin-top: 24px;">
                  <label
                    style="display: flex; align-items: center; gap: 8px; cursor: pointer; font-size: 13px; color: #ffb300;">
                    <input type="checkbox" v-model="taskForm.ignore_env_check">
                    <span>强制跳过 Launcher 环境校验 (--ignore-env-check)</span>
                  </label>
                </div>
              </div>
            </div>
          </div>
        </div>

        <!-- 弹窗底部操作栏 (确认项 3: 多通道闭环) -->
        <div style="padding: 14px 24px; border-top: 1px solid #1a253c; background: #0d1424; display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 12px;">
          <div style="font-size: 12px; color: var(--text-muted);">
            💡 提示: “立即启动”将一键拉起巡检；若需沉淀为日常标准方案，可点击“保存为新预设”。
          </div>
          <div style="display: flex; gap: 10px; align-items: center;">
            <button type="button" class="btn btn-secondary" @click="taskModalVisible = false" style="padding: 8px 16px;">
              取消
            </button>
            <button type="button" class="btn btn-secondary" style="border-color: #00d2ff; color: #00d2ff; padding: 8px 16px;"
              @click="saveCurrentFormAsPreset(false)" title="将当前配置持久化保存为独立的新预设">
              💾 保存为新预设
            </button>
            <button type="button" v-if="taskForm.preset_id" class="btn btn-secondary"
              style="border-color: #ffb300; color: #ffb300; background: rgba(255, 179, 0, 0.1); padding: 8px 16px;"
              @click="saveCurrentFormAsPreset(true)" title="直接回写覆盖当前载入的原预设（保持 ID 不变）">
              🔄 覆盖当前预设
            </button>
            <button type="button" class="btn btn-primary" style="padding: 8px 22px; font-weight: 600;"
              @click="submitCreateTask" title="立即创建并启动巡检">
              🚀 立即创建并启动
            </button>
          </div>
        </div>
      </div>
    </div>

    <!-- 🔍 预设任务详情只读弹窗 (确认项 4: 方案 A) -->
    <div class="modal-overlay" v-if="taskDetailModalVisible && activeDetailPreset" style="z-index: 9999;" @click.self="taskDetailModalVisible = false">
      <div class="modal-content" style="max-width: 760px; width: 92%; max-height: 85vh; display: flex; flex-direction: column; padding: 0; overflow: hidden; border-radius: 12px; box-shadow: 0 20px 60px rgba(0,0,0,0.8); border: 1px solid #1a253c; background: #0b1120;">
        <!-- 弹窗头部 -->
        <div class="modal-header" style="padding: 16px 20px; border-bottom: 1px solid #1a253c; display: flex; align-items: center; justify-content: space-between; background: #0d1424;">
          <div style="display: flex; align-items: center; gap: 10px;">
            <span style="font-size: 18px;">🔍</span>
            <div>
              <div style="font-size: 15px; font-weight: 700; color: #fff;">{{ activeDetailPreset.title }}</div>
              <div style="font-size: 11px; color: #64748b; font-family: monospace;">#{{ activeDetailPreset.id }}</div>
            </div>
          </div>
          <button type="button" style="background: transparent; border: none; color: #64748b; font-size: 22px; cursor: pointer; line-height: 1;" @click="taskDetailModalVisible = false" title="关闭">&times;</button>
        </div>

        <!-- 弹窗主体 -->
        <div style="flex: 1; overflow-y: auto; padding: 20px;">
          <!-- 基础信息栅格 -->
          <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 12px; margin-bottom: 18px;">
            <div style="background: rgba(13, 20, 36, 0.7); border: 1px solid #1a253c; border-radius: 6px; padding: 12px;">
              <div style="font-size: 11px; color: var(--text-muted); margin-bottom: 4px;">运行矿山</div>
              <div style="font-size: 13px; font-weight: 600; color: #00d2ff;">🎯 {{ getAppName(activeDetailPreset.app_name) }}</div>
            </div>
            <div style="background: rgba(13, 20, 36, 0.7); border: 1px solid #1a253c; border-radius: 6px; padding: 12px;">
              <div style="font-size: 11px; color: var(--text-muted); margin-bottom: 4px;">运行模式</div>
              <div>
                <span class="badge" :class="(activeDetailPreset.tour || activeDetailPreset.mode === 'smoke') ? 'badge-running' : (activeDetailPreset.mode === 'case' ? 'badge-low' : 'badge-high')">
                  {{ getPresetModeLabel(activeDetailPreset) }}
                </span>
              </div>
            </div>
            <div style="background: rgba(13, 20, 36, 0.7); border: 1px solid #1a253c; border-radius: 6px; padding: 12px;">
              <div style="font-size: 11px; color: var(--text-muted); margin-bottom: 4px;">步数与时限</div>
              <div style="font-size: 13px; font-weight: 600; color: #fff;">
                <span>{{ activeDetailPreset.max_steps ? (activeDetailPreset.max_steps + ' 步') : '无限制 (0步)' }}</span> / 
                <span style="color: #ffb300;">{{ activeDetailPreset.max_times }} 分钟</span>
              </div>
            </div>
            <div style="background: rgba(13, 20, 36, 0.7); border: 1px solid #1a253c; border-radius: 6px; padding: 12px;">
              <div style="font-size: 11px; color: var(--text-muted); margin-bottom: 4px;">容错与韧性策略</div>
              <div style="font-size: 12px; color: #00e676;">
                {{ activeDetailPreset.ignore_errors ? '✅ 容错继续 (不阻断)' : '❌ 严格阻断' }}
              </div>
            </div>
          </div>

          <!-- 方案描述 -->
          <div v-if="activeDetailPreset.description" style="margin-bottom: 16px;">
            <div style="font-size: 12px; font-weight: 600; color: var(--text-muted); margin-bottom: 6px;">方案描述说明:</div>
            <div style="font-size: 13px; color: #cbd5e1; background: rgba(13, 20, 36, 0.5); padding: 10px 14px; border-radius: 6px; border: 1px solid #1a253c; line-height: 1.6;">
              {{ activeDetailPreset.description }}
            </div>
          </div>

          <!-- 宏观提示词展示 (带快捷复制) -->
          <div v-if="activeDetailPreset.macro_objective" style="margin-bottom: 16px;">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px;">
              <span style="font-size: 12px; font-weight: 600; color: #00d2ff;">🎯 宏观目标探索提示词 (Prompt):</span>
              <button type="button" class="btn btn-secondary" style="padding: 2px 8px; font-size: 11px;" @click="copyPresetPrompt(activeDetailPreset.macro_objective)">
                📋 复制提示词
              </button>
            </div>
            <div style="font-size: 12px; color: #cbd5e1; background: rgba(5, 7, 13, 0.8); padding: 12px 14px; border-radius: 6px; border: 1px solid #1a253c; line-height: 1.7; white-space: pre-wrap; font-family: monospace; max-height: 220px; overflow-y: auto;">{{ activeDetailPreset.macro_objective }}</div>
          </div>

          <!-- YAML 用例路径 (如果存在) -->
          <div v-if="activeDetailPreset.case_path" style="margin-bottom: 16px;">
            <div style="font-size: 12px; font-weight: 600; color: #00d2ff; margin-bottom: 6px;">📋 YAML 脚本路径:</div>
            <div style="font-size: 12px; color: #fff; background: rgba(5, 7, 13, 0.8); padding: 8px 12px; border-radius: 6px; border: 1px solid #1a253c; font-family: monospace;">
              {{ activeDetailPreset.case_path }}
            </div>
          </div>

          <!-- 高阶 CLI 参数列表 -->
          <div>
            <div style="font-size: 12px; font-weight: 600; color: var(--text-muted); margin-bottom: 6px;">⚙️ 高阶调优参数:</div>
            <div style="font-size: 12px; background: rgba(13, 20, 36, 0.5); padding: 10px 14px; border-radius: 6px; border: 1px solid #1a253c; line-height: 1.8; color: #94a3b8;">
              <div>• 启动缓冲等待: <strong style="color: #fff;">{{ activeDetailPreset.start_delay != null ? (activeDetailPreset.start_delay + ' 秒') : '默认 15 秒' }}</strong></div>
              <div>• 视觉就绪轮询超时: <strong style="color: #fff;">{{ activeDetailPreset.wait_timeout || 60 }} 秒</strong></div>
              <div>• 环境校验准入: <strong :style="activeDetailPreset.ignore_env_check ? 'color: #ffb300;' : 'color: #00e676;'">{{ activeDetailPreset.ignore_env_check ? '跳过校验直接运行' : '严格准入校验' }}</strong></div>
              <div v-if="activeDetailPreset.wait_ready">• 就绪判定条件: <strong style="color: #fff;">{{ activeDetailPreset.wait_ready }}</strong></div>
              <div v-if="activeDetailPreset.resume_from">• 历史断点续传: <strong style="color: #fff;">{{ activeDetailPreset.resume_from }}</strong></div>
            </div>
          </div>
        </div>

        <!-- 弹窗底部操作栏 -->
        <div style="padding: 14px 20px; border-top: 1px solid #1a253c; background: #0d1424; display: flex; justify-content: flex-end; gap: 10px; align-items: center;">
          <button type="button" class="btn btn-secondary" @click="taskDetailModalVisible = false" style="padding: 6px 14px;">
            关闭
          </button>
          <button type="button" class="btn btn-secondary" style="border-color: #64748b; color: #cbd5e1; padding: 6px 14px;" @click="editFromDetail">
            ✏️ 前往编辑
          </button>
          <button type="button" class="btn btn-primary" style="padding: 6px 18px; font-weight: 600;" @click="launchFromDetail">
            🚀 立即运行
          </button>
        </div>
      </div>
    </div>

    <!-- 🔔 全局自研现代化确认与输入交互弹窗 (彻底替换原生 confirm / prompt) -->
    <div class="modal-overlay" v-if="dialogState.visible" style="z-index: 99999;" @click.self="handleDialogCancel">
      <div class="modal-content" style="max-width: 480px; width: 92%; padding: 24px; border: 1px solid var(--border-color); box-shadow: 0 16px 50px rgba(0, 0, 0, 0.7); border-radius: 12px;">
        <div class="modal-header" style="margin-bottom: 16px; border-bottom: 1px solid rgba(255, 255, 255, 0.08); padding-bottom: 12px; display: flex; align-items: center; justify-content: space-between;">
          <h3 style="font-size: 16px; display: flex; align-items: center; gap: 8px; margin: 0; color: #fff; font-weight: 700;">
            <span style="font-size: 18px;">{{ dialogState.icon || (dialogState.isDanger ? '⚠️' : '💬') }}</span>
            <span>{{ dialogState.title }}</span>
          </h3>
          <button class="modal-close" style="background: none; border: none; color: var(--text-muted); font-size: 22px; cursor: pointer; line-height: 1;" @click="handleDialogCancel">&times;</button>
        </div>

        <div style="font-size: 14px; line-height: 1.6; color: #cbd5e1; margin-bottom: 20px; white-space: pre-wrap; word-break: break-word;">{{ dialogState.message }}</div>

        <!-- Prompt 专用暗黑输入框 -->
        <div v-if="dialogState.type === 'prompt'" style="margin-bottom: 20px;">
          <input
            ref="dialogInputRef"
            type="text"
            class="form-control"
            v-model="dialogState.inputValue"
            :placeholder="dialogState.inputPlaceholder"
            style="width: 100%; box-sizing: border-box; padding: 10px 14px; font-size: 14px;"
            @keyup.enter="handleDialogConfirm"
            @keyup.esc="handleDialogCancel"
          />
        </div>

        <div style="display: flex; justify-content: flex-end; gap: 12px;">
          <button class="btn btn-secondary" style="min-width: 80px; padding: 8px 16px;" @click="handleDialogCancel">
            {{ dialogState.cancelText || '取消' }}
          </button>
          <button
            class="btn"
            :class="dialogState.isDanger ? 'btn-danger' : 'btn-primary'"
            style="min-width: 80px; padding: 8px 18px; font-weight: 600;"
            :style="dialogState.isDanger ? 'background: #ff5252; border-color: #ff5252;' : ''"
            @click="handleDialogConfirm">
            {{ dialogState.confirmText || '确定' }}
          </button>
        </div>
      </div>
    </div>

    <!-- 全局现代 Toast 通知层 -->
    <div class="toast-container" v-if="toasts && toasts.length">
      <div v-for="t in toasts" :key="t.id" :class="['toast-item', 'toast-' + t.type]">
        <div class="toast-icon">
          <span v-if="t.type === 'success'">🎉</span>
          <span v-else-if="t.type === 'info'">ℹ️</span>
          <span v-else>⚠️</span>
        </div>
        <div class="toast-body">
          <div class="toast-title">{{ t.title || '系统提示' }}</div>
          <div class="toast-msg" v-html="t.message"></div>
        </div>
        <button class="toast-close" @click="removeToast(t.id)">&times;</button>
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

<style scoped>
.zentao-preview-layout {
  display: grid;
  grid-template-columns: minmax(0, 1.35fr) minmax(390px, 1fr);
  gap: 20px;
  align-items: start;
}

.zentao-preview-sidebar {
  min-width: 0;
  background: rgba(15, 23, 42, 0.55);
  border: 1px solid rgba(148, 163, 184, 0.16);
  border-radius: 10px;
  padding: 14px 16px;
}

.zentao-preview-sidebar .form-control {
  width: 100%;
  min-width: 0;
  box-sizing: border-box;
}

.zentao-steps-preview {
  background: #ffffff;
  color: #1e293b;
  border-radius: 8px;
  padding: 16px;
  border: 1px solid #cbd5e1;
  max-height: 54vh;
  overflow-y: auto;
  overflow-x: hidden;
  font-size: 13px;
  line-height: 1.6;
  word-break: break-word;
  overflow-wrap: anywhere;
}

.zentao-steps-preview :deep(*) {
  max-width: 100%;
  box-sizing: border-box;
}

.zentao-steps-preview :deep(pre),
.zentao-steps-preview :deep(code) {
  white-space: pre-wrap;
  word-break: break-word;
  overflow-wrap: anywhere;
}

.zentao-steps-preview :deep(img) {
  display: block;
  max-width: 100%;
  height: auto;
}
</style>
