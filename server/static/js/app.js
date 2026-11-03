const { createApp, ref, reactive, onMounted, onUnmounted, nextTick, watch } = Vue;

const app = createApp({
  setup() {
    const currentTab = ref('dashboard'); // dashboard, tasks, monitor, bugs
    const apiBase = window.location.origin;

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

    const taskForm = reactive({
      preset_id: null, // 记录当前是否绑定某个预设 (用于回写保存)
      name: '',
      app_name: 'zhaiwan',
      mode: 'explore',
      macro_objective: '',
      max_steps: 200,
      max_times: 60,
      reset_memory: false,
      ignore_errors: true,
      explore_context: 'docs/explore_rules_zhaiwan.md',
      case_path: ''
    });

    // 监控页面与 ECharts
    const terminalLogs = ref([]);
    let logWs = null;
    let metricWs = null;
    let domChart = null;
    let ueChart = null;

    // 缺陷列表
    const bugs = ref([]);
    const bugSearch = ref('');
    const bugSeverityFilter = ref('');
    const selectedBug = ref(null);

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

    async function fetchLiveSnapshot() {
      try {
        const res = await fetch(`${apiBase}/api/metrics/live/snapshot?app_name=${taskForm.app_name}`);
        const data = await res.json();
        Object.assign(liveSnapshot, data);

        // 如果当前处于【本机物理环境实时心电图模式】，向折线图推入动态打点
        if (activeTaskId.value === '__live__') {
          appendMetricToCharts({
            timestamp: data.timestamp || new Date().toISOString(),
            dom_count: data.dom_count || 0,
            listeners_count: data.listeners_count || 0,
            js_heap_mb: data.js_heap_mb || 0,
            ue_cpu_percent: data.ue_cpu_percent || 0,
            ue_memory_mb: data.ue_memory_mb || 0,
            webrtc_fps: (data.webrtc_fps !== null && data.webrtc_fps !== undefined) ? data.webrtc_fps : (data.gpu_usage_percent || 0)
          });
        }
      } catch (e) {
        console.error('获取实时快照失败:', e);
      }
    }

    async function fetchTasks() {
      try {
        const res = await fetch(`${apiBase}/api/tasks?limit=50`);
        tasks.value = await res.json();
        if (!activeTaskId.value) {
          activeTaskId.value = '__live__';
        } else if (activeTaskId.value !== '__live__') {
          activeTask.value = tasks.value.find(t => t.id === activeTaskId.value) || activeTask.value;
        }
      } catch (e) {
        console.error('获取任务列表失败:', e);
      }
    }

    async function fetchBugs() {
      try {
        let url = `${apiBase}/api/bugs?limit=100`;
        if (bugSeverityFilter.value) url += `&severity=${bugSeverityFilter.value}`;
        if (bugSearch.value) url += `&search=${encodeURIComponent(bugSearch.value)}`;
        const res = await fetch(url);
        bugs.value = await res.json();
      } catch (e) {
        console.error('获取缺陷列表失败:', e);
      }
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
      if (activeTaskId.value === '__live__') {
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

      initCharts();
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
      initCharts();

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

    let chartTimes = [];
    let domData = [];
    let listenersData = [];
    let jsHeapData = [];
    let ueCpuData = [];
    let ueMemData = [];
    let webrtcFpsData = [];

    function initCharts() {
      nextTick(() => {
        const domEl = document.getElementById('domChart');
        const ueEl = document.getElementById('ueChart');
        if (!domEl || !ueEl || !window.echarts) return;

        if (domChart) domChart.dispose();
        if (ueChart) ueChart.dispose();

        chartTimes = [];
        domData = [];
        listenersData = [];
        jsHeapData = [];
        ueCpuData = [];
        ueMemData = [];
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
            { name: 'UE5 内存 (MB)', type: 'line', smooth: true, data: [], itemStyle: { color: '#00e676' } },
            { name: 'WebRTC FPS / GPU (%)', type: 'line', yAxisIndex: 1, smooth: true, data: [], itemStyle: { color: '#3a7bd5' } }
          ]
        });
      });
    }

    function resetChartsData(list) {
      if (!domChart || !ueChart) return;
      chartTimes = list.map(m => new Date(m.timestamp).toLocaleTimeString());
      domData = list.map(m => m.dom_count);
      listenersData = list.map(m => m.listeners_count);
      jsHeapData = list.map(m => m.js_heap_mb);
      ueCpuData = list.map(m => m.ue_cpu_percent || 0);
      ueMemData = list.map(m => m.ue_memory_mb || 0);
      webrtcFpsData = list.map(m => m.webrtc_fps || 0);

      domChart.setOption({
        xAxis: { data: chartTimes },
        series: [{ data: domData }, { data: listenersData }, { data: jsHeapData }]
      });

      ueChart.setOption({
        xAxis: { data: chartTimes },
        series: [{ data: ueCpuData }, { data: ueMemData }, { data: webrtcFpsData }]
      });
    }

    function appendMetricToCharts(m) {
      if (!domChart || !ueChart) return;
      const t = new Date(m.timestamp).toLocaleTimeString();
      chartTimes.push(t);
      domData.push(m.dom_count);
      listenersData.push(m.listeners_count);
      jsHeapData.push(m.js_heap_mb);
      ueCpuData.push(m.ue_cpu_percent || 0);
      ueMemData.push(m.ue_memory_mb || 0);
      webrtcFpsData.push(m.webrtc_fps || 0);

      if (chartTimes.length > 60) {
        chartTimes.shift();
        domData.shift();
        listenersData.shift();
        jsHeapData.shift();
        ueCpuData.shift();
        ueMemData.shift();
        webrtcFpsData.shift();
      }

      domChart.setOption({
        xAxis: { data: chartTimes },
        series: [{ data: domData }, { data: listenersData }, { data: jsHeapData }]
      });

      ueChart.setOption({
        xAxis: { data: chartTimes },
        series: [{ data: ueCpuData }, { data: ueMemData }, { data: webrtcFpsData }]
      });
    }

    // =========================================================================
    // 缺陷管理与禅道同步
    // =========================================================================

    function viewBugDetail(b) {
      selectedBug.value = b;
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
      try {
        const res = await fetch(`${apiBase}/api/bugs/${bug.id}/sync_zentao`, { method: 'POST' });
        const data = await res.json();
        if (res.ok) {
          alert(`✅ 禅道提单成功！禅道 Bug ID: #${data.zentao_id}`);
          await fetchBugs();
          if (selectedBug.value && selectedBug.value.id === bug.id) {
            selectedBug.value.zentao_id = data.zentao_id;
            selectedBug.value.status = '已提单';
          }
        } else {
          alert('提单失败: ' + (data.detail || '未知异常'));
        }
      } catch (e) {
        alert('同步禅道网络异常: ' + e);
      }
    }

    // 监听标签页切换
    watch(currentTab, (val) => {
      if (val === 'monitor') {
        if (activeTaskId.value === '__live__') {
          switchToLiveMonitor();
        } else if (activeTaskId.value) {
          initCharts();
          loadHistoricalMetrics(activeTaskId.value);
        }
      } else if (val === 'bugs') {
        fetchBugs();
      }
    });

    let liveTimer = null;
    let taskTimer = null;

    onMounted(() => {
      fetchOptions();
      fetchPresetTasks();
      fetchTasks();
      fetchLiveSnapshot();
      fetchBugs();

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
      if (logWs) logWs.close();
      if (metricWs) metricWs.close();
    });

    return {
      currentTab,
      options,
      presetTasks,
      liveSnapshot,
      tasks,
      activeTaskId,
      activeTask,
      taskForm,
      terminalLogs,
      bugs,
      bugSearch,
      bugSeverityFilter,
      selectedBug,
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
      syncZenTao
    };
  }
});

app.mount('#app');
