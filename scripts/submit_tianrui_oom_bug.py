# -*- coding: utf-8 -*-
"""
向禅道提交天瑞大屏巡检模型漫游 viewFlyToModel 内存严重泄漏 OOM 缺陷
归属：数字孪生系统 (ID: 11) / 马边天瑞 (ID: 134)
指派：周书鹏 (zhoushupeng)
"""

import sys
import json
from pathlib import Path
from datetime import datetime

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

PROJECT_ROOT = Path(__file__).parent.parent.resolve()
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from utils.zentao_sync import ZenTaoClient

def build_steps_html() -> str:
    html = """
<p><strong>【缺陷概述】</strong></p>
<p>天瑞数字孪生大屏在待机静置状态下内存稳定（1小时仅微增83MB），但在进入【巡检】模块点击不同配电室/设备模型执行漫游（<code>viewFlyToModel</code>）时，三维端存在极严重的未卸载与重复实例化漏洞。<strong>单次模型切换泄漏 1.5GB ~ 2.2GB 专用虚拟内存（Private Commit）</strong>。连续点击多次后，专用内存撑满至 <strong>44.8 GB</strong>，导致 Windows 页面文件耗尽并引发测试机整机 OOM 蓝屏与崩溃强制退出。</p>

<hr/>
<p><strong>【测试环境】</strong></p>
<ul>
  <li>客户端：<code>se-launcher-tianrui.exe</code> (Electron 启动器)</li>
  <li>伴生引擎：<code>tianrui.exe</code> (UE 5.8.2 Development PCD3D_SM6)</li>
  <li>操作系统：Windows 11 64位, AMD Ryzen 5 9600X, 32GB 物理内存, RTX 5060 Ti</li>
</ul>

<hr/>
<p><strong>【复现步骤】</strong></p>
<ol>
  <li>冷启动天瑞大屏客户端，进入主界面（记录此时 UE 专用提交 Commit 初始基线为 <strong>8.08 GB</strong>，物理内存 300MB）；</li>
  <li>点击进入顶部【巡检】模块，在设备列表中点击<strong>【地面10kv配电室】</strong>，视口触发飞行动画并加载模型；</li>
  <li>点击切换到列表中另一个设备<strong>【地面25kv配电室】</strong>；</li>
  <li>再次点击切回刚刚已看过的<strong>【地面10kv配电室】</strong>；</li>
  <li>在列表中来回切换 5~10 次不同的巡检模型。</li>
</ol>

<hr/>
<p><strong>【实际结果 (Actual Result)】</strong></p>
<p>旧点位的模型 Actor、动态材质、阴影投射光源和 D3D12 光追管线（RTPSO）完全没有执行销毁或缓存去重，每次切换均产生阶梯式单向暴涨，即使切回同一个模型依然重复实例化叠加：</p>
<table border="1" cellpadding="6" cellspacing="0" style="border-collapse:collapse;width:100%;font-size:13px;border-color:#cbd5e1;">
  <tr style="background:#f1f5f9;">
    <th>步骤</th>
    <th>操作动作</th>
    <th>实测时间</th>
    <th>UE Commit (专用提交/虚拟内存)</th>
    <th>单步净暴涨量 (&Delta;)</th>
    <th>累计暴涨总量</th>
  </tr>
  <tr>
    <td>0</td>
    <td>冷启动初始基线 (首页)</td>
    <td>13:55:32</td>
    <td>8,270.7 MB (8.08 GB)</td>
    <td>-</td>
    <td>基准线</td>
  </tr>
  <tr>
    <td>1</td>
    <td>点击【地面10kv配电室】</td>
    <td>13:56:11</td>
    <td>10,485.1 MB (10.24 GB)</td>
    <td><strong style="color:#dc2626;">+2,214.4 MB (+2.16 GB)</strong></td>
    <td>+2.16 GB</td>
  </tr>
  <tr>
    <td>2</td>
    <td>切换到【地面25kv配电室】</td>
    <td>13:57:20</td>
    <td>12,075.0 MB (11.79 GB)</td>
    <td><strong style="color:#dc2626;">+1,589.9 MB (+1.55 GB)</strong></td>
    <td>+3.71 GB</td>
  </tr>
  <tr>
    <td>3</td>
    <td>切回【地面10kv配电室】</td>
    <td>13:58:31</td>
    <td>12,852.6 MB (12.55 GB)</td>
    <td><strong style="color:#dc2626;">+777.6 MB (+0.76 GB)</strong></td>
    <td><strong style="color:#dc2626;">+4.47 GB</strong></td>
  </tr>
</table>

<p><strong>连续多点位巡检后：</strong>UE Commit 专用提交一路狂飙至 <strong>44,780.5 MB (43.73 GB)</strong>，物理 RAM 爆满，Windows 42GB 页面文件写死，全系统可用虚拟内存仅剩 4.3GB，最终全机瘫痪卡死。</p>

<hr/>
<p><strong>【预期结果 (Expected Result)】</strong></p>
<p>1. 视口飞离旧点位时，应自动卸载/隐藏上一模型资源（或对其流送关卡进行卸载）；<br/>
2. 对于已加载过的模型应建立单例缓存池直接复用，切回已看过的模型时不应产生新的大额内存申请；<br/>
3. 多次来回切换后，UE 专用提交 Commit 应保持在稳定水线，单次波动应 &le; 50MB。</p>

<hr/>
<p><strong>【底层日志证据链 (tianrui.log)】</strong></p>
<pre style="background:#0f172a;color:#f8fafc;padding:12px;border-radius:6px;font-family:Consolas,monospace;font-size:12px;overflow-x:auto;">
[13:57:10] 前端发送事件: {"strUEEventKey":"viewFlyToModel","data":{"name":"地面25kv配电室","type":"巡检"}}
[13:57:10] LogRHI: Display: Encountered a new ray tracing PSO: 1092944288
[13:57:10] LogD3D12RHI: Creating RTPSO with 79 shaders (0 cached, 1 new) took 19.27 ms. Compile time 13.88 ms, link time 5.35 ms.
[13:57:10] LogRenderer: Warning: [VSM] One Pass Projection max lights overflow. If you see shadow artifacts, decrease the amount of local lights per pixel.
[13:58:24] 前端发送事件: {"strUEEventKey":"viewFlyToModel","data":{"name":"地面10kv配电室","type":"巡检"}}
</pre>

<hr/>
<p><strong>【三维修复建议 (指派负责人：周书鹏)】</strong></p>
<ol>
  <li><strong>Actor / Level 生命周期闭环</strong>：在 <code>viewFlyToModel</code> 蓝图接收新目标时，先对前一处配电室模型调用 <code>DestroyActor</code> 或 <code>UnloadStreamLevel</code>；</li>
  <li><strong>模型单例缓存池</strong>：对常用场景资产做去重单例管理，已加载过的模型二次飞入时仅做相机 Transform 移动与可见性显示，避免重复实例化；</li>
  <li><strong>主动 GC 与材质显存回收</strong>：在区域切换阶段触发垃圾回收（如 <code>CollectGarbage</code>），释放未引用的材质实例与纹理，防止光追 RTPSO 与 VSM 阴影投射光源无限堆叠；</li>
  <li><strong>POI 摄像头材质池</strong>：排查密集轮询的 <code>BP_POI_Camera_C</code>，避免每次切点位重复生成未销毁的 Dynamic Texture。</li>
</ol>
"""
    return html.strip()

def submit():
    client = ZenTaoClient()
    print("🔌 正在连接禅道系统...")
    
    product_id = 11      # 数字孪生系统
    project_id = 134     # 马边天瑞
    assignee = "zhoushupeng"  # 周书鹏
    severity = 1         # 致命
    pri = 1              # 最高优先级
    title = "【性能严重缺陷/OOM宕机】天瑞大屏巡检模块切换设备模型(viewFlyToModel)未做资源卸载，单次切换泄漏1.5~2GB虚拟内存(Commit)，累计撑满44.8GB导致宿主机死机"
    
    steps_html = build_steps_html()

    print(f"🚀 正在向禅道提交缺陷...")
    print(f"  • 所属产品: 数字孪生系统 (ID: {product_id})")
    print(f"  • 所属项目: 马边天瑞 (ID: {project_id})")
    print(f"  • 严重程度: {severity} (致命)")
    print(f"  • 指派人员: 周书鹏 ({assignee})")
    print(f"  • 缺陷标题: {title}")

    try:
        res = client.submit_bug(
            product_id=product_id,
            title=title,
            steps_html=steps_html,
            severity=severity,
            pri=pri,
            bug_type="codeerror",
            assigned_to=assignee,
            project_id=project_id,
        )
        zen_id = res.get("id")
        print(f"\n🎉 缺陷已成功创建！禅道 ID: #{zen_id}")
        print(f"🔗 直达查看链接: {client.url}/index.php?m=bug&f=view&bugID={zen_id}")

        # 持久化记录到本地缺陷库
        local_bug_id = f"BUG-{datetime.now().strftime('%Y%m%d')}-001"
        bug_entry = {
            "id": local_bug_id,
            "zentao_id": str(zen_id),
            "app": "tianrui",
            "title": title,
            "severity": severity,
            "priority": pri,
            "status": "已提单",
            "date": datetime.now().strftime("%Y-%m-%d"),
            "assignee": "周书鹏",
            "assignee_account": assignee,
            "module": "巡检系统 / viewFlyToModel",
            "error_log": "[OOM] UE Commit Memory Leaked 44.8GB across viewFlyToModel calls",
            "analysis_notes": "三维资产在 viewFlyToModel 漫游切换中未卸载，单次泄漏1.5~2GB Commit，导致宿主机页面文件写满暴毙",
            "created_at": datetime.now().isoformat(),
        }

        # 写入 global_bugs_tianrui.json
        tianrui_bugs_file = PROJECT_ROOT / "artifacts" / "bugs" / "global_bugs_tianrui.json"
        tianrui_bugs = []
        if tianrui_bugs_file.exists():
            try:
                with open(tianrui_bugs_file, "r", encoding="utf-8") as f:
                    tianrui_bugs = json.load(f)
            except Exception:
                tianrui_bugs = []
        
        tianrui_bugs.insert(0, bug_entry)
        with open(tianrui_bugs_file, "w", encoding="utf-8") as f:
            json.dump(tianrui_bugs, f, ensure_ascii=False, indent=2)
        print(f"💾 本地缺陷库已自动归档: {tianrui_bugs_file.name}")

        return zen_id
    except Exception as e:
        print(f"❌ 提单失败: {e}")
        raise e

if __name__ == "__main__":
    submit()

