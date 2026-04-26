"""
Tests for Agent Orchestrator
Tests unitaires et d'intégration
"""
import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from src.base_agent import BaseAgent, AgentRole, Tool, AgentThought, AgentAction
from credit_agents.orchestrator.src.orchestrator_legacy import OrchestratorAgent
from config.settings import get_config


@pytest.fixture
def mock_azure_config():
    """Mock Azure OpenAI config"""
    config = MagicMock()
    config.azure_openai.endpoint = "https://test.openai.azure.com/"
    config.azure_openai.api_key = "test-key"
    config.azure_openai.deployment = "test-gpt"
    config.azure_openai.api_version = "2025-01-01-preview"
    config.mcp_server.base_url = "http://localhost:8000"
    config.mcp_server.timeout = 30
    return config


@pytest.fixture
async def orchestrator(mock_azure_config):
    """Create orchestrator instance"""
    with patch('config.settings.get_config', return_value=mock_azure_config):
        orch = OrchestratorAgent()
        yield orch
        # Cleanup
        if orch.llm_client:
            try:
                await orch.llm_client.close()
            except:
                pass


class TestBaseAgent:
    """Test BaseAgent functionality"""

    def test_agent_initialization(self):
        """Test agent creation"""
        # À implémenter avec un agent concrete
        pass

    def test_tool_registration(self):
        """Test tool registration"""
        # À implémenter
        pass

    def test_thought_adding(self):
        """Test adding thoughts to chain"""
        # À implémenter
        pass


class TestOrchestratorAgent:
    """Test Orchestrator Agent"""

    @pytest.mark.asyncio
    async def test_orchestrator_initialization(self, orchestrator):
        """Test orchestrator creates agents"""
        assert orchestrator.analyzer_agent is not None
        assert orchestrator.scorer_agent is not None
        assert orchestrator.risk_assessor is not None

    @pytest.mark.asyncio
    async def test_orchestrator_tools_registered(self, orchestrator):
        """Test orchestrator has required tools"""
        assert "dispatch_analysis" in orchestrator.tools
        assert "consolidate_results" in orchestrator.tools
        assert "make_final_decision" in orchestrator.tools

    @pytest.mark.asyncio
    async def test_think_step(self, orchestrator):
        """Test thinking step"""
        thought = await orchestrator.think({"test": "data"})
        assert isinstance(thought, AgentThought)
        assert thought.content is not None
        assert 0 <= thought.confidence <= 1

    @pytest.mark.asyncio
    async def test_decide_action_step(self, orchestrator):
        """Test action decision"""
        thought = AgentThought(content="test", confidence=0.8)
        action = await orchestrator.decide_action(thought)
        if action:  # First action only
            assert isinstance(action, AgentAction)
            assert action.tool_name in orchestrator.tools


class TestIntegration:
    """Integration tests"""

    @pytest.mark.asyncio
    async def test_full_decision_flow(self, orchestrator):
        """Test complete decision flow"""
        client_data = {
            "client_id": "TEST-001",
            "age": 30,
            "income": 50000,
            "employment_type": "permanent"
        }

        orchestrator.state.metadata["client_data"] = client_data

        # Run with mocked external calls
        with patch.object(orchestrator.scorer_agent, 'execute_tool') as mock_score:
            mock_score.return_value = MagicMock(
                success=True,
                result={"score": 0.75, "decision": "approved"}
            )

            # À compléter
            # response = await orchestrator.process(client_data)


@pytest.mark.asyncio
async def test_config_loading():
    """Test configuration loading"""
    config = get_config()
    assert config is not None
    # Config should be cacheable (singleton)
    config2 = get_config()
    assert config is config2


if __name__ == "__main__":
    # Run tests: pytest tests/test_orchestrator.py -v
    pytest.main([__file__, "-v", "-s"])
