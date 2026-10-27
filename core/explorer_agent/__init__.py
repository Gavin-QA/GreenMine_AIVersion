def __getattr__(name: str):
    if name == "ExplorerAgent":
        from .agent import ExplorerAgent
        return ExplorerAgent
    raise AttributeError(f"module '{__name__}' has no attribute '{name}'")

