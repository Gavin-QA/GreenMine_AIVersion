import logging
from pathlib import Path

logger = logging.getLogger("explorer_agent.trajectory")

class TrajectoryExporter:
    @staticmethod
    def export_yaml_case(run_id: str, trajectory: list):
        """将探索轨迹导出为符合要求的 YAML 测试脚本"""
        try:
            import yaml
            
            yaml_dir = Path("test_cases").resolve()
            yaml_dir.mkdir(parents=True, exist_ok=True)
            yaml_path = yaml_dir / f"auto_generated_{run_id}.yaml"
            
            case_data = {
                "name": f"Auto Generated Case - {run_id}",
                "description": "由 ExplorerAgent 探索模式自动生成的闭环测试用例。",
                "steps": []
            }
            
            for step in trajectory:
                step_dict = {"type": step["type"]}
                if step["type"] == "action":
                    step_dict["prompt"] = f"[{step['action_type'].upper()}] {step['prompt']}"
                elif step["type"] == "wait":
                    step_dict["seconds"] = 3
                case_data["steps"].append(step_dict)
                
            with open(yaml_path, "w", encoding="utf-8") as f:
                yaml.dump(case_data, f, allow_unicode=True, sort_keys=False)
                
            logger.info(f"📄 已自动生成闭环测试用例 YAML: {yaml_path}")
        except Exception as e:
            logger.error(f"❌ 自动生成 YAML 用例失败: {e}")
