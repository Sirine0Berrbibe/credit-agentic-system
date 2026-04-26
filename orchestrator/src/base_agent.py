"""
Base Agent Class - ReAct Pattern (Reasoning + Acting)
Implémente le pattern standard pour tous les agents
"""
from abc import ABC, abstractmethod
from enum import Enum
from typing import Any, Dict, List, Optional, Callable, Coroutine
from dataclasses import dataclass, field
from datetime import datetime
import asyncio
import json
from pydantic import BaseModel, Field


class AgentRole(str, Enum):
    """Rôles des agents dans l'architecture"""
    ORCHESTRATOR = "orchestrator"  # Routeur principal
    ANALYZER = "analyzer"           # Analyse des données client
    RISK_ASSESSOR = "risk_assessor" # Évaluation des risques
    COMPLIANCE = "compliance"       # Vérification compliance
    EXPLAINER = "explainer"         # Explication des décisions
    SCORER = "scorer"               # Scoring via MCP


@dataclass
class Tool:
    """Définition d'un outil utilisable par un agent"""
    name: str
    description: str
    handler: Callable[..., Coroutine[Any, Any, Any]]  # async function
    parameters: Dict[str, Any]  # JSON Schema pour les paramètres


@dataclass
class AgentThought:
    """Une étape de réflexion (Reasoning)"""
    timestamp: datetime = field(default_factory=datetime.utcnow)
    content: str = ""
    confidence: float = 0.0
    reasoning_type: str = "thinking"  # thinking|planning|analysis


@dataclass
class AgentAction:
    """Une action (Acting - appel d'outil)"""
    tool_name: str
    tool_input: Dict[str, Any]
    thought: str = ""


@dataclass
class AgentObservation:
    """Résultat d'une action (Observation)"""
    tool_name: str
    result: Any
    success: bool = True
    error: Optional[str] = None


class AgentMessage(BaseModel):
    """Message dans la conversation d'un agent"""
    role: str = Field(..., description="user|assistant|system")
    content: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    tool_calls: Optional[List[Dict[str, Any]]] = None
    tool_results: Optional[List[Dict[str, Any]]] = None


class AgentState(BaseModel):
    """État interne d'un agent"""
    agent_id: str
    role: AgentRole
    conversation_history: List[AgentMessage] = Field(default_factory=list)
    thought_chain: List[AgentThought] = Field(default_factory=list)
    action_history: List[AgentAction] = Field(default_factory=list)
    observations: List[AgentObservation] = Field(default_factory=list)
    current_task: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class BaseAgent(ABC):
    """
    Agent de base implémentant le pattern ReAct
    
    Thinking (T) -> Acting (A) -> Observing (O) -> Loop
    """

    def __init__(self, agent_id: str, role: AgentRole):
        self.agent_id = agent_id
        self.role = role
        self.state = AgentState(agent_id=agent_id, role=role)
        self.tools: Dict[str, Tool] = {}
        self.max_iterations = 20
        self.temperature = 0.7

    def register_tool(self, tool: Tool):
        """Enregistre un outil disponible pour cet agent"""
        self.tools[tool.name] = tool

    def add_message(self, role: str, content: str, tool_calls: Optional[List] = None,
                    tool_results: Optional[List] = None):
        """Ajoute un message à l'historique"""
        msg = AgentMessage(
            role=role,
            content=content,
            tool_calls=tool_calls,
            tool_results=tool_results
        )
        self.state.conversation_history.append(msg)

    def add_thought(self, content: str, confidence: float = 0.8, reasoning_type: str = "thinking"):
        """Ajoute une pensée au chain of thought"""
        thought = AgentThought(
            content=content,
            confidence=confidence,
            reasoning_type=reasoning_type
        )
        self.state.thought_chain.append(thought)

    async def execute_tool(self, action: AgentAction) -> AgentObservation:
        """Exécute un outil de manière sûre"""
        tool = self.tools.get(action.tool_name)
        if not tool:
            return AgentObservation(
                tool_name=action.tool_name,
                result=None,
                success=False,
                error=f"Tool '{action.tool_name}' not found"
            )

        try:
            result = await tool.handler(**action.tool_input)
            obs = AgentObservation(
                tool_name=action.tool_name,
                result=result,
                success=True
            )
            self.state.observations.append(obs)
            return obs
        except Exception as e:
            obs = AgentObservation(
                tool_name=action.tool_name,
                result=None,
                success=False,
                error=str(e)
            )
            self.state.observations.append(obs)
            return obs

    @abstractmethod
    async def think(self, input_data: Dict[str, Any]) -> AgentThought:
        """
        Étape de réflexion (Reasoning)
        Doit retourner la pensée et potentiellement une action
        """
        pass

    @abstractmethod
    async def decide_action(self, thought: AgentThought) -> Optional[AgentAction]:
        """Décide quelle action entreprendre basée sur la pensée"""
        pass

    @abstractmethod
    async def process(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """Traite l'input et retourne le résultat final"""
        pass

    async def run_react_loop(self, input_data: Dict[str, Any], max_iterations: Optional[int] = None) -> Dict[str, Any]:
        """
        Exécute la boucle ReAct complète
        T (thinking) -> A (acting) -> O (observing) -> Loop until done
        """
        if max_iterations is None:
            max_iterations = self.max_iterations

        iteration = 0
        while iteration < max_iterations:
            # THINKING
            thought = await self.think(input_data)
            self.add_thought(thought.content, thought.confidence, thought.reasoning_type)

            # DECIDING ACTION
            action = await self.decide_action(thought)
            if action is None:
                # Agent a décidé de terminer
                break

            self.state.action_history.append(action)

            # ACTING
            observation = await self.execute_tool(action)

            # Update input_data with observation for next iteration
            input_data["last_observation"] = observation.result
            input_data["last_success"] = observation.success

            iteration += 1

        # Récupère les résultats finaux
        return await self.process(input_data)

    def get_context(self) -> str:
        """
        Construit le contexte pour l'appel LLM
        Incluant l'historique et les observations récentes
        """
        context_parts = []

        # Pensées récentes
        if self.state.thought_chain:
            recent_thoughts = self.state.thought_chain[-3:]  # Les 3 dernières
            thoughts_str = "\n".join([f"- {t.content}" for t in recent_thoughts])
            context_parts.append(f"Recent thoughts:\n{thoughts_str}")

        # Tools disponibles
        if self.tools:
            tools_info = "\n".join([
                f"- {name}: {tool.description}" 
                for name, tool in self.tools.items()
            ])
            context_parts.append(f"Available tools:\n{tools_info}")

        # Observations récentes
        if self.state.observations:
            recent_obs = self.state.observations[-2:]
            obs_str = "\n".join([
                f"- {o.tool_name}: {o.result if o.success else f'ERROR: {o.error}'}"
                for o in recent_obs
            ])
            context_parts.append(f"Recent observations:\n{obs_str}")

        return "\n\n".join(context_parts)

    def reset_state(self):
        """Réinitialise l'état de l'agent"""
        self.state = AgentState(agent_id=self.agent_id, role=self.role)

    def get_summary(self) -> Dict[str, Any]:
        """Retourne un résumé de l'exécution"""
        return {
            "agent_id": self.agent_id,
            "role": self.role.value,
            "num_thoughts": len(self.state.thought_chain),
            "num_actions": len(self.state.action_history),
            "num_observations": len(self.state.observations),
            "avg_confidence": sum(t.confidence for t in self.state.thought_chain) / len(self.state.thought_chain) if self.state.thought_chain else 0,
            "conversation_turns": len(self.state.conversation_history),
            "metadata": self.state.metadata,
        }
