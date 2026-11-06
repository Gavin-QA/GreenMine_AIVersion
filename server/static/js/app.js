const { createApp, ref, reactive, computed, onMounted, onUnmounted, nextTick, watch } = Vue;



const app = createApp({

  setup() {

    const currentTab = ref('dashboard'); // dashboard, tasks, monitor, bugs

    const apiBase = window.location.origin;

    // 全局 Toast 通知状态与操作方法
    const toasts = ref([]);
    function showToast(title, message, type = 'success', duration = 6000) {
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




    // 全局选项配置 (应用、模式、提示词模板)

    const options = reactive({

      apps: [],

      modes: [],

      prompt_templates: [],

      zentao_configured: false,

      report_hub_url: '/report-hub'

    });



    // 预设任务库

    const presetTasks = ref([]);



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

    const activeTaskId = ref(null);

    const activeTask = ref(null);

    // 任务列表分页
    const taskPage = ref(1);
    const taskPageSize = ref(10);
    const taskPageSizes = [10, 20, 50];
    const taskPageJump = ref(1);

    const totalTaskPages = computed(() => {
      const total = Math.ceil(tasks.value.length / taskPageSize.value);
      return total > 0 ? total : 1;
    });

    const paginatedTasks = computed(() => {
      const start = (taskPage.value - 1) * taskPageSize.value;
      return tasks.value.slice(start, start + taskPageSize.value);
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


    const liveSelectedApp = ref('tianrui');

    const liveTimeSpan = ref('24h');

    const liveAppsStatus = ref([
      { app_name: 'tianrui', title: '四川天瑞', online: false, ue_pid: null, ue_commit_mb: 0, ue_memory_mb: 0 },
      { app_name: 'zhaiwan', title: '寨湾矿山', online: false, ue_pid: null, ue_commit_mb: 0, ue_memory_mb: 0 },
      { app_name: 'liwutong', title: '里伍铜矿山', online: false, ue_pid: null, ue_commit_mb: 0, ue_memory_mb: 0 }
    ]);



    const taskForm = reactive({

      preset_id: null, // 记录当前是否绑定某个预设 (用于回写保存)

      name: '',

      app_name: 'tianrui',

      mode: 'explore',

      macro_objective: '',

      max_steps: 200,

      max_times: 60,

      reset_memory: false,

      ignore_errors: true,

      explore_context: 'docs/explore_rules_tianrui.md',

      case_path: ''

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

    // 缺陷列表分页
    const bugPage = ref(1);
    const bugPageSize = ref(15);
    const bugPageSizes = [10, 15, 30, 50];
    const bugPageJump = ref(1);

    const totalBugPages = computed(() => {
      const total = Math.ceil(bugs.value.length / bugPageSize.value);
      return total > 0 ? total : 1;
    });

    const paginatedBugs = computed(() => {
      const start = (bugPage.value - 1) * bugPageSize.value;
      return bugs.value.slice(start, start + bugPageSize.value);
    });

    function setBugPage(p) {
      if (typeof p !== 'number') return;
      if (p < 1) p = 1;
      if (p > totalBugPages.value) p = totalBugPages.value;
      bugPage.value = p;
      bugPageJump.value = p;
    }

    function onBugPageSizeChange() {
      bugPage.value = 1;
      bugPageJump.value = 1;
    }

    function jumpToBugPage() {
      let p = parseInt(bugPageJump.value, 10);
      if (isNaN(p)) p = 1;
      setBugPage(p);
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

        presetTasks.value = await res.json();

      } catch (e) {

        console.error('获取预设任务列表失败:', e);

      }

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

    async function changeLiveApp(appName) {
      liveSelectedApp.value = appName;
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

        fetchLiveAppsStatus();

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

        let url = `${apiBase}/api/bugs?limit=300`;

        if (options && options.sync) url += `&sync=true`;

        if (bugSeverityFilter.value) url += `&severity=${encodeURIComponent(bugSeverityFilter.value)}`;

        if (bugAssigneeFilter.value) url += `&assignee=${encodeURIComponent(bugAssigneeFilter.value)}`;

        if (bugStatusFilter.value) url += `&status=${encodeURIComponent(bugStatusFilter.value)}`;

        if (bugOccurrencesFilter.value) url += `&occurrences_range=${encodeURIComponent(bugOccurrencesFilter.value)}`;

        if (bugSearch.value && bugSearch.value.trim()) url += `&search=${encodeURIComponent(bugSearch.value.trim())}`;



        const res = await fetch(url, { signal: bugAbortController.signal });

        if (!res.ok) throw new Error(`HTTP ${res.status}`);

        bugs.value = await res.json();
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

      if (!confirm(`确定要立即拉起预设巡检任务【${preset.title}】吗？`)) return;

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

          alert('拉起预设任务失败: ' + (await res.text()));

        }

      } catch (e) {

        alert('启动异常: ' + e);

      }

    }



    function loadPresetToForm(preset) {

      taskForm.preset_id = preset.is_system ? null : preset.id; // 系统预设载入默认另存，自定义预设保留id可直接回写

      taskForm.name = preset.title;

      taskForm.app_name = preset.app_name;

      taskForm.mode = preset.mode;

      taskForm.macro_objective = preset.macro_objective;

      taskForm.max_steps = preset.max_steps;

      taskForm.max_times = preset.max_times;

      taskForm.reset_memory = preset.reset_memory;

      taskForm.ignore_errors = preset.ignore_errors;

      taskForm.case_path = preset.case_path || '';

      // 平滑滚动到底部表单

      const formCard = document.getElementById('taskFormCard');

      if (formCard) {

        formCard.scrollIntoView({ behavior: 'smooth' });

      }

    }



    async function saveCurrentFormAsPreset(overwriteExisting = false) {

      const title = prompt('请输入要保存的预设任务名称:', taskForm.name || '我的定制巡检预设');

      if (!title) return;



      const payload = {

        id: (overwriteExisting && taskForm.preset_id) ? taskForm.preset_id : null,

        title: title,

        app_name: taskForm.app_name,

        mode: taskForm.mode,

        badge: '自定义',

        macro_objective: taskForm.macro_objective,

        max_steps: taskForm.max_steps,

        max_times: taskForm.max_times,

        reset_memory: taskForm.reset_memory,

        ignore_errors: taskForm.ignore_errors,

        case_path: taskForm.case_path || null,

        description: `用户自定义预设: ${taskForm.app_name} / ${taskForm.mode} / ${taskForm.max_steps}步`

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

          alert(`✅ 预设【${saved.title}】保存成功！已加入常用预设任务库！`);

          await fetchPresetTasks();

        } else {

          alert('保存预设失败: ' + (await res.text()));

        }

      } catch (e) {

        alert('保存预设异常: ' + e);

      }

    }



    async function deletePreset(preset) {

      if (preset.is_system) {

        alert('系统内置预设不可删除！');

        return;

      }

      if (!confirm(`确定要删除自定义预设【${preset.title}】吗？`)) return;

      try {

        const res = await fetch(`${apiBase}/api/tasks/presets/${preset.id}`, { method: 'DELETE' });

        if (res.ok) {

          alert('预设删除成功！');

          if (taskForm.preset_id === preset.id) {

            taskForm.preset_id = null;

          }

          await fetchPresetTasks();

        } else {

          alert('删除失败: ' + (await res.text()));

        }

      } catch (e) {

        alert('删除异常: ' + e);

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

        const res = await fetch(`${apiBase}/api/tasks`, {

          method: 'POST',

          headers: { 'Content-Type': 'application/json' },

          body: JSON.stringify(taskForm)

        });

        if (res.ok) {

          const newTask = await res.json();

          await fetchTasks();

          activeTaskId.value = newTask.id;

          activeTask.value = newTask;

          currentTab.value = 'monitor';

          startTask(newTask.id);

        } else {

          alert('创建任务失败: ' + (await res.text()));

        }

      } catch (e) {

        alert('创建任务异常: ' + e);

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

          alert(data.detail || '启动失败');

        }

      } catch (e) {

        alert('启动任务异常: ' + e);

      }

    }



    async function stopTask(taskId) {

      if (!confirm('确定要终止当前任务吗？底座将优雅退出进程树。')) return;

      try {

        await fetch(`${apiBase}/api/tasks/${taskId}/stop`, { method: 'POST' });

        await fetchTasks();

      } catch (e) {

        alert('终止任务异常: ' + e);

      }

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

        if (!domEl || !ueEl || !window.echarts) return;



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

          alert(`✅ 缺陷 [${updated.id}] 修改成功！已实时多端同步入库！`);

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

          alert('保存失败: ' + (await res.text()));

        }

      } catch (e) {

        alert('修改缺陷异常: ' + e);

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



    async function syncZenTao(bug) {
      if (!confirm(`确定要将缺陷 [${bug.id}] 提交到禅道吗？`)) return;
      bug._syncing = true;
      try {
        const res = await fetch(`${apiBase}/api/bugs/${bug.id}/sync_zentao`, { method: 'POST' });
        const data = await res.json();
        if (res.ok) {
          showToast(
            '🎉 禅道提单成功！',
            `已成功提交至禅道 <a href="${data.zentao_url}" target="_blank">#${data.zentao_id}</a> (指派人: <strong>${bug.assignee || '责任人'}</strong>)，单据已自动双向同步！`,
            'success',
            8000
          );
          await fetchBugs();
          if (selectedBug.value && selectedBug.value.id === bug.id) {
            selectedBug.value.zentao_id = data.zentao_id;
            selectedBug.value.status = '已提单';
          }
        } else {
          showToast('⚠️ 禅道提单失败', data.detail || '接口响应异常', 'error', 6000);
        }
      } catch (err) {
        showToast('⚠️ 提单请求网络异常', err.message, 'error', 6000);
      } finally {
        bug._syncing = false;
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

        alert(`✅ 磁盘数据热同步成功！已更新 ${data.new_tasks || 0} 个任务批次，${data.new_bugs || 0} 条缺陷记录！`);

      } catch (e) {

        console.error('热同步失败:', e);

        alert('❌ 热同步失败，请检查服务后台日志。');

      } finally {

        isSyncing.value = false;

      }

    }



    // 监听标签页切换

    watch(currentTab, (val) => {

      if (val === 'monitor') {

        // 切回大屏标签页时：图表 DOM 重新恢复显示，只调用 resize 自适应容器，不销毁历史数据！

        nextTick(() => {

          if (domChart) domChart.resize();

          if (ueChart) ueChart.resize();

          scrollTerminalToBottom();

        });

        if (!domChart || !ueChart) {

          initCharts(false);

          if (activeTaskId.value && activeTaskId.value !== '__live__') {

            loadHistoricalMetrics(activeTaskId.value);

          } else if (activeTaskId.value === '__live__') {

            loadLiveAmbientHistory(liveSelectedApp.value, getSpanHours(liveTimeSpan.value));

          }

        }

      } else if (val === 'bugs') {

        fetchBugs();

      }

    });



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

              fetchBugs();

              if (selectedBug.value && msg.data && selectedBug.value.id === msg.data.bug_id) {

                // 如果当前正在查看该缺陷详情，静默重新拉取

                fetch(`${apiBase}/api/bugs`).then(r => r.json()).then(list => {

                  const found = list.find(x => x.id === selectedBug.value.id);

                  if (found) Object.assign(selectedBug.value, found);

                }).catch(() => { });

              }

            } else if (msg.event === 'task_updated') {

              console.log('[Live-Update] ⚡ 监听到巡检任务状态变更，静默热更新...', msg.data);

              fetchTasks();

            } else if (msg.event === 'data_refresh') {

              fetchBugs();

              fetchTasks();

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



    let liveTimer = null;

    let taskTimer = null;



    onMounted(() => {

      fetchOptions();

      fetchPresetTasks();

      fetchTasks();

      fetchLiveAppsStatus();

      loadLiveAmbientHistory(liveSelectedApp.value, getSpanHours(liveTimeSpan.value));

      fetchLiveSnapshot();

      fetchBugs();

      initPlatformWebSocket();



      // 当用户从其他应用/窗口切回本控制台标签页时，自动静默触发最新数据同步

      document.addEventListener('visibilitychange', () => {

        if (!document.hidden) {

          fetchBugs();

          fetchTasks();

        }

      });



      // 定时轮询环境快照与任务状态

      liveTimer = setInterval(fetchLiveSnapshot, 4000);

      taskTimer = setInterval(fetchTasks, 5000);



      window.addEventListener('resize', () => {

        if (domChart) domChart.resize();

        if (ueChart) ueChart.resize();

      });

    });



    onUnmounted(() => {

      if (liveTimer) clearInterval(liveTimer);

      if (taskTimer) clearInterval(taskTimer);

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
      setTaskPage,
      onTaskPageSizeChange,
      jumpToTaskPage,

      // 缺陷列表分页
      bugPage,
      bugPageSize,
      bugPageSizes,
      bugPageJump,
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

      currentTab,

      options,

      presetTasks,

      liveSnapshot,

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

      bugSeverityFilter,

      bugAssigneeFilter,

      bugStatusFilter,

      bugOccurrencesFilter,

      resetBugFilters,

      selectedBug,

      editingBug,

      editForm,

      openEditBugModal,

      submitBugEdit,

      formatZenTaoUrl,

      formatScreenshotUrl,

      launchPreset,

      loadPresetToForm,

      saveCurrentFormAsPreset,

      deletePreset,

      applyTemplate,

      submitCreateTask,

      startTask,

      stopTask,

      switchActiveTask,

      onMonitorTargetChange,

      switchToLiveMonitor,

      viewBugDetail,

      formatReportUrl,

      syncZenTao,

      isSyncing,

      triggerHotSync,

      liveSelectedApp,

      liveTimeSpan,

      liveAppsStatus,

      changeLiveApp,

      changeLiveTimeSpan

    };

  }

});



app.mount('#app');

