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
                "description": "由 ExplorerAgent 探索模式自动生成的闭环测试用例。",
                "steps": []
            }
            
            # --- 降噪逻辑 (Noise Reduction) ---
            # 步骤 1：基础规范化与连续单步去重
            raw_steps = []
            for step in trajectory:
                step_type = step.get("type", "action")
                action_type = step.get("action_type", "").upper()
                prompt = step.get("prompt", "")
                
                step_dict = {"type": step_type}
                if step_type == "action":
                    step_dict["prompt"] = f"[{action_type}] {prompt}"
                elif step_type == "wait":
                    step_dict["seconds"] = 3
                elif step_type in ("api_assert", "assert", "wait_for"):
                    step_dict["prompt"] = prompt
                
                # 过滤连续的 WAIT：如果上一步已经是 wait，跳过
                if step_type == "wait" and raw_steps and raw_steps[-1].get("type") == "wait":
                    continue
                # 过滤连续相同单步
                if raw_steps and raw_steps[-1] == step_dict:
                    continue
                raw_steps.append(step_dict)

            # 步骤 2：周期性循环动作折叠去重 (周期 2 与周期 3)
            # 例如 [HOVER A, CLICK B, HOVER A, CLICK B, ...] 自动折叠为单个 [HOVER A, CLICK B]
            changed = True
            while changed:
                changed = False
                i = 0
                collapsed = []
                while i < len(raw_steps):
                    # 检查周期 2: raw_steps[i:i+2] == raw_steps[i+2:i+4]
                    if i + 3 < len(raw_steps) and raw_steps[i] == raw_steps[i+2] and raw_steps[i+1] == raw_steps[i+3]:
                        pattern = [raw_steps[i], raw_steps[i+1]]
                        collapsed.extend(pattern)
                        i += 4
                        while i + 1 < len(raw_steps) and raw_steps[i] == pattern[0] and raw_steps[i+1] == pattern[1]:
                            i += 2
                        changed = True
                    # 检查周期 3: raw_steps[i:i+3] == raw_steps[i+3:i+6]
                    elif i + 5 < len(raw_steps) and raw_steps[i] == raw_steps[i+3] and raw_steps[i+1] == raw_steps[i+4] and raw_steps[i+2] == raw_steps[i+5]:
                        pattern = [raw_steps[i], raw_steps[i+1], raw_steps[i+2]]
                        collapsed.extend(pattern)
                        i += 6
                        while i + 2 < len(raw_steps) and raw_steps[i] == pattern[0] and raw_steps[i+1] == pattern[1] and raw_steps[i+2] == pattern[2]:
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

            case_data["steps"] = pruned_steps
            
            with open(yaml_path, "w", encoding="utf-8") as f:
                yaml.dump(case_data, f, allow_unicode=True, sort_keys=False)
                
            logger.info(f"📄 已自动生成（优化后）闭环测试用例 YAML: {yaml_path}")
            return yaml_path
        except Exception as e:
            logger.error(f"❌ 自动生成 YAML 用例失败: {e}")
            return None
