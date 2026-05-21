"""
Studio entrypoint for LangGraph.

This module exposes a compiled graph instance that LangGraph Studio / CLI can
load directly from `langgraph.json` without going through the FastAPI service.
"""

import os

# In local Studio sessions we only need to visualize and run the graph. If the
# sentence-transformer model is not cached yet, forcing offline mode makes the
# PolicyAgent fall back quickly to hard rules instead of hanging on network
# retries during graph startup.
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

from src.orchestrator_graph import OrchestratorGraph


agent = OrchestratorGraph().graph
graph = agent
