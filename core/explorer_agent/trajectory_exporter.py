import logging
from pathlib import Path
from typing import Optional

from utils.artifacts import get_run_generated_cases_dir

logger = logging.getLogger("explorer_agent.trajectory")

class TrajectoryExporter:
    @staticmethod
    def export_yaml_case(run_id: str, trajectory: list, output_dir: Optional[Path] = None) -> Optional[Path]:
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
            optimized_steps = []
            for step in trajectory:
                step_type = step["type"]
                action_type = step.get("action_type", "").upper()
                prompt = step.get("prompt", "")
                
                # 过滤连续的 WAIT：如果上一步已经是 wait，或者没操作，合并
                if step_type == "wait":
                    if not optimized_steps or optimized_steps[-1]["type"] == "wait":
                        continue  # 忽略多余的 wait
                        
                # 过滤连续重复的动作（例如因为没点中导致连续生成多个相同的点击）
                if step_type == "action" and optimized_steps:
                    last_step = optimized_steps[-1]
                    if last_step.get("type") == "action" and last_step.get("prompt") == f"[{action_type}] {prompt}":
                        continue
                        
                # 构建优化后的步
                step_dict = {"type": step_type}
                if step_type == "action":
                    step_dict["prompt"] = f"[{action_type}] {prompt}"
                elif step_type == "wait":
                    step_dict["seconds"] = 3
                elif step_type in ("api_assert", "assert", "wait_for"):
                    step_dict["prompt"] = prompt
                
                optimized_steps.append(step_dict)
            
            # --- 抽象与整理 (Abstraction) ---
            # 如果最后一个操作是 wait，可以剔除，没意义
            if optimized_steps and optimized_steps[-1]["type"] == "wait":
                optimized_steps.pop()
                
            case_data["steps"] = optimized_steps
            
            with open(yaml_path, "w", encoding="utf-8") as f:
                yaml.dump(case_data, f, allow_unicode=True, sort_keys=False)
                
            logger.info(f"📄 已自动生成（优化后）闭环测试用例 YAML: {yaml_path}")
            return yaml_path
        except Exception as e:
            logger.error(f"❌ 自动生成 YAML 用例失败: {e}")
            return None
