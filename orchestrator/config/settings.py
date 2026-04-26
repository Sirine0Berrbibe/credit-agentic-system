"""
Configuration - Architecture Agentic AICredits 2026
Centralise les variables d'environnement et paramètres
"""
import os
import logging
from typing import Optional
from dataclasses import dataclass
from enum import Enum
from dotenv import load_dotenv

# Load .env file at startup
load_dotenv()

logger = logging.getLogger(__name__)


class Environment(str, Enum):
    """Environnements supportés"""
    DEVELOPMENT = "development"
    STAGING = "staging"
    PRODUCTION = "production"


class LLMProvider(str, Enum):
    """Fournisseurs LLM supportés"""
    AZURE_OPENAI = "azure_openai"
    OPENAI = "openai"


@dataclass
class AzureOpenAIConfig:
    """Configuration Azure OpenAI API"""
    endpoint: str
    api_key: str
    deployment: str
    api_version: str

    @classmethod
    def from_env(cls) -> "AzureOpenAIConfig":
        """Charge depuis variables d'environnement"""
        return cls(
            endpoint=os.getenv("AZURE_OPENAI_ENDPOINT", "").rstrip("/"),
            api_key=os.getenv("AZURE_OPENAI_KEY", ""),
            deployment=os.getenv("AZURE_OPENAI_DEPLOYMENT", "gpt-5.4-mini"),
            api_version=os.getenv("AZURE_OPENAI_API_VERSION", "2025-01-01-preview"),
        )

    def validate(self) -> bool:
        """Valide la configuration"""
        return all([self.endpoint, self.api_key, self.deployment, self.api_version])

    def get_validation_errors(self) -> list:
        """Liste les erreurs de validation"""
        errors = []
        if not self.endpoint:
            errors.append("AZURE_OPENAI_ENDPOINT vide ou manquant")
        if not self.api_key:
            errors.append("AZURE_OPENAI_KEY vide ou manquant")
        if not self.deployment:
            errors.append("AZURE_OPENAI_DEPLOYMENT vide ou manquant")
        if not self.api_version:
            errors.append("AZURE_OPENAI_API_VERSION vide ou manquant")
        return errors


@dataclass
class MCPServerConfig:
    """Configuration MCP Scoring Engine"""
    host: str = "localhost"
    port: int = 8000
    timeout: int = 30
    protocol: str = "http"

    @property
    def base_url(self) -> str:
        return f"{self.protocol}://{self.host}:{self.port}"

    @classmethod
    def from_env(cls) -> "MCPServerConfig":
        """Charge depuis variables d'environnement"""
        return cls(
            host=os.getenv("MCP_HOST", "localhost"),
            port=int(os.getenv("MCP_PORT", "8000")),
            timeout=int(os.getenv("MCP_TIMEOUT", "30")),
            protocol=os.getenv("MCP_PROTOCOL", "http"),
        )


@dataclass
class AppConfig:
    """Configuration principale de l'application"""
    # Environnement
    env: Environment = Environment.DEVELOPMENT
    debug: bool = False
    
    # LLM
    llm_provider: LLMProvider = LLMProvider.AZURE_OPENAI
    azure_openai: AzureOpenAIConfig = None
    
    # MCP Integration
    mcp_server: MCPServerConfig = None
    
    # Agents
    max_retries: int = 3
    timeout_seconds: int = 60
    max_tool_calls: int = 20
    
    # Orchestrator
    service_port: int = 8001
    service_host: str = "0.0.0.0"
    log_level: str = "INFO"
    
    # Kafka (optionnel pour communication inter-agents)
    kafka_broker: Optional[str] = None
    kafka_topic_prefix: str = "creditage"
    
    @classmethod
    def from_env(cls) -> "AppConfig":
        """Charge toute la configuration depuis l'environnement"""
        env = Environment(os.getenv("APP_ENV", "development"))
        
        azure_openai = AzureOpenAIConfig.from_env()
        if not azure_openai.validate():
            errors = azure_openai.get_validation_errors()
            warning_msg = "Configuration Azure OpenAI incomplète:\n  " + "\n  ".join(errors)
            logger.warning(warning_msg)
            # Continue avec une config incomplète au lieu de lever une exception
        
        mcp_server = MCPServerConfig.from_env()
        
        return cls(
            env=env,
            debug=os.getenv("DEBUG", "false").lower() == "true",
            azure_openai=azure_openai,
            mcp_server=mcp_server,
            max_retries=int(os.getenv("MAX_RETRIES", "3")),
            timeout_seconds=int(os.getenv("TIMEOUT_SECONDS", "60")),
            max_tool_calls=int(os.getenv("MAX_TOOL_CALLS", "20")),
            service_port=int(os.getenv("SERVICE_PORT", "8001")),
            service_host=os.getenv("SERVICE_HOST", "0.0.0.0"),
            log_level=os.getenv("LOG_LEVEL", "INFO"),
            kafka_broker=os.getenv("KAFKA_BROKER"),
            kafka_topic_prefix=os.getenv("KAFKA_TOPIC_PREFIX", "creditage"),
        )


# Singleton global
_config: Optional[AppConfig] = None


def get_config() -> AppConfig:
    """Récupère la configuration (lazy load)"""
    global _config
    if _config is None:
        _config = AppConfig.from_env()
    return _config


def reset_config():
    """Reset config (utile pour tests)"""
    global _config
    _config = None
