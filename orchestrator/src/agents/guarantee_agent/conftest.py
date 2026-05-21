import sys
from pathlib import Path

# Ensure the orchestrator src/ directory is on sys.path so that
# `from langsmith_tracing import ...` resolves to src/langsmith_tracing.py
_src_root = Path(__file__).parent.parent.parent.parent  # .../orchestrator/src
if str(_src_root) not in sys.path:
    sys.path.insert(0, str(_src_root))

# Also add the guarantee_agent root so relative imports like
# `from agent.guarantee_agent import GuaranteeAgent` work from tests/
_agent_root = Path(__file__).parent
if str(_agent_root) not in sys.path:
    sys.path.insert(0, str(_agent_root))
