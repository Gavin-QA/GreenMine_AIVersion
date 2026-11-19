import { ref, reactive, computed, onMounted, onUnmounted, nextTick, watch } from 'vue'
import * as echarts from 'echarts'



export function usePlatformStore() {

    const TAB_STORAGE_KEY = 'vision_platform_current_tab';
    const ASSETS_SUBTAB_KEY = 'vision_platform_assets_subtab';
    const SETTINGS_SUBTAB_KEY = 'vision_platform_settings_subtab';

    const validTabs = ['dashboard', 'monitor', 'tasks', 'bugs', 'settings'];
    const savedTab = localStorage.getItem(TAB_STORAGE_KEY);
    const currentTab = ref(validTabs.includes(savedTab) ? savedTab : 'dashboard'); // dashboard, tasks, monitor, bugs, settings

    const apiBase = window.location.origin;

    // 全局 Toast 通知状态与操作方法 (多态支持纯文本与对象传参)
    const toasts = ref([]);
    function showToast(titleOrObj, message = '', type = 'success', duration = 6000) {
      let title = titleOrObj;
      if (typeof titleOrObj === 'object' && titleOrObj !== null) {
        title = titleOrObj.title || '';
        message = titleOrObj.message || '';
        type = titleOrObj.type || 'info';
        duration = titleOrObj.duration !== undefined ? titleOrObj.duration : 6000;
      }
      const id = Date.now() + Math.random().toString(36).slice(2, 6);
      toasts.value.push({ id, title, message, type });
      if (duration > 0) {
        setTimeout(() => {
          removeToast(id);
        }, duration);
      }
    }
    function removeToast(id) {
      toasts.value = toasts.value.filter(t => t.id !== id);
    }

    // 全局自研现代化确认与输入交互弹窗 (彻底替换原生 confirm / prompt)
    const dialogState = reactive({
      visible: false,
      type: 'confirm', // 'confirm' | 'prompt'
      icon: '',
      title: '',
      message: '',
      confirmText: '确定',
      cancelText: '取消',
      inputValue: '',
      inputPlaceholder: '',
      isDanger: false,
      resolve: null,
    });
    const dialogInputRef = ref(null);

    function showConfirm({ title = '操作确认', message = '', icon = '', confirmText = '确定', cancelText = '取消', danger = false } = {}) {
      return new Promise((resolve) => {
        dialogState.type = 'confirm';
        dialogState.icon = icon || (danger ? '⚠️' : '💬');
        dialogState.title = title;
        dialogState.message = message;
        dialogState.confirmText = confirmText;
        dialogState.cancelText = cancelText;
        dialogState.isDanger = danger;
        dialogState.inputValue = '';
        dialogState.resolve = resolve;
        dialogState.visible = true;
      });
    }

    function showPrompt({ title = '请输入', message = '', defaultValue = '', placeholder = '', icon = '✏️', confirmText = '确定', cancelText = '取消' } = {}) {
      return new Promise((resolve) => {
        dialogState.type = 'prompt';
        dialogState.icon = icon;
        dialogState.title = title;
        dialogState.message = message;
        dialogState.confirmText = confirmText;
        dialogState.cancelText = cancelText;
        dialogState.isDanger = false;
        dialogState.inputValue = defaultValue || '';
        dialogState.inputPlaceholder = placeholder || '';
        dialogState.resolve = resolve;
        dialogState.visible = true;
        nextTick(() => {
          if (dialogInputRef.value) {
            dialogInputRef.value.focus();
            dialogInputRef.value.select();
          }
        });
      });
    }

    function handleDialogConfirm() {
      if (dialogState.resolve) {
        if (dialogState.type === 'prompt') {
          dialogState.resolve(dialogState.inputValue.trim());
        } else {
          dialogState.resolve(true);
        }
      }
      dialogState.visible = false;
      dialogState.resolve = null;
    }

    function handleDialogCancel() {
      if (dialogState.resolve) {
        if (dialogState.type === 'prompt') {
          dialogState.resolve(null);
        } else {
          dialogState.resolve(false);
        }
      }
      dialogState.visible = false;
      dialogState.resolve = null;
    }




    // 全局选项配置 (应用、模式、提示词模板)

    const options = reactive({
      apps: [],
      modes: [],
      yaml_cases: [],
      prompt_templates: [],
      zentao_configured: false,
      report_hub_url: '/report-hub'
    });



    // 预设任务库
    const presetTasks = ref([]);

    // 预设任务库视图模式 (card 卡片 | list 列表，默认卡片)
    const presetViewMode = ref(localStorage.getItem('presetViewMode') || 'card');
    function setPresetViewMode(mode) {
      presetViewMode.value = mode;
      try {
        localStorage.setItem('presetViewMode', mode);
      } catch (e) {}
    }

    // 预设列表排序状态 (字段名: title, app_name, mode, max_steps, max_times, id)
    const presetSortField = ref('');
    const presetSortOrder = ref('asc'); // 'asc' | 'desc'
    function togglePresetSort(field) {
      if (presetSortField.value === field) {
        if (presetSortOrder.value === 'asc') {
          presetSortOrder.value = 'desc';
        } else {
          presetSortField.value = '';
          presetSortOrder.value = 'asc';
        }
      } else {
        presetSortField.value = field;
        presetSortOrder.value = 'asc';
      }
    }

    const sortedPresetTasks = computed(() => {
      const list = (presetTasks.value || []).slice();
      if (!presetSortField.value) return list;
      const field = presetSortField.value;
      const order = presetSortOrder.value === 'desc' ? -1 : 1;
      return list.sort((a, b) => {
        let valA = a[field];
        let valB = b[field];
        if (field === 'max_steps' || field === 'max_times') {
          return ((Number(valA) || 0) - (Number(valB) || 0)) * order;
        }
        valA = (valA || '').toString();
        valB = (valB || '').toString();
        return valA.localeCompare(valB, 'zh-CN') * order;
      });
    });

    // 预设任务弹窗控制 (新建/微调)
    const taskModalVisible = ref(false);

    function openNewTaskModal() {
      clearLoadedPreset();
      if (!taskForm.app_name && options.apps && options.apps.length > 0) {
        taskForm.app_name = options.apps[0].key;
      }
      taskForm.name = '';
      taskForm.mode = 'explore';
      taskForm.tour = false;
      taskForm.case_path = '';
      taskForm.macro_objective = '';
      taskForm.max_steps = 200;
      taskForm.max_times = 60;
      taskForm.reset_memory = false;
      taskForm.ignore_errors = true;
      taskForm.show_advanced = false;
      taskForm.resume_from = '';
      taskForm.reexplore = '';
      taskForm.start_delay = null;
      taskForm.wait_ready = '';
      taskForm.wait_timeout = 60;
      taskForm.ignore_env_check = false;
      taskModalVisible.value = true;
    }

    // 任务详情只读弹窗 (确认项 4: 方案 A)
    const taskDetailModalVisible = ref(false);
    const activeDetailPreset = ref(null);

    function openPresetDetail(preset) {
      activeDetailPreset.value = preset;
      taskDetailModalVisible.value = true;
    }

    function editFromDetail() {
      if (!activeDetailPreset.value) return;
      const p = activeDetailPreset.value;
      taskDetailModalVisible.value = false;
      loadPresetToForm(p);
    }

    function launchFromDetail() {
      if (!activeDetailPreset.value) return;
      const p = activeDetailPreset.value;
      taskDetailModalVisible.value = false;
      launchPreset(p);
    }

    async function copyPresetPrompt(text) {
      if (!text) {
        showToast('提示', '该预设无宏观目标提示词', 'info');
        return;
      }
      try {
        await navigator.clipboard.writeText(text);
        showToast('复制成功', '提示词已成功复制到剪贴板！', 'success', 2000);
      } catch (err) {
        showToast('复制失败', String(err), 'error');
      }
    }



    // 实时物理环境探针

    const liveSnapshot = reactive({

      app_name: 'zhaiwan',

      cdp_online: false,

      ue_online: false,

      gpu_online: false,

      dom_count: 0,

      listeners_count: 0,

      js_heap_mb: 0,

      webrtc_fps: 0,

      ue_memory_mb: 0,

      ue_commit_mb: 0,

      host_ram_load_percent: 0,

      host_commit_load_percent: 0,

      ue_cpu_percent: 0,

      ue_cpu_raw_percent: 0,

      cpu_cores: 12,

      gpu_usage_percent: 0,

      gpu_memory_mb: 0

    });



    // 任务列表与创建表单

    const tasks = ref([]);

    const activeTaskId = ref('__live__');

    const activeTask = ref(null);

    // 调度执行计划与预约定时
    const taskQueue = ref([]);
    const pendingQueueCount = ref(0);
    const showEnqueueModal = ref(false);
    const isSubmittingEnqueue = ref(false);
    const scheduleModalTab = ref('basic'); // 'basic' | 'advanced'
    const scheduleForm = reactive({
      id: '', // 编辑时有值
      name: '',
      app_name: 'zhaiwan',
      preset_id: '',
      priority: 2,
      startDate: '',
      endDate: '',
      executionTime: '18:35:00',
      endTime: '23:59:59',
      cron_mode: 'daily',
      minuteInterval: 30,
      hourInterval: 2,
      dailyInterval: 1,
      weeklyDays: [1, 2, 3, 4, 5],
      monthlyDay: 1,
      conflict_policy: 'wait',
      auto_retry: 0,
      ignore_env_check: 0,
      is_active: 1
    });

    const filteredSchedulePresets = computed(() => {
      return (presetTasks.value || []).filter(p => p.app_name === scheduleForm.app_name);
    });

    // 任务列表多维筛选与分页 (Element Plus <el-date-picker type="daterange"> + 应用)
    const taskDateRange = ref([]);
    const taskAppFilter = ref('all');
    const taskQuickDateRange = ref('all');
    const dateShortcuts = [
      {
        text: '今天',
        value: () => {
          const d = new Date();
          return [d, d];
        },
      },
      {
        text: '最近 7 天',
        value: () => {
          const end = new Date();
          const start = new Date();
          start.setDate(end.getDate() - 6);
          return [start, end];
        },
      },
      {
        text: '本月',
        value: () => {
          const end = new Date();
          const start = new Date(end.getFullYear(), end.getMonth(), 1);
          return [start, end];
        },
      },
    ];
    const taskPage = ref(1);
    const taskPageSize = ref(10);
    const taskPageSizes = [10, 20, 50];
    const taskPageJump = ref(1);

    function extractTaskDate(t) {
      if (t.start_time) {
        const m = String(t.start_time).match(/^(\d{4}-\d{2}-\d{2})/);
        if (m) return m[1];
      }
      const fallbackSrc = t.run_dir || t.id || '';
      const m2 = String(fallbackSrc).match(/(20\d{2})(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])/);
      if (m2) return `${m2[1]}-${m2[2]}-${m2[3]}`;
      return '';
    }

    function formatLocalYMD(dt) {
      const y = dt.getFullYear();
      const m = String(dt.getMonth() + 1).padStart(2, '0');
      const d = String(dt.getDate()).padStart(2, '0');
      return `${y}-${m}-${d}`;
    }

    function applyQuickTaskDateRange(preset) {
      taskQuickDateRange.value = preset;
      const now = new Date();
      const todayStr = formatLocalYMD(now);
      if (preset === 'all') {
        taskDateRange.value = [];
      } else if (preset === 'today') {
        taskDateRange.value = [todayStr, todayStr];
      } else if (preset === '7d') {
        const d7 = new Date(now);
        d7.setDate(now.getDate() - 6);
        taskDateRange.value = [formatLocalYMD(d7), todayStr];
      } else if (preset === 'month') {
        taskDateRange.value = [`${todayStr.slice(0, 7)}-01`, todayStr];
      }
      onTaskPageSizeChange();
    }

    function onTaskDateInputChange() {
      taskQuickDateRange.value = (!taskDateRange.value || taskDateRange.value.length === 0) ? 'all' : '';
      onTaskPageSizeChange();
    }

    function resetTaskFilters() {
      taskDateRange.value = [];
      taskAppFilter.value = 'all';
      taskQuickDateRange.value = 'all';
      onTaskPageSizeChange();
    }

    const filteredTasks = computed(() => {
      const range = Array.isArray(taskDateRange.value) ? taskDateRange.value : [];
      const startD = range[0] || '';
      const endD = range[1] || '';
      return (tasks.value || []).filter(t => {
        if (taskAppFilter.value && taskAppFilter.value !== 'all') {
          if ((t.app_name || '') !== taskAppFilter.value) return false;
        }
        if (startD || endD) {
          const d = extractTaskDate(t);
          if (!d) return false;
          if (startD && d < startD) return false;
          if (endD && d > endD) return false;
        }
        return true;
      });
    });

    const totalTaskPages = computed(() => {
      const total = Math.ceil(filteredTasks.value.length / taskPageSize.value);
      return total > 0 ? total : 1;
    });

    const paginatedTasks = computed(() => {
      const start = (taskPage.value - 1) * taskPageSize.value;
      return filteredTasks.value.slice(start, start + taskPageSize.value);
    });

    function setTaskPage(p) {
      if (typeof p !== 'number') return;
      if (p < 1) p = 1;
      if (p > totalTaskPages.value) p = totalTaskPages.value;
      taskPage.value = p;
      taskPageJump.value = p;
    }

    function onTaskPageSizeChange() {
      taskPage.value = 1;
      taskPageJump.value = 1;
    }

    function jumpToTaskPage() {
      let p = parseInt(taskPageJump.value, 10);
      if (isNaN(p)) p = 1;
      setTaskPage(p);
    }


    // 矿山应用选中状态 (默认不选择，底部探针目标显示 "--"，用户主动在监控大屏或任务中选中后再联动)
    const storedApp = localStorage.getItem('vision_platform_app_name') || '';
    const liveSelectedApp = ref(storedApp);

    const liveTimeSpan = ref('24h');

    const liveAppsStatus = ref([
      { app_name: 'tianrui', title: '四川天瑞', online: false, ue_pid: null, ue_commit_mb: 0, ue_memory_mb: 0 },
      { app_name: 'zhaiwan', title: '寨湾矿山', online: false, ue_pid: null, ue_commit_mb: 0, ue_memory_mb: 0 },
      { app_name: 'liwutong', title: '里伍铜矿山', online: false, ue_pid: null, ue_commit_mb: 0, ue_memory_mb: 0 }
    ]);

    // 任务与产物库内二级菜单状态 ('runs' | 'queue' | 'cases')
    const validAssetsSub = ['runs', 'queue', 'cases'];
    const savedAssetsSub = localStorage.getItem(ASSETS_SUBTAB_KEY);
    const assetsSubTab = ref(validAssetsSub.includes(savedAssetsSub) ? savedAssetsSub : 'runs');

    // 系统配置二级菜单状态 ('overview' | 'cleanup')
    const validSettingsSub = ['overview', 'cleanup'];
    const savedSettingsSub = localStorage.getItem(SETTINGS_SUBTAB_KEY);
    const settingsSubTab = ref(validSettingsSub.includes(savedSettingsSub) ? savedSettingsSub : 'overview');

    // 含二级菜单的一级菜单展开状态（默认全部收起；若刷新恢复时处于对应菜单则展开）
    const navExpanded = reactive({
      tasks: currentTab.value === 'tasks',
      settings: currentTab.value === 'settings',
    });

    function selectPrimaryMenu(tab) {
      if (tab === 'tasks') {
        if (currentTab.value !== 'tasks') {
          currentTab.value = 'tasks';
          assetsSubTab.value = 'runs';
          navExpanded.tasks = true;
        } else {
          navExpanded.tasks = !navExpanded.tasks;
        }
        return;
      }
      if (tab === 'settings') {
        if (currentTab.value !== 'settings') {
          currentTab.value = 'settings';
          settingsSubTab.value = 'overview';
          navExpanded.settings = true;
        } else {
          navExpanded.settings = !navExpanded.settings;
        }
        return;
      }
      currentTab.value = tab;
    }

    // 运行环境与配置基线快照弹窗状态
    const selectedEnvInfo = ref(null);
    const envInfoLoading = ref(false);
    const envInfoViewMode = ref('card'); // 'card' | 'json'

    // 用例资产管理状态
    const manualCases = ref([]);
    const autoCases = ref([]);
    const casesSubTab = ref('manual'); // 'manual' | 'auto'
    const isCasesLoading = ref(false);
    const previewingCase = ref(null);
    const previewCaseLoading = ref(false);
    const previewCaseContent = ref('');



    const taskForm = reactive({
      preset_id: null, // 记录当前是否绑定某个预设 (用于回写保存)
      preset_title: '', // 当前绑定的预设名称
      name: '',
      app_name: storedApp,
      mode: 'explore', // explore | case
      tour: false, // 是否启用二级菜单全量冒烟巡检策略 (--tour)
      case_path: '',
      macro_objective: '',
      max_steps: 200,
      max_times: 60,
      reset_memory: false,
      ignore_errors: true,
      explore_context: `docs/explore_rules_${storedApp}.md`,
      // 进阶参数调优 (对应 main.py CLI 选项)
      show_advanced: false,
      resume_from: '',
      reexplore: '',
      start_delay: null,
      wait_ready: '',
      wait_timeout: 60,
      ignore_env_check: false
    });

    // 全局当前权威选中的矿山名称 (未选择时默认显示 "--")
    const currentAppName = computed(() => {
      const key = liveSelectedApp.value || '';
      if (!key) return '--';
      const found = (options.apps || []).find(a => a.key === key);
      return found ? found.name : key;
    });



    // 监控页面与 ECharts

    const terminalLogs = ref([]);

    let logWs = null;

    let metricWs = null;

    let domChart = null;

    let ueChart = null;



    // 缺陷列表

    const isSyncing = ref(false);

    const bugs = ref([]);

    const isBugsLoading = ref(false);

    // 缺陷列表服务端物理分页
    const bugPage = ref(1);
    const bugPageSize = ref(15);
    const bugPageSizes = [10, 15, 30, 50];
    const bugPageJump = ref(1);
    const totalBugs = ref(0);

    const totalBugPages = computed(() => {
      const total = Math.ceil(totalBugs.value / bugPageSize.value);
      return total > 0 ? total : 1;
    });

    // 模板兼容: 当前页数据直接映射
    const paginatedBugs = computed(() => bugs.value || []);

    // 缺陷批量勾选与后台串行推禅道
    const selectedBugIds = ref([]);
    const batchZentaoJob = ref(null);
    let batchZentaoPollTimer = null;

    const selectableBugsOnPage = computed(() =>
      (paginatedBugs.value || []).filter(b => b && !b.zentao_id)
    );

    const isAllPageBugsSelected = computed(() =>
      selectableBugsOnPage.value.length > 0 &&
      selectableBugsOnPage.value.every(b => selectedBugIds.value.includes(b.id))
    );

    const isSomePageBugsSelected = computed(() =>
      selectableBugsOnPage.value.some(b => selectedBugIds.value.includes(b.id)) &&
      !isAllPageBugsSelected.value
    );

    function toggleBugSelection(bug) {
      if (!bug || !bug.id || bug.zentao_id) return;
      const idx = selectedBugIds.value.indexOf(bug.id);
      if (idx >= 0) {
        selectedBugIds.value.splice(idx, 1);
      } else {
        selectedBugIds.value.push(bug.id);
      }
    }

    function toggleSelectAllPageBugs() {
      const pageIds = selectableBugsOnPage.value.map(b => b.id);
      if (pageIds.length === 0) return;
      if (isAllPageBugsSelected.value) {
        selectedBugIds.value = selectedBugIds.value.filter(id => !pageIds.includes(id));
      } else {
        const merged = new Set([...selectedBugIds.value, ...pageIds]);
        selectedBugIds.value = Array.from(merged);
      }
    }

    function clearBugSelection() {
      selectedBugIds.value = [];
    }

    function setBugPage(p) {
      if (typeof p !== 'number') return;
      if (p < 1) p = 1;
      if (p > totalBugPages.value) p = totalBugPages.value;
      if (p === bugPage.value) return;
      bugPage.value = p;
      bugPageJump.value = p;
      fetchBugs();
    }

    function onBugPageSizeChange() {
      bugPage.value = 1;
      bugPageJump.value = 1;
      fetchBugs();
    }

    function jumpToBugPage() {
      let p = parseInt(bugPageJump.value, 10);
      if (isNaN(p)) p = 1;
      if (p < 1) p = 1;
      if (p > totalBugPages.value) p = totalBugPages.value;
      bugPage.value = p;
      bugPageJump.value = p;
      fetchBugs();
    }

    // 通用页码按钮生成逻辑 (支持 1 ... 4 5 6 ... 10)
    function getPageNumbers(current, total) {
      if (!total || total <= 1) return [1];
      if (total <= 7) {
        return Array.from({ length: total }, (_, i) => i + 1);
      }
      if (current <= 4) {
        return [1, 2, 3, 4, 5, '...', total];
      }
      if (current >= total - 3) {
        return [1, '...', total - 4, total - 3, total - 2, total - 1, total];
      }
      return [1, '...', current - 1, current, current + 1, '...', total];
    }


    let bugSearchTimer = null;

    let bugAbortController = null;

    const bugSearch = ref('');
    const bugAppFilter = ref('');
    const bugSeverityFilter = ref('');

    const bugAssigneeFilter = ref('');

    const bugStatusFilter = ref('');

    const bugOccurrencesFilter = ref('');

    const selectedBug = ref(null);

    const editingBug = ref(null);

    const editForm = reactive({

      id: '',

      title: '',

      severity: 'Medium',

      status: '激活',

      assignee: '陈贻雄',

      zentao_id: '',

      ui_path: '',

      analysis_notes: '',

      remark: ''

    });



    // =========================================================================

    // API 请求封装

    // =========================================================================



    async function fetchOptions() {

      try {

        const res = await fetch(`${apiBase}/api/config/options`);

        const data = await res.json();

        options.apps = data.apps || [];
        options.modes = data.modes || [];
        options.yaml_cases = data.yaml_cases || [];
        options.prompt_templates = data.prompt_templates || [];

        options.zentao_configured = data.zentao_configured;

        if (data.report_hub_url) {

          options.report_hub_url = data.report_hub_url;

        }



        if (options.prompt_templates.length > 0 && !taskForm.macro_objective) {

          taskForm.macro_objective = options.prompt_templates[0].prompt;

        }

      } catch (e) {

        console.error('获取配置选项失败:', e);

      }

    }



    async function fetchPresetTasks() {
      try {
        const res = await fetch(`${apiBase}/api/tasks/presets`);
        const list = await res.json();
        if (Array.isArray(list)) {
          // 严格按 ID 升序稳定排序，确保用户编辑后位置固定
          list.sort((a, b) => (a.id || '').localeCompare(b.id || ''));
          presetTasks.value = list;
        }
      } catch (e) {
        console.error('获取预设任务列表失败:', e);
      }
    }

    function getPresetModeLabel(preset) {
      if (preset.tour || preset.mode === 'smoke') return '🤖 极速冒烟';
      if (preset.mode === 'case') return '📋 YAML 回归';
      return '🔍 自主探索';
    }

    function getAppName(appKey) {
      const found = (options.apps || []).find(a => a.key === appKey);
      return found ? found.name : (appKey || '未指定');
    }

    function clearLoadedPreset() {
      taskForm.preset_id = null;
      taskForm.preset_title = '';
    }

    function getSpanHours(span) {
      if (span === '15m') return 0.25;
      if (span === '1h') return 1.0;
      if (span === '6h') return 6.0;
      return 24.0;
    }

    async function fetchLiveAppsStatus() {
      try {
        const res = await fetch(`${apiBase}/api/metrics/live/apps_status`);
        if (res.ok) {
          const data = await res.json();
          if (Array.isArray(data) && data.length > 0) {
            liveAppsStatus.value = data;
            // 纯粹更新状态，严禁私自篡改用户手动选中的矿山应用
          }
        }
      } catch (e) {
        // ignore
      }
    }

    async function loadLiveAmbientHistory(appName, spanHours = 24) {
      if (!appName) appName = liveSelectedApp.value;
      try {
        const res = await fetch(`${apiBase}/api/metrics/live/history?app_name=${appName}&hours=${spanHours}&limit=1000`);
        if (res.ok) {
          const list = await res.json();
          if (Array.isArray(list) && list.length > 0) {
            liveHistory = list;
            resetChartsData(list);
            return;
          }
        }
      } catch (e) {
        console.warn('获取环境历史时序异常:', e);
      }
      if (activeTaskId.value === '__live__') {
        initCharts(true);
      }
    }

    function getAppShortName(appKey) {
      const shortMap = {
        zhaiwan: '寨湾',
        liwutong: '里伍铜',
        tianrui: '天瑞'
      };
      if (shortMap[appKey]) return shortMap[appKey];
      const found = (options.apps || []).find(a => a.key === appKey);
      if (found && found.name) {
        return found.name.replace(/矿山.*$/, '').replace(/\(.*?\)/, '').trim() || found.name;
      }
      return appKey || '';
    }

    async function changeLiveApp(appName) {
      if (!appName) return;
      liveSelectedApp.value = appName;
      taskForm.app_name = appName;
      taskForm.explore_context = `docs/explore_rules_${appName}.md`;
      // 永久持久化至本地存储，保障页面刷新绝对不飘移
      localStorage.setItem('vision_platform_app_name', appName);

      if (taskForm.name && /^【.*?】/.test(taskForm.name)) {
        const shortName = getAppShortName(appName);
        taskForm.name = taskForm.name.replace(/^【.*?】\s*/, `【${shortName}】`);
      }
      await loadLiveAmbientHistory(appName, getSpanHours(liveTimeSpan.value));
      await fetchLiveSnapshot();
    }

    async function changeLiveTimeSpan(span) {
      liveTimeSpan.value = span;
      await loadLiveAmbientHistory(liveSelectedApp.value, getSpanHours(span));
    }

    async function fetchLiveSnapshot() {

      try {

        const targetApp = (activeTaskId.value === '__live__') ? liveSelectedApp.value : taskForm.app_name;
        if (!targetApp) return;

        const res = await fetch(`${apiBase}/api/metrics/live/snapshot?app_name=${targetApp}`);

        const data = await res.json();

        Object.assign(liveSnapshot, data);



        const point = {

          timestamp: data.timestamp || new Date().toISOString(),

          dom_count: data.dom_count || 0,

          listeners_count: data.listeners_count || 0,

          js_heap_mb: data.js_heap_mb || 0,

          ue_cpu_percent: data.ue_cpu_percent || 0,

          ue_memory_mb: data.ue_memory_mb || 0,

          ue_commit_mb: data.ue_commit_mb || 0,

          host_ram_load_percent: data.host_ram_load_percent || 0,

          host_commit_load_percent: data.host_commit_load_percent || 0,

          webrtc_fps: (data.webrtc_fps !== null && data.webrtc_fps !== undefined) ? data.webrtc_fps : (data.gpu_usage_percent || 0)

        };



        // 无论当前是否停留在 monitor 大屏，后台常驻记录实时心电点 (最多保留前 15 分钟/225 点)

        liveHistory.push(point);

        if (liveHistory.length > 17280) {

          liveHistory.shift();

        }



        // 如果当前正处于【本机物理环境实时心电图模式】，向折线图实时推入动态打点

        if (activeTaskId.value === '__live__') {

          appendMetricToCharts(point, 17280);

        }

      } catch (e) {

        console.error('获取实时快照失败:', e);

      }

    }



    async function fetchTasks() {

      try {

        const res = await fetch(`${apiBase}/api/tasks?limit=200`);

        tasks.value = await res.json();
        if (taskPage.value > totalTaskPages.value) {
          taskPage.value = totalTaskPages.value;
          taskPageJump.value = totalTaskPages.value;
        }

        if (!activeTaskId.value) {

          activeTaskId.value = '__live__';

        } else if (activeTaskId.value !== '__live__') {

          activeTask.value = tasks.value.find(t => t.id === activeTaskId.value) || activeTask.value;

        }

      } catch (e) {

        console.error('获取任务列表失败:', e);

      }

    }



    function onBugSearchInput() {

      if (bugSearchTimer) clearTimeout(bugSearchTimer);

      bugSearchTimer = setTimeout(() => {
        bugPage.value = 1;
        bugPageJump.value = 1;
        fetchBugs();
      }, 250);

    }



    async function fetchBugs(options = {}) {

      try {
        if (options && options.resetPage) {
          bugPage.value = 1;
          bugPageJump.value = 1;
        }

        if (bugAbortController) {

          try { bugAbortController.abort(); } catch (_) { }

        }

        bugAbortController = new AbortController();



        isBugsLoading.value = true;

        let url = `${apiBase}/api/bugs?page=${bugPage.value}&page_size=${bugPageSize.value}`;

        if (options && options.sync) url += `&sync=true`;

        if (bugAppFilter.value) url += `&app_name=${encodeURIComponent(bugAppFilter.value)}`;

        if (bugSeverityFilter.value) url += `&severity=${encodeURIComponent(bugSeverityFilter.value)}`;

        if (bugAssigneeFilter.value) url += `&assignee=${encodeURIComponent(bugAssigneeFilter.value)}`;

        if (bugStatusFilter.value) url += `&status=${encodeURIComponent(bugStatusFilter.value)}`;

        if (bugOccurrencesFilter.value) url += `&occurrences_range=${encodeURIComponent(bugOccurrencesFilter.value)}`;

        if (bugSearch.value && bugSearch.value.trim()) url += `&search=${encodeURIComponent(bugSearch.value.trim())}`;



        const res = await fetch(url, { signal: bugAbortController.signal });

        if (!res.ok) throw new Error(`HTTP ${res.status}`);

        const data = await res.json();
        if (Array.isArray(data)) {
          // 容错: 兼容旧版数组
          bugs.value = data;
          totalBugs.value = data.length;
        } else {
          bugs.value = data.items || [];
          totalBugs.value = data.total || 0;
          if (data.page) {
            bugPage.value = data.page;
            bugPageJump.value = data.page;
          }
        }
        if (bugPage.value > totalBugPages.value) {
          bugPage.value = totalBugPages.value;
          bugPageJump.value = totalBugPages.value;
        }

      } catch (e) {

        if (e.name === 'AbortError') return;

        console.error('获取缺陷列表失败:', e);

      } finally {

        isBugsLoading.value = false;

      }

    }



    function resetBugFilters() {

      if (bugSearchTimer) clearTimeout(bugSearchTimer);

      bugSearch.value = '';

      bugAppFilter.value = '';

      bugSeverityFilter.value = '';

      bugAssigneeFilter.value = '';

      bugStatusFilter.value = '';

      bugOccurrencesFilter.value = '';
      bugPage.value = 1;
      bugPageJump.value = 1;
      fetchBugs();

    }



    // =========================================================================

    // 预设任务一键执行与载入

    // =========================================================================



    async function launchPreset(preset) {
      if (!await showConfirm({
        title: '确认拉起预设',
        message: `确定要立即拉起预设巡检任务【${preset.title}】吗？`,
        confirmText: '立即拉起',
        icon: '🚀'
      })) return;

      try {
        const res = await fetch(`${apiBase}/api/tasks/presets/${preset.id}/launch`, { method: 'POST' });
        if (res.ok) {
          const newTask = await res.json();
          await fetchTasks();
          activeTaskId.value = newTask.id;
          activeTask.value = newTask;
          currentTab.value = 'monitor';
          connectTaskChannels(newTask.id);
        } else {
          showToast('拉起失败', '拉起预设任务失败: ' + (await res.text()), 'error');
        }
      } catch (e) {
        showToast('启动异常', '启动异常: ' + e, 'error');
      }
    }



    function loadPresetToForm(preset) {
      taskForm.preset_id = preset.id;
      taskForm.preset_title = preset.title;

      // 1. 还原预设名称
      taskForm.name = preset.title || '';

      // 2. 联动预设的目标矿山
      if (preset.app_name) {
        changeLiveApp(preset.app_name);
      }

      // 3. 模式与目标
      if (preset.mode === 'smoke' || preset.tour) {
        taskForm.mode = 'smoke';
        taskForm.tour = true;
      } else if (preset.mode === 'case') {
        taskForm.mode = 'case';
        taskForm.tour = false;
      } else {
        taskForm.mode = 'explore';
        taskForm.tour = false;
      }
      taskForm.macro_objective = (taskForm.mode === 'smoke') ? '' : (preset.macro_objective || '');
      taskForm.max_steps = preset.max_steps;
      taskForm.max_times = preset.max_times;
      taskForm.reset_memory = preset.reset_memory;
      taskForm.ignore_errors = preset.ignore_errors;
      taskForm.case_path = preset.case_path || '';
      taskForm.resume_from = preset.resume_from || '';
      taskForm.reexplore = preset.reexplore || '';
      taskForm.start_delay = preset.start_delay != null ? preset.start_delay : null;
      taskForm.wait_ready = preset.wait_ready || '';
      taskForm.wait_timeout = preset.wait_timeout != null ? preset.wait_timeout : 60;
      taskForm.ignore_env_check = !!preset.ignore_env_check;
      if (taskForm.resume_from || taskForm.reexplore || taskForm.start_delay || taskForm.wait_ready || taskForm.ignore_env_check) {
        taskForm.show_advanced = true;
      }

      // 唤起自定义任务微调弹窗
      taskModalVisible.value = true;
    }

    function enqueuePreset(preset) {
      openCreateScheduleModal(preset);
    }



    async function saveCurrentFormAsPreset(overwriteExisting = false) {
      let title = '';
      if (overwriteExisting && taskForm.preset_id) {
        // 覆盖模式：优先直接读取用户在表单【任务名称】中修改好的新名称，若为空则保留原预设标题
        title = (taskForm.name && taskForm.name.trim()) || taskForm.preset_title || '定制巡检预设';
      } else {
        // 保存为新预设：若表单中已输入任务名称，直接作为预设标题，不再二次弹窗；只有完全未填写时才轻量询问
        if (taskForm.name && taskForm.name.trim()) {
          title = taskForm.name.trim();
        } else {
          title = await showPrompt({
            title: '保存定制预设',
            message: '请输入要保存的预设任务名称:',
            defaultValue: '我的定制巡检预设',
            placeholder: '请输入预设名称...',
            icon: '💾'
          });
          if (!title) return;
        }
      }

      const isSmoke = taskForm.mode === 'smoke';
      const payload = {
        id: (overwriteExisting && taskForm.preset_id) ? taskForm.preset_id : null,
        title: title,
        app_name: taskForm.app_name,
        mode: isSmoke ? 'smoke' : taskForm.mode,
        badge: isSmoke ? '冒烟' : '自定义',
        macro_objective: isSmoke ? '' : taskForm.macro_objective,
        max_steps: isSmoke ? (Number(taskForm.max_steps) || 0) : (Number(taskForm.max_steps) || 200),
        max_times: Number(taskForm.max_times) || 60,
        reset_memory: taskForm.reset_memory,
        ignore_errors: taskForm.ignore_errors,
        case_path: taskForm.mode === 'case' ? (taskForm.case_path || null) : null,
        tour: isSmoke,
        resume_from: taskForm.resume_from || null,
        reexplore: taskForm.reexplore || null,
        start_delay: taskForm.start_delay,
        wait_ready: taskForm.wait_ready || null,
        wait_timeout: taskForm.wait_timeout,
        ignore_env_check: taskForm.ignore_env_check,
        description: taskForm.description || ''
      };

      try {
        const res = await fetch(`${apiBase}/api/tasks/presets`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload)
        });
        if (res.ok) {
          const saved = await res.json();
          taskForm.preset_id = saved.id;
          taskForm.preset_title = saved.title;
          taskForm.name = saved.title;
          taskModalVisible.value = false;
          showToast(
            overwriteExisting ? '预设已成功覆盖' : '新预设已保存',
            `预设【<strong>${saved.title}</strong>】${overwriteExisting ? '覆盖更新' : '固化'}成功！已稳定保存在预设库。`,
            'success',
            5000
          );
          await fetchPresetTasks();
        } else {
          showToast('保存预设失败', await res.text(), 'error', 6000);
        }
      } catch (e) {
        showToast('保存预设异常', String(e), 'error', 6000);
      }
    }



    async function deletePreset(preset) {
      if (!await showConfirm({
        title: '删除预设确认',
        message: `确定要彻底删除预设【${preset.title}】吗？\n删除后将无法恢复。`,
        confirmText: '彻底删除',
        danger: true,
        icon: '🗑️'
      })) return;
      try {
        const res = await fetch(`${apiBase}/api/tasks/presets/${preset.id}`, { method: 'DELETE' });
        if (res.ok) {
          showToast('已删除预设', `预设【${preset.title}】已从预设库中移除`, 'info', 4000);
          if (taskForm.preset_id === preset.id) {
            taskForm.preset_id = null;
            taskForm.preset_title = '';
          }
          await fetchPresetTasks();
        } else {
          showToast('删除预设失败', await res.text(), 'error', 6000);
        }
      } catch (e) {
        showToast('删除预设异常', String(e), 'error', 6000);
      }
    }



    // =========================================================================

    // 任务操作

    // =========================================================================



    function applyTemplate(tpl) {

      taskForm.macro_objective = tpl.prompt;

    }



    async function submitCreateTask() {

      try {

        if (!taskForm.name) {

          taskForm.name = `巡检任务 - ${taskForm.app_name} (${new Date().toLocaleTimeString()})`;

        }

        const isSmoke = taskForm.mode === 'smoke';
        const payload = {
          name: taskForm.name,
          app_name: taskForm.app_name,
          mode: isSmoke ? 'smoke' : taskForm.mode,
          tour: isSmoke || (taskForm.mode === 'explore' && !!taskForm.tour),
          case_path: taskForm.mode === 'case' ? (taskForm.case_path || null) : null,
          macro_objective: isSmoke ? '' : taskForm.macro_objective,
          max_steps: isSmoke ? (Number(taskForm.max_steps) || 0) : (Number(taskForm.max_steps) || 200),
          max_times: Number(taskForm.max_times) || 60,
          reset_memory: taskForm.reset_memory,
          ignore_errors: taskForm.ignore_errors,
          explore_context: `docs/explore_rules_${taskForm.app_name}.md`,
          resume_from: taskForm.resume_from || null,
          reexplore: taskForm.reexplore || null,
          start_delay: taskForm.start_delay,
          wait_ready: taskForm.wait_ready || null,
          wait_timeout: taskForm.wait_timeout,
          ignore_env_check: taskForm.ignore_env_check,
        };

        const res = await fetch(`${apiBase}/api/tasks`, {

          method: 'POST',

          headers: { 'Content-Type': 'application/json' },

          body: JSON.stringify(payload)

        });

        if (res.ok) {

          const newTask = await res.json();

          await fetchTasks();

          activeTaskId.value = newTask.id;

          activeTask.value = newTask;

          taskModalVisible.value = false;

          currentTab.value = 'monitor';

          startTask(newTask.id);

        } else {
          showToast('创建任务失败', await res.text(), 'error');
        }
      } catch (e) {
        showToast('创建任务异常', String(e), 'error');
      }
    }

    async function startTask(taskId) {
      try {
        const res = await fetch(`${apiBase}/api/tasks/${taskId}/start`, { method: 'POST' });
        const data = await res.json();
        if (res.ok) {
          await fetchTasks();
          connectTaskChannels(taskId);
        } else {
          showToast('启动任务失败', data.detail || '启动失败', 'error');
        }
      } catch (e) {
        showToast('启动任务异常', String(e), 'error');
      }
    }

    async function stopTask(taskId) {
      if (!await showConfirm({
        title: '终止任务确认',
        message: '确定要终止当前任务吗？底座将优雅退出进程树。',
        confirmText: '立即终止',
        danger: true,
        icon: '🛑'
      })) return;
      try {
        const res = await fetch(`${apiBase}/api/tasks/${taskId}/stop`, { method: 'POST' });
        if (res.ok) {
          showToast('已终止', '任务已安全终止并归档', 'info');
        }
        await Promise.all([fetchTasks(), fetchTaskQueue()]);
      } catch (e) {
        showToast('终止任务异常', String(e), 'error');
      }
    }

    const deletingTaskId = ref(null);

    async function deleteTaskRun(task) {
      if (!task || !task.id) return;
      if (task.status === 'running') {
        showToast('无法删除', '该任务当前正在运行中，请先点击【终止】停止任务后再删除！', 'warning');
        return;
      }

      // 安全防线 1: 若任务包含已提禅道或较多 Bug，提供醒目预警
      let force = false;
      const bugCount = task.bugs_count || 0;
      let promptMsg = `确定要彻底删除任务【${task.name}】(${task.id}) 吗？\n\n⚠️ 将同时从数据库中注销，并彻底物理清理磁盘产物目录！`;

      if (bugCount > 0) {
        promptMsg += `\n\n🚨 注意：该任务关联了 ${bugCount} 条缺陷记录！若其中已有提交至禅道的缺陷，已提交缺陷将予以保留，其余本地草稿证据将被物理删除。`;
      }

      if (!await showConfirm({
        title: '彻底删除任务',
        message: promptMsg,
        danger: true,
        confirmText: '彻底删除',
        icon: '🗑️'
      })) return;

      deletingTaskId.value = task.id;
      try {
        let url = `${apiBase}/api/tasks/${task.id}?cleanup_disk=true`;
        let res = await fetch(url, { method: 'DELETE' });

        if (res.status === 409) {
          // 命中已提禅道的高危拦截
          const errData = await res.json();
          const detail = errData.detail || '任务包含已提交禅道的缺陷';
          if (await showConfirm({
            title: '高危强制删除确认',
            message: `${detail}\n\n是否仍然确认强制删除该任务的本地物理产物？(强制删除不会删除禅道上的单据)`,
            danger: true,
            confirmText: '强制删除',
            icon: '⚠️'
          })) {
            url += '&force=true';
            res = await fetch(url, { method: 'DELETE' });
          } else {
            deletingTaskId.value = null;
            return;
          }
        }

        if (res.ok) {
          const data = await res.json();
          // 1. 率先从本地列表中剔除该项，实现即时无感刷新
          tasks.value = tasks.value.filter(t => t.id !== task.id);

          // 2. 现代 Toast 通知替代原生 alert 弹窗
          showToast(
            '任务已彻底清理',
            `任务【<strong>${task.name}</strong>】已彻底清理完毕！${data.deleted_disk_path ? '<br><small style="opacity:0.8">已抹除磁盘产物目录</small>' : ''}`,
            'success',
            4500
          );

          // 若当前监控选中了被删除的任务，重置回环境监控
          if (activeTaskId.value === task.id) {
            switchToLiveMonitor();
          }
          // 异步静默二次校验拉取最新任务库
          fetchTasks();
        } else {
          const errText = await res.text();
          showToast('删除任务失败', errText, 'error', 6000);
        }
      } catch (e) {
        showToast('删除任务网络异常', String(e), 'error', 6000);
      } finally {
        deletingTaskId.value = null;
      }
    }



    // =========================================================================
    // RPA 执行器：调度执行队列操作
    // =========================================================================

    async function fetchTaskQueue() {
      try {
        const res = await fetch(`${apiBase}/api/tasks/queue?limit=50`);
        if (res.ok) {
          taskQueue.value = await res.json();
          pendingQueueCount.value = taskQueue.value.filter(q => q.status === 'pending').length;
        }
      } catch (e) {
        console.warn('获取调度队列异常:', e);
      }
    }

    function formatPriorityLabel(p) {
      if (p === 1 || p === 10) return { text: 'P1 (紧急)', color: '#ff5252', bg: 'rgba(255, 82, 82, 0.15)' };
      if (p === 2 || p === 50) return { text: 'P2 (优先)', color: '#ffb300', bg: 'rgba(255, 179, 0, 0.15)' };
      if (p === 3 || p === 100) return { text: 'P3 (标准)', color: '#00d2ff', bg: 'rgba(0, 210, 255, 0.15)' };
      if (p === 4 || p === 200) return { text: 'P4 (低)', color: '#8b9bb4', bg: 'rgba(139, 155, 180, 0.15)' };
      return { text: `P${p}`, color: '#00d2ff', bg: 'rgba(0, 210, 255, 0.15)' };
    }

    function formatTaskStatus(status) {
      const map = {
        running: '🚀 执行中',
        completed: '✅ 已完成',
        failed: '❌ 执行失败',
        stopped: '🛑 已手动终止',
        pending: '⏳ 排队等待',
        canceled: '🛑 已取消'
      };
      return map[status] || status || '-';
    }

    function formatTaskMode(mode) {
      const map = {
        explore: '自主探索',
        smoke: '极速冒烟',
        case: '用例回归',
        all: '全域巡检'
      };
      return map[mode] || mode || '-';
    }

    function formatWeekdays(spec) {
      if (!spec) return '一';
      const dayNames = { 1: '一', 2: '二', 3: '三', 4: '四', 5: '五', 6: '六', 7: '日' };
      return String(spec).split(',').map(x => dayNames[x.trim()] || x.trim()).join('、');
    }

    function setCurrentExecutionTime() {
      const now = new Date();
      const h = String(now.getHours()).padStart(2, '0');
      const m = String(now.getMinutes()).padStart(2, '0');
      const s = String(now.getSeconds()).padStart(2, '0');
      scheduleForm.executionTime = `${h}:${m}:${s}`;
    }

    function getCleanPresetScheduleName(appName, presetTitle) {
      const shortName = getAppShortName(appName);
      const cleanTitle = (presetTitle || '定时巡检计划').replace(/^【.*?】\s*/, '').trim();
      return `【${shortName}】${cleanTitle}`;
    }

    function openCreateScheduleModal(preset = null) {
      scheduleForm.id = '';
      scheduleModalTab.value = 'basic';
      const today = new Date();
      const Y = today.getFullYear();
      const M = String(today.getMonth() + 1).padStart(2, '0');
      const D = String(today.getDate()).padStart(2, '0');
      const todayStr = `${Y}-${M}-${D}`;

      if (preset && preset.app_name) {
        scheduleForm.app_name = preset.app_name;
        scheduleForm.preset_id = preset.id;
        scheduleForm.name = getCleanPresetScheduleName(preset.app_name, preset.title);
      } else {
        scheduleForm.app_name = taskForm.app_name || (options.apps && options.apps[0]?.key) || storedApp;
        const appPresets = (presetTasks.value || []).filter(p => p.app_name === scheduleForm.app_name);
        if (appPresets.length > 0) {
          scheduleForm.preset_id = appPresets[0].id;
          scheduleForm.name = getCleanPresetScheduleName(scheduleForm.app_name, appPresets[0].title);
        } else {
          scheduleForm.preset_id = '';
          scheduleForm.name = getCleanPresetScheduleName(scheduleForm.app_name, '定时巡检计划');
        }
      }
      scheduleForm.priority = 2; // 默认高优先级
      scheduleForm.startDate = todayStr;
      scheduleForm.endDate = todayStr;
      scheduleForm.executionTime = '18:35:00';
      scheduleForm.endTime = '23:59:59';
      scheduleForm.cron_mode = 'daily';
      scheduleForm.minuteInterval = 30;
      scheduleForm.hourInterval = 2;
      scheduleForm.dailyInterval = 1;
      scheduleForm.weeklyDays = [1, 2, 3, 4, 5];
      scheduleForm.monthlyDay = 1;
      scheduleForm.conflict_policy = 'wait';
      scheduleForm.auto_retry = 0;
      scheduleForm.ignore_env_check = 0;
      scheduleForm.is_active = 1;
      showEnqueueModal.value = true;
    }

    function openEditScheduleModal(plan) {
      scheduleForm.id = plan.id;
      scheduleModalTab.value = 'basic';
      scheduleForm.name = plan.name || plan.task_name || '';
      scheduleForm.app_name = plan.app_name || 'zhaiwan';
      scheduleForm.preset_id = plan.preset_id || '';
      scheduleForm.priority = plan.priority || 2;
      scheduleForm.startDate = plan.start_date || '';
      scheduleForm.endDate = plan.end_date || '';
      scheduleForm.executionTime = plan.start_time || '18:35:00';
      scheduleForm.endTime = plan.end_time || '23:59:59';
      scheduleForm.cron_mode = plan.cron_mode || 'daily';
      scheduleForm.conflict_policy = plan.conflict_policy || 'wait';
      scheduleForm.auto_retry = plan.auto_retry ? 1 : 0;
      scheduleForm.ignore_env_check = plan.ignore_env_check ? 1 : 0;
      scheduleForm.is_active = plan.is_active !== undefined ? plan.is_active : 1;

      // 解析周期规则
      const spec = plan.cron_spec || '';
      if (scheduleForm.cron_mode === 'minute') {
        scheduleForm.minuteInterval = parseInt(spec, 10) || 30;
      } else if (scheduleForm.cron_mode === 'hour') {
        scheduleForm.hourInterval = parseInt(spec, 10) || 2;
      } else if (scheduleForm.cron_mode === 'daily') {
        scheduleForm.dailyInterval = parseInt(spec, 10) || 1;
      } else if (scheduleForm.cron_mode === 'weekly') {
        const days = spec.split(',').map(x => parseInt(x.trim(), 10)).filter(x => !isNaN(x) && x >= 1 && x <= 7);
        scheduleForm.weeklyDays = days.length > 0 ? days : [1, 2, 3, 4, 5];
      } else if (scheduleForm.cron_mode === 'monthly') {
        scheduleForm.monthlyDay = parseInt(spec, 10) || 1;
      }

      showEnqueueModal.value = true;
    }

    function onScheduleAppChange() {
      const appPresets = (presetTasks.value || []).filter(p => p.app_name === scheduleForm.app_name);
      if (appPresets.length > 0) {
        scheduleForm.preset_id = appPresets[0].id;
        scheduleForm.name = getCleanPresetScheduleName(scheduleForm.app_name, appPresets[0].title);
      } else {
        scheduleForm.preset_id = '';
        scheduleForm.name = getCleanPresetScheduleName(scheduleForm.app_name, '定时巡检计划');
      }
    }

    function onSchedulePresetChange() {
      const found = (presetTasks.value || []).find(p => p.id === scheduleForm.preset_id);
      if (found) {
        scheduleForm.name = getCleanPresetScheduleName(scheduleForm.app_name, found.title);
      }
    }

    async function confirmCreateSchedulePlan() {
      if (!scheduleForm.preset_id) {
        showToast('请选择关联任务', '必须选择一个预设巡检任务模板作为执行规则', 'warning', 4000);
        return;
      }
      isSubmittingEnqueue.value = true;
      try {
        let cronSpecStr = '1';
        if (scheduleForm.cron_mode === 'minute') {
          cronSpecStr = String(scheduleForm.minuteInterval || 30);
        } else if (scheduleForm.cron_mode === 'hour') {
          cronSpecStr = String(scheduleForm.hourInterval || 1);
        } else if (scheduleForm.cron_mode === 'daily') {
          cronSpecStr = String(scheduleForm.dailyInterval || 1);
        } else if (scheduleForm.cron_mode === 'weekly') {
          const days = (scheduleForm.weeklyDays || [1]).slice().sort((a,b) => a-b);
          cronSpecStr = days.join(',');
        } else if (scheduleForm.cron_mode === 'monthly') {
          cronSpecStr = String(scheduleForm.monthlyDay || 1);
        }

        const payload = {
          name: scheduleForm.name,
          app_name: scheduleForm.app_name,
          preset_id: scheduleForm.preset_id,
          priority: scheduleForm.priority,
          start_date: scheduleForm.startDate || '',
          end_date: scheduleForm.endDate || '',
          start_time: scheduleForm.executionTime || '18:35:00',
          end_time: scheduleForm.endTime || '23:59:59',
          cron_mode: scheduleForm.cron_mode,
          cron_spec: cronSpecStr,
          conflict_policy: scheduleForm.conflict_policy || 'wait',
          auto_retry: scheduleForm.auto_retry ? 1 : 0,
          ignore_env_check: scheduleForm.ignore_env_check ? 1 : 0,
          is_active: scheduleForm.is_active ? 1 : 0
        };

        let res;
        if (scheduleForm.id) {
          res = await fetch(`${apiBase}/api/tasks/queue/schedule/${scheduleForm.id}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
          });
        } else {
          res = await fetch(`${apiBase}/api/tasks/queue/schedule`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
          });
        }

        if (res.ok) {
          showEnqueueModal.value = false;
          showToast(
            '调度计划已保存',
            `计划【<strong>${scheduleForm.name}</strong>】已成功配置并生效！`,
            'success',
            5000
          );
          await fetchTaskQueue();
          currentTab.value = 'tasks';
          assetsSubTab.value = 'queue';
        } else {
          showToast('保存调度计划失败', await res.text(), 'error', 6000);
        }
      } catch (e) {
        showToast('保存调度计划异常', String(e), 'error', 6000);
      } finally {
        isSubmittingEnqueue.value = false;
      }
    }

    async function toggleScheduleActive(plan) {
      try {
        const res = await fetch(`${apiBase}/api/tasks/queue/schedule/${plan.id}/toggle`, { method: 'POST' });
        let data = null;
        try {
          data = await res.json();
        } catch (_) {
          data = null;
        }
        if (res.ok) {
          showToast('状态已更新', (data && data.message) || '操作成功', 'success', 3500);
          await fetchTaskQueue();
        } else {
          showToast('无法切换状态', (data && data.detail) || '启用/停用调度计划失败', 'warning', 5000);
        }
      } catch (e) {
        showToast('请求异常', String(e), 'error', 4000);
      }
    }

    async function runScheduleNow(plan) {
      if (!await showConfirm({
        title: '手动触发调度确认',
        message: `确定要立即手动执行一次调度计划【${plan.name || plan.task_name}】吗？`,
        confirmText: '立即执行',
        icon: '⚡'
      })) return;
      try {
        const res = await fetch(`${apiBase}/api/tasks/queue/schedule/${plan.id}/run_now`, { method: 'POST' });
        if (res.ok) {
          const data = await res.json();
          showToast('已下发执行', data.message, 'success', 5000);
          await fetchTaskQueue();
          await fetchTasks();
        } else {
          showToast('下发失败', await res.text(), 'error', 5000);
        }
      } catch (e) {
        showToast('执行异常', String(e), 'error', 5000);
      }
    }

    async function deleteSchedule(plan) {
      if (!await showConfirm({
        title: '删除调度计划确认',
        message: `确定要彻底删除该调度计划【${plan.name || plan.task_name || plan.id}】吗？\n删除后周期巡检将终止。`,
        confirmText: '彻底删除',
        danger: true,
        icon: '🗑️'
      })) return;
      try {
        const res = await fetch(`${apiBase}/api/tasks/queue/${plan.id}`, { method: 'DELETE' });
        if (res.ok) {
          showToast('已删除', '调度计划已成功删除', 'info', 3000);
          await fetchTaskQueue();
        } else {
          showToast('删除失败', await res.text(), 'error');
        }
      } catch (e) {
        showToast('删除异常', String(e), 'error');
      }
    }

    async function removeFromQueue(queueItem) {
      return deleteSchedule(queueItem);
    }




    function onMonitorTargetChange() {

      if (activeTaskId.value === '__live__' || !activeTaskId.value) {

        switchToLiveMonitor();

      } else {

        const t = tasks.value.find(item => item.id === activeTaskId.value);

        if (t) {

          switchActiveTask(t);

        }

      }

    }



    function switchToLiveMonitor() {

      activeTaskId.value = '__live__';

      activeTask.value = null;

      if (logWs) { logWs.close(); logWs = null; }

      if (metricWs) { metricWs.close(); metricWs = null; }



      terminalLogs.value = [

        `[${new Date().toLocaleTimeString()}] ⚡ 进入【本机物理环境实时心电图模式】`,

        `[${new Date().toLocaleTimeString()}] 📡 无需启动任何测试任务，只读探针正在每 4 秒采集一次 UE5、Chromium、CDP 与 NVIDIA GPU 即时切片并绘制实时动态曲线...`

      ];



      // 切换到 Live 模式：优先向服务端拉取 24 小时真实历史切片，瞬间灌满图表
      loadLiveAmbientHistory(liveSelectedApp.value, getSpanHours(liveTimeSpan.value));

    }



    function switchActiveTask(t) {

      if (!t) return;

      activeTaskId.value = t.id;

      activeTask.value = t;

      connectTaskChannels(t.id);

    }

    async function jumpToBugMonitor(bug) {
      if (!bug) return;
      const findMatch = () => (tasks.value || []).find(t =>
        (bug.task_id && t.id === bug.task_id) ||
        (bug.run_id && t.run_dir && t.run_dir.includes(bug.run_id))
      );

      let matched = findMatch();
      if (!matched) {
        await fetchTasks();
        matched = findMatch();
      }

      if (matched) {
        selectedBug.value = null;
        currentTab.value = 'monitor';
        switchActiveTask(matched);
      } else {
        showToast(
          '⚠️ 未找到关联任务',
          `未在任务列表中找到该缺陷关联的运行批次 (${bug.task_id || bug.run_id || '未知'})，可能已被清理。`,
          'warning',
          4500
        );
      }
    }



    // =========================================================================

    // WebSocket 推流 (日志与时序性能)

    // =========================================================================



    function connectTaskChannels(taskId) {

      if (!taskId || taskId === '__live__') return;



      // 1. 关闭已有 WS

      if (logWs) { logWs.close(); logWs = null; }

      if (metricWs) { metricWs.close(); metricWs = null; }



      terminalLogs.value = [];

      initCharts(true); // 切换不同任务时清空旧任务的数据



      // 2. 建立日志流 WS

      const wsProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';

      const logWsUrl = `${wsProtocol}//${window.location.host}/ws/tasks/${taskId}/logs`;



      logWs = new WebSocket(logWsUrl);

      logWs.onmessage = (event) => {

        terminalLogs.value.push(event.data);

        if (terminalLogs.value.length > 3000) {

          terminalLogs.value.shift();

        }

        scrollTerminalToBottom();

      };



      // 3. 建立指标流 WS

      const metricWsUrl = `${wsProtocol}//${window.location.host}/ws/tasks/${taskId}/metrics`;

      metricWs = new WebSocket(metricWsUrl);

      metricWs.onmessage = (event) => {

        try {

          const m = JSON.parse(event.data);

          appendMetricToCharts(m);

        } catch (e) {

          console.error('解析性能推流异常:', e);

        }

      };



      // 4. 加载历史指标初始化图表 (智能降采样支撑 12 小时全生命周期无截断)

      loadHistoricalMetrics(taskId);

    }



    async function loadHistoricalMetrics(taskId) {

      if (!taskId || taskId === '__live__') return;

      try {

        const res = await fetch(`${apiBase}/api/metrics/${taskId}?limit=1000`);

        const list = await res.json();

        if (list && list.length > 0) {

          resetChartsData(list);

        }

      } catch (e) {

        console.error('加载历史指标失败:', e);

      }

    }



    function scrollTerminalToBottom() {

      nextTick(() => {

        const term = document.getElementById('terminalWindow');

        if (term) {

          term.scrollTop = term.scrollHeight;

        }

      });

    }



    // =========================================================================

    // ECharts 图表渲染

    // =========================================================================



    // 实时心电图独立数据队列 (前端常驻维护，最多保留前 15 分钟/225个已采集点；有值就回溯渲染，没值就空开局)

    let liveHistory = [];



    // 当前图表正在展示的数据缓冲 (由 resetChartsData 或 liveHistory 驱动)

    let chartTimes = [];

    let domData = [];

    let listenersData = [];

    let jsHeapData = [];

    let ueCpuData = [];

    let ueMemData = [];

    let ueCommitData = [];

    let webrtcFpsData = [];



    function initCharts(forceClear = false) {

      nextTick(() => {

        const domEl = document.getElementById('domChart');

        const ueEl = document.getElementById('ueChart');

        if (!domEl || !ueEl || !echarts) return;



        // 如果图表已存在且不需要强制清空重建，仅自适应容器尺寸并保持已有数据

        if (domChart && ueChart && !forceClear) {

          domChart.resize();

          ueChart.resize();

          return;

        }



        if (domChart) domChart.dispose();

        if (ueChart) ueChart.dispose();



        chartTimes = [];

        domData = [];

        listenersData = [];

        jsHeapData = [];

        ueCpuData = [];

        ueMemData = [];

        ueCommitData = [];

        webrtcFpsData = [];



        // 统一 DataZoom 缩放手柄与滚轮交互 (支持随意拖动观察全天 12 小时或放大至分钟级)

        const commonDataZoom = [

          { type: 'inside', start: 0, end: 100 },

          {

            type: 'slider',

            start: 0,

            end: 100,

            height: 18,

            bottom: 4,

            borderColor: '#1a253c',

            fillerColor: 'rgba(0, 210, 255, 0.15)',

            handleStyle: { color: '#00d2ff' },

            textStyle: { color: '#8b9bb4', fontSize: 11 }

          }

        ];



        // DOM / Heap 图表

        domChart = echarts.init(domEl);

        domChart.setOption({

          title: { text: 'Chrome 渲染端指标 (DOM / Listeners / JSHeap)', textStyle: { color: '#8b9bb4', fontSize: 13 } },

          tooltip: { trigger: 'axis' },

          legend: { data: ['DOM 节点数', '事件监听器', 'V8 JS堆 (MB)'], textStyle: { color: '#8b9bb4' } },

          grid: { left: '3%', right: '4%', bottom: '15%', containLabel: true },

          dataZoom: commonDataZoom,

          xAxis: { type: 'category', data: [], axisLine: { lineStyle: { color: '#233354' } } },

          yAxis: [

            { type: 'value', name: '数量', axisLine: { lineStyle: { color: '#233354' } }, splitLine: { lineStyle: { color: '#131b2e' } } },

            { type: 'value', name: 'MB', axisLine: { lineStyle: { color: '#233354' } }, splitLine: { show: false } }

          ],

          series: [

            { name: 'DOM 节点数', type: 'line', smooth: true, data: [], itemStyle: { color: '#00d2ff' } },

            { name: '事件监听器', type: 'line', smooth: true, data: [], itemStyle: { color: '#9d4edd' } },

            { name: 'V8 JS堆 (MB)', type: 'line', yAxisIndex: 1, smooth: true, data: [], itemStyle: { color: '#ffb300' } }

          ]

        });



        // UE5 引擎与 WebRTC 像素流图表

        ueChart = echarts.init(ueEl);

        ueChart.setOption({

          title: { text: '伴生 UE5 引擎与 WebRTC 像素流 / GPU (CPU / 内存 / FPS)', textStyle: { color: '#8b9bb4', fontSize: 13 } },

          tooltip: { trigger: 'axis' },

          legend: { data: ['UE5 CPU (%)', 'UE5 内存 (MB)', 'WebRTC FPS / GPU (%)'], textStyle: { color: '#8b9bb4' } },

          grid: { left: '3%', right: '4%', bottom: '15%', containLabel: true },

          dataZoom: commonDataZoom,

          xAxis: { type: 'category', data: [], axisLine: { lineStyle: { color: '#233354' } } },

          yAxis: [

            { type: 'value', name: 'CPU / 内存', axisLine: { lineStyle: { color: '#233354' } }, splitLine: { lineStyle: { color: '#131b2e' } } },

            { type: 'value', name: 'FPS / GPU %', max: 100, axisLine: { lineStyle: { color: '#233354' } }, splitLine: { show: false } }

          ],

          series: [

            { name: 'UE5 CPU (%)', type: 'line', smooth: true, data: [], itemStyle: { color: '#ff5252' } },

            { name: 'UE5 RAM物理 (MB)', type: 'line', smooth: true, data: [], itemStyle: { color: '#00e676' } },

            { name: 'UE5 Commit提交 (MB)', type: 'line', smooth: true, data: [], itemStyle: { color: '#ff9100' } },

            { name: 'WebRTC FPS / GPU (%)', type: 'line', yAxisIndex: 1, smooth: true, data: [], itemStyle: { color: '#3a7bd5' } }

          ]

        });

      });

    }



    function parseMetricDate(ts) {

      if (!ts) return new Date();

      if (typeof ts === 'string') {

        let clean = ts.trim();

        // 如果后端传回的 ISO 字符串未标注时区 (如 2026-11-02T10:24:16)，显式附加 'Z' 表示 UTC 零时区

        if (!clean.endsWith('Z') && !clean.includes('+') && clean.includes('T')) {

          clean += 'Z';

        }

        return new Date(clean);

      }

      return new Date(ts);

    }



    function resetChartsData(list) {

      if (!domChart || !ueChart) return;

      chartTimes = list.map(m => parseMetricDate(m.timestamp).toLocaleTimeString());

      domData = list.map(m => m.dom_count);

      listenersData = list.map(m => m.listeners_count);

      jsHeapData = list.map(m => m.js_heap_mb);

      ueCpuData = list.map(m => m.ue_cpu_percent || 0);

      ueMemData = list.map(m => m.ue_memory_mb || 0);

      ueCommitData = list.map(m => m.ue_commit_mb || 0);

      webrtcFpsData = list.map(m => m.webrtc_fps || 0);



      domChart.setOption({

        xAxis: { data: chartTimes },

        series: [{ data: domData }, { data: listenersData }, { data: jsHeapData }]

      });



      ueChart.setOption({

        xAxis: { data: chartTimes },

        series: [{ data: ueCpuData }, { data: ueMemData }, { data: ueCommitData }, { data: webrtcFpsData }]

      });

    }



    function appendMetricToCharts(m, maxPoints = 17280) {

      if (!domChart || !ueChart) return;

      const t = parseMetricDate(m.timestamp).toLocaleTimeString();

      chartTimes.push(t);

      domData.push(m.dom_count);

      listenersData.push(m.listeners_count);

      jsHeapData.push(m.js_heap_mb);

      ueCpuData.push(m.ue_cpu_percent || 0);

      ueMemData.push(m.ue_memory_mb || 0);

      ueCommitData.push(m.ue_commit_mb || 0);

      webrtcFpsData.push(m.webrtc_fps || 0);



      // 默认维持最多 225 个采样点 (4秒一个点即 15 分钟连续滑动窗口)

      if (chartTimes.length > maxPoints) {

        chartTimes.shift();

        domData.shift();

        listenersData.shift();

        jsHeapData.shift();

        ueCpuData.shift();

        ueMemData.shift();

        ueCommitData.shift();

        webrtcFpsData.shift();

      }



      domChart.setOption({

        xAxis: { data: chartTimes },

        series: [{ data: domData }, { data: listenersData }, { data: jsHeapData }]

      });



      ueChart.setOption({

        xAxis: { data: chartTimes },

        series: [{ data: ueCpuData }, { data: ueMemData }, { data: ueCommitData }, { data: webrtcFpsData }]

      });

    }



    // =========================================================================

    // 缺陷管理与禅道同步

    // =========================================================================



    function viewBugDetail(b) {

      selectedBug.value = b;

    }



    const zentaoUsers = ref([]);

    async function fetchZentaoUsers() {
      if (zentaoUsers.value.length > 0) return;
      try {
        const res = await fetch(`${apiBase}/api/zentao/users`);
        if (res.ok) {
          const list = await res.json();
          if (Array.isArray(list) && list.length > 0) {
            zentaoUsers.value = list;
            return;
          }
        }
      } catch (_) {}
      zentaoUsers.value = [
        { account: 'chenyixiong', realname: '陈贻雄' },
        { account: 'meibenxia', realname: '梅本霞' },
        { account: 'liyuncong', realname: '李云骢' },
        { account: 'jinzhengwu', realname: '靳正武' },
      ];
    }

    function openEditBugModal(b) {

      editingBug.value = b;

      editForm.id = b.id;

      editForm.title = b.title || '';

      editForm.severity = b.severity || 'Medium';

      editForm.status = b.status || '激活';

      editForm.assignee = b.assignee || '陈贻雄';

      editForm.zentao_id = b.zentao_id || '';

      editForm.ui_path = b.ui_path || '';

      editForm.analysis_notes = b.analysis_notes || '';

      editForm.remark = b.remark || '';

      fetchZentaoUsers();

    }



    async function submitBugEdit() {

      if (!editingBug.value) return;

      try {

        const payload = {

          title: editForm.title,

          severity: editForm.severity,

          status: editForm.status,

          assignee: editForm.assignee,

          zentao_id: editForm.zentao_id,

          ui_path: editForm.ui_path,

          analysis_notes: editForm.analysis_notes,

          remark: editForm.remark

        };

        const res = await fetch(`${apiBase}/api/bugs/${editingBug.value.id}`, {

          method: 'PUT',

          headers: { 'Content-Type': 'application/json' },

          body: JSON.stringify(payload)

        });

        if (res.ok) {
          const updated = await res.json();
          showToast('修改成功', `缺陷 [${updated.id}] 修改成功！已实时多端同步入库！`, 'success', 4000);

          // 更新前端内存列表
          const idx = bugs.value.findIndex(item => item.id === updated.id);
          if (idx !== -1) {
            bugs.value[idx] = Object.assign(bugs.value[idx], updated);
          }
          if (selectedBug.value && selectedBug.value.id === updated.id) {
            Object.assign(selectedBug.value, updated);
          }
          editingBug.value = null;
        } else {
          showToast('保存失败', await res.text(), 'error');
        }
      } catch (e) {
        showToast('修改缺陷异常', String(e), 'error');
      }

    }



    function formatZenTaoUrl(zentaoId) {

      if (!zentaoId) return '';

      const base = (options.zentao_base_url || 'http://192.140.163.129:8080').replace(/\/+$/, '');

      return `${base}/index.php?m=bug&f=view&bugID=${encodeURIComponent(zentaoId)}`;

    }



    function formatScreenshotUrl(path) {

      if (!path) return '';

      if (path.startsWith('http://') || path.startsWith('https://')) return path;

      const normalized = path.replace(/\\/g, '/');

      const idxReports = normalized.indexOf('/reports/');

      if (idxReports !== -1) {

        return normalized.slice(idxReports);

      }

      const idxArtifacts = normalized.indexOf('/artifacts/');

      if (idxArtifacts !== -1) {

        return normalized.slice(idxArtifacts);

      }

      if (normalized.startsWith('reports/')) {

        return '/' + normalized;

      }

      if (normalized.startsWith('artifacts/')) {

        return '/' + normalized;

      }

      return normalized;

    }



    function formatDateTime(val) {
      if (!val) return '-';
      const str = String(val).replace('T', ' ');
      const matched = str.match(/^(\d{4}-\d{2}-\d{2})\s+(\d{2}:\d{2}:\d{2})/);
      if (matched) {
        return `${matched[1]} ${matched[2]}`;
      }
      return str.split('.')[0] || '-';
    }

    function formatDuration(val) {
      if (!val || val === '未知') return '-';
      if (typeof val === 'string' && (val.includes('h') || val.includes('m') || val.includes('s'))) {
        return val;
      }
      const m = String(val).match(/^(\d+):(\d+):(\d+)$/);
      if (m) {
        const h = parseInt(m[1], 10);
        const mn = parseInt(m[2], 10);
        const s = parseInt(m[3], 10);
        return h > 0 ? `${h}h ${mn}m ${s}s` : `${mn}m ${s}s`;
      }
      return String(val);
    }

    function formatReportUrl(url) {

      if (!url) return '';

      if (url.startsWith('http://') || url.startsWith('https://')) return url;

      let clean = url.replace(/^\.\//, '').replace(/^\//, '');

      if (clean.startsWith('reports/runs/')) {

        return '/' + clean;

      } else if (clean.startsWith('reports/')) {

        return '/' + clean;

      }

      return '/reports/runs/' + clean;

    }

    async function openEnvInfoModal(task) {
      selectedEnvInfo.value = { task_id: task.id, exists: false, env_info: null, raw_json: '' };
      envInfoLoading.value = true;
      envInfoViewMode.value = 'card';
      try {
        const res = await fetch(`${apiBase}/api/tasks/${task.id}/env_info`);
        if (res.ok) {
          selectedEnvInfo.value = await res.json();
        } else {
          selectedEnvInfo.value = { task_id: task.id, exists: false, message: '读取环境快照记录失败' };
        }
      } catch (e) {
        selectedEnvInfo.value = { task_id: task.id, exists: false, message: `网络请求异常: ${e.message}` };
      } finally {
        envInfoLoading.value = false;
      }
    }

    function copyEnvInfoJson() {
      if (!selectedEnvInfo.value || !selectedEnvInfo.value.raw_json) return;
      navigator.clipboard.writeText(selectedEnvInfo.value.raw_json).then(() => {
        showToast({ type: 'success', title: '已复制 JSON', message: '环境基线快照配置已成功复制到剪贴板' });
      }).catch(() => {
        showToast({ type: 'warning', title: '复制失败', message: '请手动选中文本框内容复制' });
      });
    }

    async function fetchCases() {
      isCasesLoading.value = true;
      try {
        const res = await fetch(`${apiBase}/api/cases`);
        if (res.ok) {
          const data = await res.json();
          manualCases.value = data.manual_cases || [];
          autoCases.value = data.auto_cases || [];
        }
      } catch (e) {
        console.error('获取测试用例资产失败:', e);
      } finally {
        isCasesLoading.value = false;
      }
    }

    async function openCasePreview(c) {
      previewingCase.value = c;
      previewCaseLoading.value = true;
      previewCaseContent.value = '';
      try {
        const res = await fetch(`${apiBase}/api/cases/content?path=${encodeURIComponent(c.path)}`);
        if (res.ok) {
          const data = await res.json();
          previewCaseContent.value = data.content || '';
        } else {
          previewCaseContent.value = '# 读取用例源码失败';
        }
      } catch (e) {
        previewCaseContent.value = `# 读取异常: ${e.message}`;
      } finally {
        previewCaseLoading.value = false;
      }
    }

    function copyCaseYaml() {
      if (!previewCaseContent.value) return;
      navigator.clipboard.writeText(previewCaseContent.value).then(() => {
        showToast({ type: 'success', title: '已复制 YAML', message: '测试用例脚本内容已复制到剪贴板' });
      }).catch(() => {
        showToast({ type: 'warning', title: '复制失败', message: '请手动选中文本框内容复制' });
      });
    }

    async function promoteCase(c) {
      if (!await showConfirm({
        title: '固化为常态回归用例',
        message: `确定将探索生成的用例 [${c.filename}] 固化转存到 test_cases/ 作为常态化回归用例吗？`,
        confirmText: '固化转存',
        icon: '📁'
      })) return;
      try {
        const res = await fetch(`${apiBase}/api/cases/promote`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ path: c.path, target_name: c.filename })
        });
        if (res.ok) {
          const ret = await res.json();
          showToast({ type: 'success', title: '固化成功', message: ret.message });
          await fetchCases();
          await fetchOptions(); // 刷新控制台可选 yaml 列表
        } else {
          showToast({ type: 'warning', title: '固化失败', message: '无法转存该用例' });
        }
      } catch (e) {
        showToast({ type: 'danger', title: '请求失败', message: e.message });
      }
    }

    function runCaseInDashboard(c) {
      taskForm.preset_id = null;
      taskForm.preset_title = '';
      taskForm.mode = 'case';
      taskForm.case_path = c.path || '';
      taskForm.name = `【确定性回归】${c.name || c.filename}`;
      if (c.app_name) {
        changeLiveApp(c.app_name);
      }
      currentTab.value = 'dashboard';
      previewingCase.value = null;
      taskModalVisible.value = true;
      showToast({
        type: 'info',
        title: '用例已载入配置窗口',
        message: `已将 [${c.name || c.filename}] 载入，核验参数后点击“立即创建并启动巡检”或“存为预设”即可！`
      });
    }



    const deletingBugId = ref(null);

    async function deleteBug(bug) {
      if (!bug || !bug.id) return;
      if (bug.zentao_id) {
        showToast('⚠️ 安全拦截', `缺陷 [${bug.id}] 已提交至禅道 (#${bug.zentao_id})，受控单据禁止删除！`, 'warning', 5000);
        return;
      }

      const bugLabel = `[${bug.id}] ${bug.title || ''}`;
      if (!await showConfirm({
        title: '彻底删除缺陷确认',
        message: `确定要彻底删除未提单缺陷 ${bugLabel} 吗？\n\n⚠️ 此操作将永久抹除该缺陷记录，不可恢复！`,
        danger: true,
        confirmText: '彻底删除',
        icon: '🗑️'
      })) {
        return;
      }

      deletingBugId.value = bug.id;
      try {
        const res = await fetch(`${apiBase}/api/bugs/${encodeURIComponent(bug.id)}`, {
          method: 'DELETE'
        });
        const data = await res.json();
        if (res.ok) {
          // 乐观更新：立即在前端列表中过滤剔除
          if (bugs.value) {
            bugs.value = bugs.value.filter(b => b.id !== bug.id);
          }
          totalBugs.value = Math.max(0, totalBugs.value - 1);
          if (selectedBug.value && selectedBug.value.id === bug.id) {
            selectedBug.value = null;
          }
          showToast('🗑️ 删除成功', `未提单缺陷 [${bug.id}] 已彻底物理清理。`, 'success', 3500);
          if (bugs.value.length === 0 && bugPage.value > 1) {
            setBugPage(bugPage.value - 1);
          } else {
            fetchBugs();
          }
        } else {
          showToast('⚠️ 删除失败', data.detail || '接口响应异常', 'error', 5000);
        }
      } catch (err) {
        showToast('⚠️ 网络异常', `请求删除缺陷失败: ${err.message}`, 'error', 5000);
      } finally {
        deletingBugId.value = null;
      }
    }

    const zentaoPreviewVisible = ref(false);
    const zentaoPreviewLoading = ref(false);
    const zentaoPreviewSubmitting = ref(false);
    const zentaoPreviewMetadataLoading = ref(false);
    const zentaoPreviewError = ref('');
    const zentaoPreviewTab = ref('preview'); // 'preview' | 'html'
    const zentaoPreviewTargetBug = ref(null);
    const zentaoPreviewMeta = ref({
      zentao_configured: true,
      zentao_base_url: '',
      warning: null,
      options: {
        products: [],
        projects: [],
        executions: [],
        modules: [],
        builds: [],
        users: [],
        bug_types: [],
      },
    });
    const zentaoPreviewForm = reactive({
      bug_id: '',
      app_key: '',
      app_name: '',
      title: '',
      product_id: 11,
      project_id: 26,
      execution_id: 30,
      module_id: 0,
      type: 'codeerror',
      severity: 3,
      pri: 3,
      status_label: '激活',
      assigned_to: '',
      assigned_to_name: '',
      assignee_reason: '',
      deadline: '',
      opened_build: [],
      os: 'windows',
      browser: 'electron',
      steps_html: '',
      screenshot_url: '',
    });

    function closeZentaoPreview() {
      if (zentaoPreviewSubmitting.value) return;
      zentaoPreviewVisible.value = false;
      zentaoPreviewError.value = '';
    }

    function toggleZentaoBuild(buildId) {
      const idStr = String(buildId);
      const idx = zentaoPreviewForm.opened_build.indexOf(idStr);
      if (idx === -1) {
        zentaoPreviewForm.opened_build.push(idStr);
      } else {
        zentaoPreviewForm.opened_build.splice(idx, 1);
      }
    }

    async function onZentaoCascadedChange(source = 'project') {
      zentaoPreviewMetadataLoading.value = true;
      try {
        const params = new URLSearchParams();
        if (zentaoPreviewForm.project_id) params.set('project_id', String(zentaoPreviewForm.project_id));
        if (zentaoPreviewForm.product_id) params.set('product_id', String(zentaoPreviewForm.product_id));
        const res = await fetch(`${apiBase}/api/zentao/metadata?${params.toString()}`);
        const data = await res.json();
        if (!res.ok) {
          showToast('⚠️ 刷新禅道字典失败', data.detail || '无法获取级联数据', 'warning', 4500);
          return;
        }
        zentaoPreviewMeta.value.options.executions = data.executions || [];
        zentaoPreviewMeta.value.options.modules = data.modules || [];
        zentaoPreviewMeta.value.options.builds = data.builds || [];

        if (source === 'project') {
          const execList = data.executions || [];
          const hasCurrentExec = execList.some(e => Number(e.id) === Number(zentaoPreviewForm.execution_id));
          if (!hasCurrentExec) {
            const testExec = execList.find(e => String(e.name || '').includes('测试'));
            zentaoPreviewForm.execution_id = testExec ? Number(testExec.id) : (execList[0] ? Number(execList[0].id) : 0);
          }
          zentaoPreviewForm.opened_build = [...(data.recommended_builds || [])];
        } else if (source === 'product') {
          const modList = data.modules || [];
          const hasCurrentMod = modList.some(m => Number(m.id) === Number(zentaoPreviewForm.module_id));
          if (!hasCurrentMod) {
            zentaoPreviewForm.module_id = 0;
          }
          zentaoPreviewForm.opened_build = [...(data.recommended_builds || [])];
        }
      } catch (err) {
        showToast('⚠️ 级联拉取异常', err.message, 'warning', 4500);
      } finally {
        zentaoPreviewMetadataLoading.value = false;
      }
    }

    async function syncZenTao(bug) {
      if (!bug || !bug.id) return;
      zentaoPreviewTargetBug.value = bug;
      zentaoPreviewVisible.value = true;
      zentaoPreviewLoading.value = true;
      zentaoPreviewError.value = '';
      zentaoPreviewTab.value = 'preview';
      zentaoPreviewForm.bug_id = bug.id;

      try {
        const res = await fetch(`${apiBase}/api/bugs/${encodeURIComponent(bug.id)}/zentao_preview`);
        const data = await res.json();
        if (!res.ok) {
          zentaoPreviewError.value = data.detail || '获取禅道提单预览数据失败';
          return;
        }
        zentaoPreviewMeta.value = {
          zentao_configured: data.zentao_configured,
          zentao_base_url: data.zentao_base_url || '',
          warning: data.warning || null,
          options: data.options || {
            products: [], projects: [], executions: [], modules: [], builds: [], users: [], bug_types: [],
          },
        };
        const d = data.defaults || {};
        Object.assign(zentaoPreviewForm, {
          bug_id: d.bug_id || bug.id,
          app_key: d.app_key || '',
          app_name: d.app_name || '',
          title: d.title || '',
          product_id: Number(d.product_id || 11),
          project_id: Number(d.project_id || 26),
          execution_id: Number(d.execution_id || 0),
          module_id: Number(d.module_id || 0),
          type: d.type || 'codeerror',
          severity: Number(d.severity || 3),
          pri: Number(d.pri || 3),
          status_label: d.status_label || '激活',
          assigned_to: d.assigned_to || '',
          assigned_to_name: d.assigned_to_name || '',
          assignee_reason: d.assignee_reason || '',
          deadline: d.deadline || '',
          opened_build: Array.isArray(d.opened_build) ? [...d.opened_build] : [],
          os: d.os || 'windows',
          browser: d.browser || 'electron',
          steps_html: d.steps_html || '',
          screenshot_url: d.screenshot_url || '',
        });
      } catch (err) {
        zentaoPreviewError.value = `网络请求异常: ${err.message}`;
      } finally {
        zentaoPreviewLoading.value = false;
      }
    }

    async function confirmSyncZenTao() {
      if (!zentaoPreviewForm.bug_id || zentaoPreviewSubmitting.value) return;
      if (!zentaoPreviewForm.title || !zentaoPreviewForm.title.trim()) {
        showToast('⚠️ 校验提示', '请填写缺陷标题后再提交', 'warning', 4000);
        return;
      }
      zentaoPreviewSubmitting.value = true;
      if (zentaoPreviewTargetBug.value) {
        zentaoPreviewTargetBug.value._syncing = true;
      }
      try {
        const payload = {
          title: zentaoPreviewForm.title.trim(),
          product_id: Number(zentaoPreviewForm.product_id),
          project_id: Number(zentaoPreviewForm.project_id),
          execution_id: Number(zentaoPreviewForm.execution_id || 0),
          module_id: Number(zentaoPreviewForm.module_id || 0),
          type: zentaoPreviewForm.type || 'codeerror',
          severity: Number(zentaoPreviewForm.severity || 3),
          pri: Number(zentaoPreviewForm.pri || 3),
          assigned_to: zentaoPreviewForm.assigned_to || undefined,
          deadline: zentaoPreviewForm.deadline || undefined,
          opened_build: zentaoPreviewForm.opened_build.length > 0 ? [...zentaoPreviewForm.opened_build] : ['trunk'],
          os: zentaoPreviewForm.os || 'windows',
          browser: zentaoPreviewForm.browser || 'electron',
          steps_html: zentaoPreviewForm.steps_html || undefined,
        };
        const res = await fetch(`${apiBase}/api/bugs/${encodeURIComponent(zentaoPreviewForm.bug_id)}/sync_zentao`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        });
        const data = await res.json();
        if (res.ok) {
          const matchedUser = (zentaoPreviewMeta.value.options.users || []).find(
            u => u.account === zentaoPreviewForm.assigned_to
          );
          const assigneeDisplay = matchedUser ? matchedUser.realname : (zentaoPreviewForm.assigned_to || '责任人');
          showToast(
            '🎉 禅道提单成功！',
            `已成功提交至禅道 <a href="${data.zentao_url}" target="_blank">#${data.zentao_id}</a> (指派人: <strong>${assigneeDisplay}</strong>)，单据已自动双向同步！`,
            'success',
            8000
          );
          zentaoPreviewVisible.value = false;
          await fetchBugs();
          if (selectedBug.value && selectedBug.value.id === zentaoPreviewForm.bug_id) {
            selectedBug.value.zentao_id = data.zentao_id;
            selectedBug.value.status = '已提单';
            selectedBug.value.assignee = assigneeDisplay;
          }
        } else {
          showToast('⚠️ 禅道提单失败', data.detail || '接口响应异常', 'error', 6000);
        }
      } catch (err) {
        showToast('⚠️ 提单请求网络异常', err.message, 'error', 6000);
      } finally {
        zentaoPreviewSubmitting.value = false;
        if (zentaoPreviewTargetBug.value) {
          zentaoPreviewTargetBug.value._syncing = false;
        }
      }
    }

    function stopBatchZentaoPoll() {
      if (batchZentaoPollTimer) {
        clearInterval(batchZentaoPollTimer);
        batchZentaoPollTimer = null;
      }
    }

    function startBatchZentaoPoll(jobId) {
      stopBatchZentaoPoll();
      let lastProcessed = -1;
      batchZentaoPollTimer = setInterval(async () => {
        try {
          const res = await fetch(`${apiBase}/api/bugs/batch_sync_zentao/${encodeURIComponent(jobId)}`);
          if (!res.ok) {
            if (res.status === 404) stopBatchZentaoPoll();
            return;
          }
          const data = await res.json();
          batchZentaoJob.value = data;
          if (data.processed !== lastProcessed) {
            lastProcessed = data.processed;
            await fetchBugs();
          }
          if (data.status !== 'running') {
            stopBatchZentaoPoll();
            const doneIds = new Set(
              (data.results || [])
                .filter(r => r.status === 'success' || r.status === 'skipped')
                .map(r => r.bug_id)
            );
            selectedBugIds.value = selectedBugIds.value.filter(id => !doneIds.has(id));
            await fetchBugs();

            if (data.status === 'completed') {
              const failedList = (data.results || []).filter(r => r.status === 'failed');
              const failNote = failedList.length > 0
                ? `；失败 ${failedList.length} 条 (${failedList.slice(0, 3).map(f => f.bug_id).join(', ')})`
                : '';
              showToast(
                failedList.length > 0 ? '⚠️ 批量推禅道完成（含部分失败）' : '🎉 批量推禅道全部完成',
                `共处理 ${data.total} 条：成功 ${data.succeeded} 条，跳过 ${data.skipped} 条${failNote}`,
                failedList.length > 0 ? 'warning' : 'success',
                8000
              );
            } else {
              showToast('❌ 批量推禅道后台异常中断', data.error || '请检查后台日志', 'error', 7000);
            }
          }
        } catch (err) {
          console.warn('轮询批量推禅道状态异常:', err);
        }
      }, 2000);
    }

    async function checkActiveBatchZentaoJob() {
      try {
        const res = await fetch(`${apiBase}/api/bugs/batch_sync_zentao/active`);
        if (!res.ok) return;
        const data = await res.json();
        if (data && data.job_id && data.status === 'running') {
          batchZentaoJob.value = data;
          startBatchZentaoPoll(data.job_id);
        }
      } catch (_) {}
    }

    async function batchSyncZenTao() {
      if (selectedBugIds.value.length === 0) {
        showToast('💡 提示', '请先勾选需要提交禅道的未提单缺陷', 'info', 3000);
        return;
      }
      if (batchZentaoJob.value && batchZentaoJob.value.status === 'running') {
        showToast('⏳ 任务运行中', `当前已有批量推禅道任务在后台执行 (${batchZentaoJob.value.processed}/${batchZentaoJob.value.total})`, 'warning', 4000);
        return;
      }

      const count = selectedBugIds.value.length;
      if (!await showConfirm({
        title: '批量提交禅道确认',
        message: `确定将已勾选的 ${count} 条缺陷提交至禅道吗？\n\n任务将在后台按顺序串行执行（不并发），自动使用各缺陷的默认项目映射、截图证据与 AI 分流责任人，期间您可自由切换页面或继续其他操作。`,
        confirmText: `后台提交 (${count} 条)`,
        icon: '🚀'
      })) {
        return;
      }

      try {
        const res = await fetch(`${apiBase}/api/bugs/batch_sync_zentao`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ bug_ids: [...selectedBugIds.value] }),
        });
        const data = await res.json();
        if (!res.ok) {
          showToast('⚠️ 启动批量提单失败', data.detail || '接口响应异常', 'error', 5000);
          return;
        }
        batchZentaoJob.value = {
          job_id: data.job_id,
          status: 'running',
          total: data.total,
          processed: 0,
          succeeded: 0,
          skipped: 0,
          failed: 0,
          current_bug_id: selectedBugIds.value[0],
          results: [],
        };
        showToast('🚀 已开启后台串行提单', `共 ${data.total} 条缺陷正在后台排队提交禅道，可实时查看进度条。`, 'info', 5000);
        startBatchZentaoPoll(data.job_id);
      } catch (err) {
        showToast('❌ 请求异常', err.message || '网络连接失败', 'error', 5000);
      }
    }

    const reanalyzingBugId = ref(null);

    async function reanalyzeBug(bug) {
      if (!bug || !bug.id || reanalyzingBugId.value) return;
      reanalyzingBugId.value = bug.id;
      showToast('🧠 AI 深度诊断中', `正在对缺陷 [${bug.id}] 基于最新案发现场进行 AI 研判，请稍候...`, 'info', 4000);
      try {
        const resp = await fetch(`${apiBase}/api/bugs/${encodeURIComponent(bug.id)}/reanalyze`, {
          method: 'POST'
        });
        let data = null;
        const text = await resp.text();
        try {
          data = JSON.parse(text);
        } catch (_) {
          data = { detail: text || '服务端未返回有效数据' };
        }
        if (resp.ok && data) {
          if (selectedBug.value && selectedBug.value.id === bug.id) {
            Object.assign(selectedBug.value, data);
          }
          await fetchBugs();
          showToast('✨ 诊断完成', `缺陷 [${bug.id}] 根因分析与修复指引已热刷新！`, 'success', 4000);
        } else {
          showToast('⚠️ 诊断失败', (data && data.detail) || '接口响应异常', 'error', 5000);
        }
      } catch (err) {
        showToast('❌ 请求异常', err.message || '网络连接失败', 'error', 5000);
      } finally {
        reanalyzingBugId.value = null;
      }
    }



    async function triggerHotSync() {

      if (isSyncing.value) return;

      isSyncing.value = true;

      try {

        const res = await fetch(`${apiBase}/api/sync/hot`, { method: 'POST' });

        const data = await res.json();

        await fetchTasks();

        await fetchBugs();

        showToast('热同步成功', `已更新 ${data.new_tasks || 0} 个任务批次，${data.new_bugs || 0} 条缺陷记录！`, 'success', 5000);

      } catch (e) {

        console.error('热同步失败:', e);

        showToast('热同步失败', '请检查服务后台日志。', 'error', 5000);

      } finally {

        isSyncing.value = false;

      }

    }

    const storageSummary = ref({});
    const isCleaningStorage = ref(false);
    const lastCleanupResult = ref(null);
    const systemConfigOverview = ref(null);
    const isLoadingConfigOverview = ref(false);

    async function fetchSystemConfigOverview() {
      isLoadingConfigOverview.value = true;
      try {
        const res = await fetch(`${apiBase}/api/system/config-overview`);
        if (res.ok) {
          systemConfigOverview.value = await res.json();
        }
      } catch (e) {
        console.warn('获取系统配置总览失败:', e);
      } finally {
        isLoadingConfigOverview.value = false;
      }
    }

    async function fetchStorageSummary() {
      try {
        const res = await fetch(`${apiBase}/api/system/storage`);
        if (res.ok) {
          storageSummary.value = await res.json();
        }
      } catch (e) {
        console.warn('获取产物磁盘占用失败:', e);
      }
    }

    async function triggerStorageCleanup(opts = {}) {
      if (isCleaningStorage.value) return;
      const retainDays = opts.retain_days !== undefined ? Number(opts.retain_days) : 7;
      const compressWebp = Boolean(opts.compress_webp);
      const protectActiveBugs = opts.protect_active_bugs !== undefined ? Boolean(opts.protect_active_bugs) : true;
      const cleanResolvedBugShots = Boolean(opts.clean_resolved_bug_shots);
      const dryRun = Boolean(opts.dry_run);

      if (!dryRun) {
        const actionDesc = compressWebp
          ? `将对 ${retainDays} 天前的临时过程截图执行 WebP 高压缩转码`
          : `将安全清理 ${retainDays} 天前的临时过程截图`;
        const bugDesc = cleanResolvedBugShots
          ? '\n同时清理「已关闭 / 误报」缺陷现场截图（永久保护「激活」与「已提单」缺陷截图）。'
          : '';
        const protDesc = protectActiveBugs ? '（自动跳过仍含「激活」Bug 的未处理报告）' : '（注意：已关闭激活 Bug 保护）';
        const ok = await showConfirm({
          title: '执行产物安全瘦身',
          message: `当前 runs 目录总占用：${storageSummary.value.runs_total_human || '未知'}（过程截图占比 ${storageSummary.value.screenshots_ratio || 0}%）。\n\n${actionDesc}${protDesc}${bugDesc}\n\n是否确认执行？`,
          confirmText: '立即执行',
          cancelText: '取消',
          danger: !protectActiveBugs,
        });
        if (!ok) return;
      }

      isCleaningStorage.value = true;
      try {
        const params = new URLSearchParams({
          retain_days: String(retainDays),
          compress_webp: String(compressWebp),
          protect_active_bugs: String(protectActiveBugs),
          clean_resolved_bug_shots: String(cleanResolvedBugShots),
          dry_run: String(dryRun),
        });
        const res = await fetch(`${apiBase}/api/system/cleanup?${params.toString()}`, { method: 'POST' });
        const data = await res.json();
        lastCleanupResult.value = { ...data, dry_run: dryRun, timestamp: new Date().toLocaleTimeString() };
        if (data.storage_after) {
          storageSummary.value = data.storage_after;
        } else {
          await fetchStorageSummary();
        }
        const protMsg = data.protected_count > 0 ? `，跳过 ${data.protected_count} 个含激活 Bug 的报告` : '';
        if (dryRun) {
          showToast('预演估算完成', `预计可释放 ${data.freed_human || '0 B'}（涉及 ${data.cleaned_files || 0} 张过程图${protMsg}）`, 'info', 6000);
        } else {
          showToast('瘦身完成', `已释放 ${data.freed_human || '0 B'}（处理 ${data.cleaned_files || 0} 张过程图${protMsg}），当前占用 ${storageSummary.value.runs_total_human || ''}`, 'success', 6000);
        }
      } catch (e) {
        console.error('磁盘清理失败:', e);
        showToast('瘦身失败', '请检查后台服务日志。', 'error', 5000);
      } finally {
        isCleaningStorage.value = false;
      }
    }







    // =========================================================================

    // 全局平台事件实时热更新总线 (WebSocket Live-Update Bus)

    // =========================================================================

    let platformWs = null;

    let platformReconnectTimer = null;



    function initPlatformWebSocket() {

      const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';

      const wsUrl = `${protocol}//${location.host}/ws/platform`;



      try {

        platformWs = new WebSocket(wsUrl);



        platformWs.onopen = () => {

          console.log('[Live-Update] 🟢 平台数据实时热推总线已就绪');

          if (platformReconnectTimer) {

            clearTimeout(platformReconnectTimer);

            platformReconnectTimer = null;

          }

        };



        platformWs.onmessage = (event) => {

          try {

            const msg = JSON.parse(event.data);

            if (msg.event === 'bug_updated') {

              console.log('[Live-Update] ⚡ 监听到缺陷数据变更，静默热更新...', msg.data);

              if (currentTab.value === 'bugs') {

                fetchBugs();

              }

              if (selectedBug.value && msg.data && selectedBug.value.id === msg.data.bug_id) {

                // 如果当前正在查看该缺陷详情，静默重新拉取

                fetch(`${apiBase}/api/bugs/${encodeURIComponent(selectedBug.value.id)}`).then(r => r.json()).then(detail => {

                  if (detail && detail.id) Object.assign(selectedBug.value, detail);

                }).catch(() => { });

              }

            } else if (msg.event === 'task_updated') {
              console.log('[Live-Update] ⚡ 监听到巡检任务状态变更，静默热更新...', msg.data);
              if (currentTab.value === 'tasks') {
                fetchTasks();
                fetchTaskQueue();
              }
            } else if (msg.event === 'data_refresh') {
              if (currentTab.value === 'bugs') fetchBugs();
              if (currentTab.value === 'tasks') {
                fetchTasks();
                fetchTaskQueue();
              }
            }

          } catch (e) {

            // 忽略非 JSON 心跳

          }

        };



        platformWs.onclose = () => {

          if (!platformReconnectTimer) {

            platformReconnectTimer = setTimeout(initPlatformWebSocket, 4000);

          }

        };



        platformWs.onerror = () => {

          if (platformWs) platformWs.close();

        };

      } catch (err) {

        if (!platformReconnectTimer) {

          platformReconnectTimer = setTimeout(initPlatformWebSocket, 4000);

        }

      }

    }



    const liveAutoRefresh = ref(false); // 币安式静默模式：默认彻底关闭高频 HTTP 轮询，消除控制台跳动刷屏
    let liveTimer = null;

    function startLiveTimer() {
      // 1. 若未开启自动刷新开关，坚决不启动轮询
      if (!liveAutoRefresh.value) {
        stopLiveTimer();
        return;
      }
      // 2. 若当前正在查看具体任务，指标已由 WebSocket (/ws/tasks/{id}/metrics) 纯流式推送，坚决不进行无意义 HTTP 轮询
      if (activeTaskId.value && activeTaskId.value !== '__live__') {
        stopLiveTimer();
        return;
      }
      if (!liveTimer) {
        liveTimer = setInterval(() => {
          if (document.hidden) return; // 页面失焦或最小化时静默休眠
          fetchLiveSnapshot();
        }, 4000);
      }
    }

    function stopLiveTimer() {
      if (liveTimer) {
        clearInterval(liveTimer);
        liveTimer = null;
      }
    }

    function toggleLiveAutoRefresh() {
      liveAutoRefresh.value = !liveAutoRefresh.value;
      if (liveAutoRefresh.value) {
        fetchLiveSnapshot();
        startLiveTimer();
        showToast('⏱️ 自动轮询已开启', '物理环境心跳探针已激活 (4s 间隔)', 'info', 2500);
      } else {
        stopLiveTimer();
        showToast('🤫 静默模式', '已暂停 HTTP 轮询，控制台已清净', 'info', 2500);
      }
    }

    async function manualRefreshLive() {
      await Promise.all([fetchLiveSnapshot(), fetchLiveAppsStatus()]);
      showToast('✨ 刷新成功', '物理环境与应用状态切片已更新', 'success', 2000);
    }

    // 智能 Tab 驱动：仅在用户切换到对应 Tab 时按需发起数据获取，彻底消灭全站高频无意义轮询
    watch(currentTab, (newTab) => {
      localStorage.setItem(TAB_STORAGE_KEY, newTab);
      if (newTab === 'tasks') navExpanded.tasks = true;
      if (newTab === 'settings') navExpanded.settings = true;

      if (newTab === 'bugs') {
        fetchBugs();
      } else if (newTab === 'tasks') {
        if (assetsSubTab.value === 'cases') {
          fetchCases();
        } else {
          fetchTasks();
        }
      } else if (newTab === 'settings') {
        if (settingsSubTab.value === 'cleanup') {
          fetchStorageSummary();
        } else {
          fetchSystemConfigOverview();
        }
      } else if (newTab === 'monitor') {
        fetchTasks(); // 预载最新任务清单，保证“当前查看维度”下拉选项时刻齐全
        fetchLiveAppsStatus();
        fetchLiveSnapshot();
        startLiveTimer();

        nextTick(() => {
          if (domChart) domChart.resize();
          if (ueChart) ueChart.resize();
          scrollTerminalToBottom();
        });

        if (!domChart || !ueChart) {
          initCharts(false);
        }

        if (activeTaskId.value && activeTaskId.value !== '__live__') {
          loadHistoricalMetrics(activeTaskId.value);
        } else {
          loadLiveAmbientHistory(liveSelectedApp.value, getSpanHours(liveTimeSpan.value));
        }
      } else if (newTab === 'dashboard') {
        fetchLiveSnapshot();
        startLiveTimer();
      }

      // 切离实时监控与看板时，暂停 4 秒快照轮询，彻底释放网络与 CPU 资源
      if (newTab !== 'monitor' && newTab !== 'dashboard') {
        stopLiveTimer();
      }
    });

    watch(assetsSubTab, (newSub) => {
      localStorage.setItem(ASSETS_SUBTAB_KEY, newSub);
      if (newSub === 'cases') {
        fetchCases();
      } else if (newSub === 'queue') {
        fetchTaskQueue();
      } else {
        fetchTasks();
      }
    });

    watch(settingsSubTab, (newSub) => {
      localStorage.setItem(SETTINGS_SUBTAB_KEY, newSub);
      if (newSub === 'cleanup') {
        fetchStorageSummary();
      } else {
        fetchSystemConfigOverview();
      }
    });

    function handleGlobalKeydown(e) {
      if ((e.ctrlKey || e.metaKey) && (e.key === 'r' || e.key === 'R')) {
        localStorage.removeItem(TAB_STORAGE_KEY);
        localStorage.removeItem(ASSETS_SUBTAB_KEY);
        localStorage.removeItem(SETTINGS_SUBTAB_KEY);
        localStorage.removeItem('vision_platform_app_name');
      }
    }

    onMounted(() => {
      window.addEventListener('keydown', handleGlobalKeydown);
      fetchOptions();
      fetchPresetTasks();
      fetchLiveAppsStatus();
      fetchTasks(); // 启动时预载任务库，保证任何页面（含监控大屏维度）均可即刻使用任务数据
      fetchCases(); // 预载用例资产清单
      fetchTaskQueue(); // 预载调度执行队列状态
      checkActiveBatchZentaoJob(); // 恢复后台运行中的批量推禅道进度

      // 根据当前恢复的 Tab 按需加载首屏数据与启动必要监控
      if (currentTab.value === 'dashboard') {
        fetchLiveSnapshot();
        startLiveTimer();
      } else if (currentTab.value === 'monitor') {
        fetchLiveSnapshot();
        loadLiveAmbientHistory(liveSelectedApp.value, getSpanHours(liveTimeSpan.value));
        startLiveTimer();
      } else if (currentTab.value === 'bugs') {
        fetchBugs();
      } else if (currentTab.value === 'cases') {
        fetchCases();
      } else if (currentTab.value === 'settings') {
        if (settingsSubTab.value === 'cleanup') {
          fetchStorageSummary();
        } else {
          fetchSystemConfigOverview();
        }
      }

      initPlatformWebSocket();

      document.addEventListener('visibilitychange', () => {
        if (document.hidden) {
          stopLiveTimer();
        } else if (liveAutoRefresh.value && (currentTab.value === 'monitor' || currentTab.value === 'dashboard')) {
          startLiveTimer();
        }
      });

      window.addEventListener('resize', () => {
        if (domChart) domChart.resize();
        if (ueChart) ueChart.resize();
      });

      // 全局弹窗键盘事件响应 (Esc 取消 / Enter 确认)
      window.addEventListener('keydown', (e) => {
        if (dialogState.visible) {
          if (e.key === 'Escape') {
            e.preventDefault();
            handleDialogCancel();
          } else if (e.key === 'Enter' && dialogState.type !== 'prompt') {
            e.preventDefault();
            handleDialogConfirm();
          }
        }
      });
    });

    onUnmounted(() => {
      stopLiveTimer();
      stopBatchZentaoPoll();
      if (platformReconnectTimer) clearTimeout(platformReconnectTimer);
      if (platformWs) platformWs.close();
      if (logWs) logWs.close();
      if (metricWs) metricWs.close();
    });



    return {

      // 任务列表分页
      taskPage,
      taskPageSize,
      taskPageSizes,
      taskPageJump,
      totalTaskPages,
      paginatedTasks,

      taskDateRange,

      dateShortcuts,

      taskAppFilter,

      taskQuickDateRange,

      applyQuickTaskDateRange,

      onTaskDateInputChange,

      resetTaskFilters,

      filteredTasks,
      setTaskPage,
      onTaskPageSizeChange,
      jumpToTaskPage,

      // 缺陷列表分页
      bugPage,
      bugPageSize,
      bugPageSizes,
      bugPageJump,
      totalBugs,
      totalBugPages,
      paginatedBugs,
      setBugPage,
      onBugPageSizeChange,
      jumpToBugPage,

      // 页码生成器
      getPageNumbers,
      toasts,
      showToast,
      removeToast,

      // 全局自研交互弹窗系统
      dialogState,
      dialogInputRef,
      handleDialogConfirm,
      handleDialogCancel,
      showConfirm,
      showPrompt,

      currentTab,

      currentAppName,

      options,

      presetTasks,

      liveSnapshot,

      liveAutoRefresh,
      toggleLiveAutoRefresh,
      manualRefreshLive,

      fetchLiveSnapshot,

      tasks,

      fetchTasks,

      activeTaskId,

      activeTask,

      taskForm,

      terminalLogs,

      bugs,

      isBugsLoading,

      fetchBugs,

      onBugSearchInput,

      bugSearch,
      bugAppFilter,
      bugSeverityFilter,

      bugAssigneeFilter,

      bugStatusFilter,

      bugOccurrencesFilter,

      resetBugFilters,

      selectedBug,

      editingBug,

      editForm,

      openEditBugModal,
      zentaoUsers,

      submitBugEdit,

      formatZenTaoUrl,

      formatScreenshotUrl,

      launchPreset,
      enqueuePreset,
      loadPresetToForm,
      saveCurrentFormAsPreset,
      deletePreset,
      getPresetModeLabel,
      getAppName,
      clearLoadedPreset,
      applyTemplate,

      presetViewMode,
      setPresetViewMode,
      presetSortField,
      presetSortOrder,
      togglePresetSort,
      sortedPresetTasks,
      taskModalVisible,
      openNewTaskModal,
      taskDetailModalVisible,
      activeDetailPreset,
      openPresetDetail,
      editFromDetail,
      launchFromDetail,
      copyPresetPrompt,

      submitCreateTask,

      startTask,

      stopTask,

      deleteTaskRun,
      deletingTaskId,

      switchActiveTask,
      jumpToBugMonitor,

      onMonitorTargetChange,

      switchToLiveMonitor,

      viewBugDetail,

      formatDateTime,

      formatDuration,

      formatReportUrl,

      deleteBug,
      deletingBugId,

      syncZenTao,
      selectedBugIds,
      selectableBugsOnPage,
      isAllPageBugsSelected,
      isSomePageBugsSelected,
      toggleBugSelection,
      toggleSelectAllPageBugs,
      clearBugSelection,
      batchZentaoJob,
      batchSyncZenTao,
      zentaoPreviewVisible,
      zentaoPreviewLoading,
      zentaoPreviewSubmitting,
      zentaoPreviewMetadataLoading,
      zentaoPreviewError,
      zentaoPreviewTab,
      zentaoPreviewMeta,
      zentaoPreviewForm,
      closeZentaoPreview,
      toggleZentaoBuild,
      onZentaoCascadedChange,
      confirmSyncZenTao,
      reanalyzeBug,
      reanalyzingBugId,

      isSyncing,

      triggerHotSync,

      storageSummary,

      isCleaningStorage,

      lastCleanupResult,

      fetchStorageSummary,

      triggerStorageCleanup,

      systemConfigOverview,

      isLoadingConfigOverview,

      fetchSystemConfigOverview,

      liveSelectedApp,

      liveTimeSpan,

      liveAppsStatus,

      changeLiveApp,

      changeLiveTimeSpan,

      assetsSubTab,

      settingsSubTab,

      navExpanded,

      selectPrimaryMenu,

      selectedEnvInfo,

      envInfoLoading,

      envInfoViewMode,

      openEnvInfoModal,

      copyEnvInfoJson,

      manualCases,

      autoCases,

      casesSubTab,

      isCasesLoading,

      previewingCase,

      previewCaseLoading,

      previewCaseContent,

      fetchCases,

      openCasePreview,

      copyCaseYaml,

      promoteCase,

      runCaseInDashboard,

      taskQueue,
      pendingQueueCount,
      showEnqueueModal,
      isSubmittingEnqueue,
      scheduleModalTab,
      enqueueForm: scheduleForm,
      scheduleForm,
      filteredSchedulePresets,
      fetchTaskQueue,
      openEnqueueModal: openCreateScheduleModal,
      openCreateScheduleModal,
      openEditScheduleModal,
      onScheduleAppChange,
      onSchedulePresetChange,
      confirmEnqueueTask: confirmCreateSchedulePlan,
      confirmCreateSchedulePlan,
      toggleScheduleActive,
      runScheduleNow,
      deleteSchedule,
      removeFromQueue,
      formatPriorityLabel,
      formatTaskStatus,
      formatTaskMode,
      formatWeekdays,
      setCurrentExecutionTime

    };

}
