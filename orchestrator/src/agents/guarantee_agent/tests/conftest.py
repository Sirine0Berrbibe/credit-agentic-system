import sys
from pathlib import Path

# Add orchestrator root (parent of src/) so `import src.langsmith_tracing` resolves.
_orchestrator_root = Path(__file__).parent.parent.parent.parent.parent  # .../orchestrator
if str(_orchestrator_root) not in sys.path:
    sys.path.insert(0, str(_orchestrator_root))

# Add src/ so the bare `from langsmith_tracing import ...` fallback also resolves.
_src_root = _orchestrator_root / "src"
if str(_src_root) not in sys.path:
    sys.path.insert(0, str(_src_root))

# Add guarantee_agent root so `from agent.guarantee_agent import ...` works.
_agent_root = Path(__file__).parent.parent
if str(_agent_root) not in sys.path:
    sys.path.insert(0, str(_agent_root))
