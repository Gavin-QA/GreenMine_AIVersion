import json
import logging
from pathlib import Path
from typing import Optional, Union

from utils.paths import get_run_generated_cases_dir

logger = logging.getLogger("explorer_agent.trajectory")

class TrajectoryExporter:
    def __init__(
        self,
        run_dir: Optional[Union[Path, str]] = None,
        output_dir: Optional[Union[Path, str]] = None,
        run_id: Optional[str] = None
    ):
        self.run_dir = Path(run_dir) if run_dir else None
        if output_dir:
            self.output_dir = Path(output_dir)
        elif self.run_dir:
            self.output_dir = self.run_dir / "generated_cases"
        else:
            self.output_dir = None
        self.run_id = run_id

    def export_yaml(
        self,
        trajectory: list,
        run_id: Optional[str] = None,
        output_dir: Optional[Union[Path, str]] = None
    ) -> Optional[Path]:
        """实例方法导出 YAML 测试脚本"""
        target_run_id = run_id or self.run_id or "default"
        target_output_dir = Path(output_dir) if output_dir else self.output_dir
        return self.export_yaml_case(
            run_id=target_run_id,
            trajectory=trajectory,
            output_dir=target_output_dir
        )

    @staticmethod
    def export_yaml_case(run_id: str, trajectory: list, output_dir: Optional[Union[Path, str]] = None) -> Optional[Path]:
        """将探索轨迹导出为符合要求的 YAML 测试脚本，默认存放在本次运行的专属 generated_cases 目录下，避免污染正式用例库"""
        try:
            import yaml
            
            target_dir = Path(output_dir).resolve() if output_dir else get_run_generated_cases_dir(run_id)
            target_dir.mkdir(parents=True, exist_ok=True)
            yaml_path = target_dir / f"auto_generated_{run_id}.yaml"
            
            case_data = {
                "name": f"Auto Generated Case - {run_id}",
                "description": "由 ExplorerAgent 自主探索模式生成的自动化回归用例，涵盖全链路业务拓扑与操作闭环。",
                "steps": []
            }
            
            # --- 降噪与语义结构化逻辑 (Noise Reduction & Semantic Structuring) ---
            # 步骤 1：基础规范化与连续单步去重
            raw_steps = []
            for step in trajectory:
                step_type = str(step.get("type", "action")).lower()
                action_type = str(step.get("action_type", "")).upper()
                prompt = str(step.get("prompt", "")).strip()

                if step_type in ("chart_probe_skip", "skip"):
                    continue

                step_dict = {}
                if step_type in ("click", "hover", "action"):
                    step_dict["type"] = "action"
                    act = "CLICK" if step_type == "click" else ("HOVER" if step_type == "hover" else (action_type or "CLICK"))
                    clean_p = prompt
                    for pfx in ["[CLICK]", "[HOVER]", "[click]", "[hover]"]:
                        if clean_p.startswith(pfx):
                            clean_p = clean_p[len(pfx):].strip()
                            break
                    step_dict["prompt"] = f"[{act}] {clean_p}"
                elif step_type == "input":
                    step_dict["type"] = "input"
                    step_dict["prompt"] = prompt
                    step_dict["text"] = step.get("text", "")
                    if step.get("press_enter"):
                        step_dict["press_enter"] = True
                elif step_type == "zoom":
                    step_dict["type"] = "zoom"
                    step_dict["prompt"] = prompt
                    step_dict["direction"] = step.get("direction", "in")
                    step_dict["steps"] = int(step.get("steps", 3))
                elif step_type == "rotate_3d":
                    step_dict["type"] = "rotate_3d"
                    step_dict["prompt"] = prompt
                    step_dict["direction"] = step.get("direction", "left")
                    step_dict["distance"] = int(step.get("distance", 250))
                elif step_type == "scroll":
                    step_dict["type"] = "scroll"
                    step_dict["prompt"] = prompt
                    step_dict["direction"] = step.get("direction", "down")
                    step_dict["delta"] = int(step.get("delta", 300))
                elif step_type == "slide":
                    step_dict["type"] = "slide"
                    step_dict["prompt"] = prompt
                elif step_type == "wait":
                    step_dict["type"] = "wait"
                    step_dict["seconds"] = int(step.get("seconds", 2))
                elif step_type == "back":
                    step_dict["type"] = "action"
                    step_dict["prompt"] = "[CLICK] 路由历史回退"
                elif step_type == "canvas_stress_drag":
                    step_dict["type"] = "canvas_stress_drag"
                    step_dict["prompt"] = prompt or "中央三维数字孪生视口暴力抗压晃动检测"
                    step_dict["mode"] = step.get("mode", "hybrid")
                    step_dict["rounds"] = int(step.get("rounds", 3))
                    step_dict["radius"] = int(step.get("radius", 300))
                elif step_type in ("physics_sanity_check", "assert_no_console_errors", "memory_leak_check"):
                    step_dict["type"] = step_type
                    if prompt:
                        step_dict["prompt"] = prompt
                elif step_type in ("api_assert", "assert", "wait_for", "freeze_check"):
                    step_dict["type"] = step_type
                    step_dict["prompt"] = prompt
                else:
                    step_dict["type"] = "action"
                    step_dict["prompt"] = f"[CLICK] {prompt}"

                # 挂载业务上下文元数据（用于生成区块注释）
                step_dict["_meta_ui_path"] = step.get("ui_path") or []
                step_dict["_meta_container"] = step.get("container") or ""

                def _core_step(s):
                    return {k: v for k, v in s.items() if not k.startswith("_meta_")}

                # 过滤连续的 WAIT：如果上一步已经是 wait，跳过
                if step_dict["type"] == "wait" and raw_steps and raw_steps[-1].get("type") == "wait":
                    continue
                # 过滤连续完全相同的单步
                if raw_steps and _core_step(raw_steps[-1]) == _core_step(step_dict):
                    continue
                raw_steps.append(step_dict)

            def _step_cmp(s1, s2):
                return {k: v for k, v in s1.items() if not k.startswith("_meta_")} == {k: v for k, v in s2.items() if not k.startswith("_meta_")}

            # 步骤 2：周期性循环动作折叠去重 (周期 2 与周期 3)
            # 例如 [HOVER A, CLICK B, HOVER A, CLICK B, ...] 自动折叠为单个 [HOVER A, CLICK B]
            changed = True
            while changed:
                changed = False
                i = 0
                collapsed = []
                while i < len(raw_steps):
                    # 检查周期 2
                    if i + 3 < len(raw_steps) and _step_cmp(raw_steps[i], raw_steps[i+2]) and _step_cmp(raw_steps[i+1], raw_steps[i+3]):
                        pattern = [raw_steps[i], raw_steps[i+1]]
                        collapsed.extend(pattern)
                        i += 4
                        while i + 1 < len(raw_steps) and _step_cmp(raw_steps[i], pattern[0]) and _step_cmp(raw_steps[i+1], pattern[1]):
                            i += 2
                        changed = True
                    # 检查周期 3
                    elif i + 5 < len(raw_steps) and _step_cmp(raw_steps[i], raw_steps[i+3]) and _step_cmp(raw_steps[i+1], raw_steps[i+4]) and _step_cmp(raw_steps[i+2], raw_steps[i+5]):
                        pattern = [raw_steps[i], raw_steps[i+1], raw_steps[i+2]]
                        collapsed.extend(pattern)
                        i += 6
                        while i + 2 < len(raw_steps) and _step_cmp(raw_steps[i], pattern[0]) and _step_cmp(raw_steps[i+1], pattern[1]) and _step_cmp(raw_steps[i+2], pattern[2]):
                            i += 3
                        changed = True
                    else:
                        collapsed.append(raw_steps[i])
                        i += 1
                raw_steps = collapsed

            # 步骤 3：剔除连续孤立 HOVER (例如 HOVER A 紧跟着 HOVER B，则 HOVER A 是无意义悬停)
            pruned_steps = []
            for i in range(len(raw_steps)):
                curr = raw_steps[i]
                curr_prompt = curr.get("prompt", "")
                if curr.get("type") == "action" and curr_prompt.startswith("[HOVER]"):
                    if i + 1 < len(raw_steps):
                        next_step = raw_steps[i+1]
                        if next_step.get("type") == "action" and next_step.get("prompt", "").startswith("[HOVER]"):
                            continue
                pruned_steps.append(curr)

            # 步骤 4：剔除末尾无意义的 wait 或 hover
            while pruned_steps:
                last = pruned_steps[-1]
                if last.get("type") == "wait" or (last.get("type") == "action" and last.get("prompt", "").startswith("[HOVER]")):
                    pruned_steps.pop()
                else:
                    break

            # 步骤 5：格式化渲染带有业务层级注释的高可读性 YAML
            lines = [
                f'name: "Auto Generated Case - {run_id}"',
                f'description: "由 ExplorerAgent 自主探索模式生成的自动化回归用例，涵盖全链路业务拓扑与操作闭环。"',
                "",
                "steps:"
            ]

            last_section = None
            step_counter = 0

            # 暂存纯净步骤列表供兜底
            clean_steps_for_dump = []

            for s in pruned_steps:
                ui_path = s.pop("_meta_ui_path", None) or []
                container = s.pop("_meta_container", None) or ""

                clean_steps_for_dump.append(dict(s))

                # 构建当前业务区块描述
                section_parts = []
                if ui_path:
                    section_parts.append(" -> ".join([str(p) for p in ui_path if str(p).strip()]))
                if container:
                    section_parts.append(f"容器/面板: {container}")
                section_desc = " | ".join(section_parts) if section_parts else "全局基础交互"

                if section_desc != last_section:
                    last_section = section_desc
                    lines.append("")
                    lines.append("  # " + "=" * 76)
                    lines.append(f"  # 📍 业务区域：{section_desc}")
                    lines.append("  # " + "=" * 76)

                step_counter += 1
                stype = s.get("type", "action")
                sprompt = s.get("prompt", "")
                short_summary = sprompt.split("\n")[0][:45]
                lines.append(f"  # Step {step_counter}: [{stype.upper()}] {short_summary}")
                lines.append(f"  - type: {stype}")

                for k, v in s.items():
                    if k == "type":
                        continue
                    if isinstance(v, str):
                        safe_v = json.dumps(v, ensure_ascii=False)
                        lines.append(f"    {k}: {safe_v}")
                    elif isinstance(v, bool):
                        lines.append(f"    {k}: {str(v).lower()}")
                    elif isinstance(v, (int, float)):
                        lines.append(f"    {k}: {v}")
                    else:
                        lines.append(f"    {k}: {json.dumps(v, ensure_ascii=False)}")
                lines.append("")

            yaml_content = "\n".join(lines)

            # 严格双重校验生成的 YAML 合法性
            try:
                parsed_check = yaml.safe_load(yaml_content)
                assert isinstance(parsed_check, dict) and "steps" in parsed_check
                with open(yaml_path, "w", encoding="utf-8") as f:
                    f.write(yaml_content)
            except Exception as val_err:
                logger.error(f"⚠️ 生成的带有业务注释的 YAML 语法自检失败: {val_err}，正在回退基础序列化...")
                case_data["steps"] = clean_steps_for_dump
                with open(yaml_path, "w", encoding="utf-8") as f:
                    yaml.dump(case_data, f, allow_unicode=True, sort_keys=False)
                
            logger.info(f"📄 已自动生成结构化闭环测试用例 YAML: {yaml_path}")
            return yaml_path
        except Exception as e:
            logger.error(f"❌ 自动生成 YAML 用例失败: {e}")
            return None
