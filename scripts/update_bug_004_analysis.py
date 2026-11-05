import json
from pathlib import Path

NEW_NOTES = """### 🤖 AI 架构师缺陷根因诊断与研发整改指引

**【核心技术定性】**：【前端代码健壮性漏洞】物联网历史属性接口数据为空时，前端遗漏可选链防护引发未捕获的 TypeError 崩溃

**【案发速览】**：
当点击底部导航 Tab【810溜井】标签时，页面触发加载该溜井的雷达料位计监控数据，向上游接口 `/iot/getInstancePropertiesHistoryQuery` 发起请求。后端因该时间段无采样点或设备未上报数据，正常响应返回业务空字典 `{"code": 0, "data": {}, "msg": "查询成功", "err": null}`。前端在解析设备属性时获取到的设备数据为 `undefined`（兜底为 `[]`），在构造 X 轴数据时直接执行了 `t.OnlineStatus.map(...)`，因缺失可选链导致对 `undefined` 调用 `.map()`，瞬间抛出 `Cannot read properties of undefined (reading 'map')` 并使组件崩溃。
*(注：此前分析推测的 crypto.randomUUID / 安全上下文假说已被代码实证推翻，本 Bug 与 BUG-20261030-001 无关。)*

#### 1. 底层案发机理与前端代码实证剖析
根据前端打包产物（`assets/intelligentOredrawing9-CqMr4PNL.js`）中的实际源码：
```javascript
// 接口调用处：
re.getIotInstancePropertiesHistoryQuery({deviceQueries: f}, n => {
    var e, h, b, g, m, p, d, y;
    // 当接口 data 为 {} 时，e[r] 找不到对应设备属性，降级为 t = []
    const t = ((e = n == null ? void 0 : n.data) == null ? void 0 : e[r]) || [];
    console.log(t);
    
    // 💥【直接致命崩溃行】：此处遗漏了可选链，t 上无 OnlineStatus 属性即为 undefined，直接调用 .map() 抛出异常！
    i.xAxisData = t.OnlineStatus.map(l => v._getDateFormatStringHHMM(new Date(l == null ? void 0 : l.formatTime)) || "--").reverse();
    
    // 🔍【铁证】：开发者在后续行中对同类字段却明确加上了可选链防护：
    i.orePassLevel = ((p = t == null ? void 0 : t.EmptyWarehouseHeight) == null ? void 0 : p.map(...));
    i.warningData = ((y = t == null ? void 0 : t.OnlineStatus) == null ? void 0 : y.map(...)) || [];
})
```
- **对比排查**：另一接口 `produceOrePass/getOrePassRuntimeStatistics` 返回 `{"totalRuntimeSeconds": 0, "dataPoints": []}` 时，前端通过 `(l.data?.dataPoints || []).map(...)` 实现了安全兜底，空数组 map 不会报错。
- **真凶确认**：正是 `/iot/getInstancePropertiesHistoryQuery` 响应空字典 `{}` 时，`t.OnlineStatus` 为 `undefined` 且未作保护触发了崩溃。

#### 2. 软件工程规范与责任划分
1. **直接责任 - 前端（陈贻雄）**：
   - 物联网大屏运行中，新装设备、断网离线、检修停机等无数据场景属于合法的日常业务状态。
   - 接口返回 HTTP 200 和 `code: 0` 且 `data: {}` 符合接口规范。
   - 前端未能进行防御性编程（Defensive Programming），空数据时应优雅降级展示“暂无数据”或空坐标轴，而绝不能直接抛 JS Uncaught Exception 导致界面瘫痪。
2. **协作事项 - 后端/IoT（梅本霞）**：
   - 需确认现场 810 溜井的雷达料位计设备编码及 IoT 数据采集服务是否正常入库，为何该设备历史数据为空。

#### 3. 推荐代码级修复补丁 (Copy-Paste Ready)
```javascript
// 前端修复补丁（陈贻雄负责）：
// intelligentOredrawing 组件 getHistory 回调内：
i.xAxisData = (t?.OnlineStatus?.map(l => v._getDateFormatStringHHMM(new Date(l?.formatTime)) || "--") || []).reverse();
```
"""

def update_json_file(file_path: Path):
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        
        updated = False
        if isinstance(data, list):
            for item in data:
                if item.get("id") == "BUG-20261030-004":
                    item["analysis_notes"] = NEW_NOTES
                    updated = True
        elif isinstance(data, dict):
            if data.get("id") == "BUG-20261030-004":
                data["analysis_notes"] = NEW_NOTES
                updated = True
        
        if updated:
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            print(f"Updated: {file_path}")
    except Exception as e:
        print(f"Failed {file_path}: {e}")

root = Path("D:/Auto/electron_ai_vision")
global_file = root / "artifacts/bugs/global_bugs_zhaiwan.json"
if global_file.exists():
    update_json_file(global_file)

for p in root.glob("reports/runs/**/BUG-20261030-004*.json"):
    update_json_file(p)

print("All updates finished.")

