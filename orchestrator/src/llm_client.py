"""
LLM Client - Azure OpenAI Integration
Wrapper pour communication avec le modèle GPT
"""
import json
import re
from typing import Optional, List, Dict, Any
import httpx
import asyncio
from dataclasses import dataclass

from config.settings import AzureOpenAIConfig
from src.langsmith_tracing import (
    annotate_current_run,
    process_trace_inputs,
    process_trace_outputs,
    traceable,
)


@dataclass
class LLMResponse:
    """Réponse du modèle LLM"""
    content: str
    tool_calls: Optional[List[Dict[str, Any]]] = None
    finish_reason: str = "stop"
    usage: Optional[Dict[str, int]] = None


@dataclass
class TextGenerationResponse:
    text: str


class AzureOpenAIClient:
    """Client pour Azure OpenAI API"""

    def __init__(self, config: AzureOpenAIConfig):
        self.config = config
        self.base_url = f"{config.endpoint}/openai/deployments/{config.deployment}"
        self.headers = {
            "api-key": config.api_key,
            "Content-Type": "application/json",
        }
        self.client = httpx.AsyncClient(timeout=60.0)

    async def close(self):
        """Ferme le client HTTP"""
        await self.client.aclose()

    @traceable(
        name="Azure OpenAI Chat Completion",
        run_type="llm",
        process_inputs=process_trace_inputs,
        process_outputs=process_trace_outputs,
    )
    async def chat_completion(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
        top_p: float = 0.95,
        max_completion_tokens: int = 2000,
        tools: Optional[List[Dict[str, Any]]] = None,
    ) -> LLMResponse:
        """
        Appelle le modèle avec support des tools (function calling)
        """
        annotate_current_run(
            metadata={
                "provider": "azure_openai",
                "deployment": self.config.deployment,
                "api_version": self.config.api_version,
                "temperature": temperature,
                "top_p": top_p,
                "max_completion_tokens": max_completion_tokens,
                "tool_count": len(tools or []),
            }
        )
        payload = {
            "messages": messages,
            "temperature": temperature,
            "top_p": top_p,
            "max_completion_tokens": max_completion_tokens,
        }

        # Inclure les tools si fournis
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        url = f"{self.base_url}/chat/completions?api-version={self.config.api_version}"

        try:
            response = await self.client.post(
                url,
                headers=self.headers,
                json=payload,
            )
            response.raise_for_status()
            data = response.json()

            # Parser la réponse
            choice = data["choices"][0]
            message = choice["message"]

            # Extraire tool calls si présents
            tool_calls = None
            if "tool_calls" in message:
                tool_calls = message["tool_calls"]

            annotate_current_run(
                metadata={
                    "finish_reason": choice.get("finish_reason", "stop"),
                    "usage": data.get("usage") or {},
                }
            )

            return LLMResponse(
                content=message.get("content", ""),
                tool_calls=tool_calls,
                finish_reason=choice.get("finish_reason", "stop"),
                usage=data.get("usage"),
            )

        except httpx.HTTPStatusError as e:
            raise RuntimeError(f"Azure OpenAI API error: {e.response.text}")
        except Exception as e:
            raise RuntimeError(f"LLM call failed: {str(e)}")

    async def generate_thought(
        self,
        context: str,
        task: str,
        recent_observations: Optional[str] = None,
    ) -> str:
        """Génère une pensée/réflexion basée sur le contexte"""
        prompt = f"""Tu es un agent de décision de crédit avec une expertise en analyse financière.

CONTEXTE:
{context}

TÂCHE ACTUELLE:
{task}

{f'OBSERVATIONS RÉCENTES:{recent_observations}' if recent_observations else ''}

Réfléchis sur la prochaine étape. Sois concis et actionnable. Fournis ton analyse en JSON:
{{
    "thought": "ta réflexion brève",
    "confidence": 0.0-1.0,
    "reasoning_type": "thinking|planning|analysis"
}}
"""
        messages = [
            {"role": "system", "content": "Tu es un expert en analyse de crédits. Pense de manière logique et structurée."},
            {"role": "user", "content": prompt},
        ]

        response = await self.chat_completion(messages, temperature=0.3, max_completion_tokens=500)
        
        try:
            # Try to extract JSON from response
            json_match = re.search(r'\{[^{}]*\}', response.content, re.DOTALL)
            if json_match:
                return json.loads(json_match.group())
            else:
                return {
                    "thought": response.content,
                    "confidence": 0.7,
                    "reasoning_type": "thinking"
                }
        except json.JSONDecodeError:
            return {
                "thought": response.content,
                "confidence": 0.5,
                "reasoning_type": "thinking"
            }

    def format_tools_for_llm(self, tools: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Formate les tools en JSON Schema pour Azure OpenAI"""
        formatted_tools = []

        for tool_name, tool_obj in tools.items():
            tool_schema = {
                "type": "function",
                "function": {
                    "name": tool_name,
                    "description": tool_obj.description,
                    "parameters": tool_obj.parameters or {
                        "type": "object",
                        "properties": {},
                        "required": []
                    }
                }
            }
            formatted_tools.append(tool_schema)

        return formatted_tools

    async def decide_action(
        self,
        thought: str,
        available_tools: Dict[str, Any],
        context: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Utilise le LLM avec function calling pour décider l'action suivante
        """
        prompt = f"""Tu dois décider si un outil doit être utilisé pour progresser.

PENSÉE ACTUELLE:
{thought}

{f'CONTEXTE:{context}' if context else ''}

Si un outil est nécessaire, appelle-le. Sinon, termine le processus.
"""
        messages = [
            {"role": "system", "content": "Tu es un agent décisionnel. Utilise les outils intelligemment."},
            {"role": "user", "content": prompt},
        ]

        tools_schema = self.format_tools_for_llm(available_tools)

        try:
            response = await self.chat_completion(
                messages,
                tools=tools_schema if tools_schema else None,
                temperature=0.3,
                max_completion_tokens=1000,
            )

            if response.tool_calls:
                # Premier tool call
                first_call = response.tool_calls[0]
                return {
                    "tool_name": first_call["function"]["name"],
                    "tool_input": json.loads(first_call["function"]["arguments"]) if isinstance(first_call["function"]["arguments"], str) else first_call["function"]["arguments"],
                }
            else:
                # Pas de tool call, le processus se termine
                return None

        except Exception as e:
            print(f"Error in decide_action: {e}")
            return None

    async def generate_summary(
        self,
        state: str,
        task: str,
    ) -> str:
        """Génère un résumé final de la décision"""
        prompt = f"""Basé sur l'analyse suivante, fournis une conclusion claire et actionnable.

ÉTAT DE L'ANALYSE:
{state}

TÂCHE:
{task}

Fournis un résumé professionnel, concis et explicable au client.
"""
        messages = [
            {"role": "system", "content": "Tu es un expert en communication financière."},
            {"role": "user", "content": prompt},
        ]

        response = await self.chat_completion(messages, temperature=0.3, max_completion_tokens=1000)
        return response.content

    async def agenerate_text(
        self,
        prompt: str,
        system_prompt: str = "Tu es un assistant utile et concis.",
        temperature: float = 0.3,
        max_completion_tokens: int = 1000,
    ) -> TextGenerationResponse:
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt},
        ]
        response = await self.chat_completion(
            messages,
            temperature=temperature,
            max_completion_tokens=max_completion_tokens,
        )
        return TextGenerationResponse(text=response.content)
