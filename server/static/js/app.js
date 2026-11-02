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
      zentao_configured: false
    });

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
      gpu_usage_percent: 0,
      gpu_memory_mb: 0
    });

    // 任务列表与创建表单
    const tasks = ref([]);
    const activeTaskId = ref(null);
    const activeTask = ref(null);

    const taskForm = reactive({
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

        if (options.prompt_templates.length > 0 && !taskForm.macro_objective) {
          taskForm.macro_objective = options.prompt_templates[0].prompt;
        }
      } catch (e) {
        console.error('获取配置选项失败:', e);
      }
    }

    async function fetchLiveSnapshot() {
      try {
        const res = await fetch(`${apiBase}/api/metrics/live/snapshot?app_name=${taskForm.app_name}`);
        const data = await res.json();
        Object.assign(liveSnapshot, data);
      } catch (e) {
        console.error('获取实时快照失败:', e);
      }
    }

    async function fetchTasks() {
      try {
        const res = await fetch(`${apiBase}/api/tasks?limit=50`);
        tasks.value = await res.json();
        if (!activeTaskId.value && tasks.value.length > 0) {
          activeTaskId.value = tasks.value[0].id;
          activeTask.value = tasks.value[0];
        } else if (activeTaskId.value) {
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

    function switchActiveTask(t) {
      activeTaskId.value = t.id;
      activeTask.value = t;
      connectTaskChannels(t.id);
    }

    // =========================================================================
    // WebSocket 推流 (日志与时序性能)
    // =========================================================================

    function connectTaskChannels(taskId) {
      if (!taskId) return;

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

      // 4. 加载历史指标初始化图表
      loadHistoricalMetrics(taskId);
    }

    async function loadHistoricalMetrics(taskId) {
      try {
        const res = await fetch(`${apiBase}/api/metrics/${taskId}?limit=300`);
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

        // DOM / Heap 图表
        domChart = echarts.init(domEl);
        domChart.setOption({
          title: { text: 'Chrome 渲染端指标 (DOM / Listeners / JSHeap)', textStyle: { color: '#8b9bb4', fontSize: 13 } },
          tooltip: { trigger: 'axis' },
          legend: { data: ['DOM 节点数', '事件监听器', 'V8 JS堆 (MB)'], textStyle: { color: '#8b9bb4' } },
          grid: { left: '3%', right: '4%', bottom: '3%', containLabel: true },
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
          title: { text: '伴生 UE5 引擎与 WebRTC 像素流 (CPU / 内存 / FPS)', textStyle: { color: '#8b9bb4', fontSize: 13 } },
          tooltip: { trigger: 'axis' },
          legend: { data: ['UE5 CPU (%)', 'UE5 内存 (MB)', 'WebRTC FPS'], textStyle: { color: '#8b9bb4' } },
          grid: { left: '3%', right: '4%', bottom: '3%', containLabel: true },
          xAxis: { type: 'category', data: [], axisLine: { lineStyle: { color: '#233354' } } },
          yAxis: [
            { type: 'value', name: 'CPU / 内存', axisLine: { lineStyle: { color: '#233354' } }, splitLine: { lineStyle: { color: '#131b2e' } } },
            { type: 'value', name: 'FPS', max: 60, axisLine: { lineStyle: { color: '#233354' } }, splitLine: { show: false } }
          ],
          series: [
            { name: 'UE5 CPU (%)', type: 'line', smooth: true, data: [], itemStyle: { color: '#ff5252' } },
            { name: 'UE5 内存 (MB)', type: 'line', smooth: true, data: [], itemStyle: { color: '#00e676' } },
            { name: 'WebRTC FPS', type: 'line', yAxisIndex: 1, smooth: true, data: [], itemStyle: { color: '#3a7bd5' } }
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
        initCharts();
        if (activeTaskId.value) {
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
      applyTemplate,
      submitCreateTask,
      startTask,
      stopTask,
      switchActiveTask,
      viewBugDetail,
      syncZenTao
    };
  }
});

app.mount('#app');
