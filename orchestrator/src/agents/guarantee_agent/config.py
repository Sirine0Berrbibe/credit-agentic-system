from typing import Optional

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    azure_openai_endpoint: Optional[str] = None
    azure_openai_key: Optional[str] = None
    azure_openai_deployment: Optional[str] = None
    azure_openai_api_version: str = "2025-01-01-preview"
    mcp_server_url: str = "http://localhost:8003"
    log_level: str = "INFO"

    model_config = SettingsConfigDict(
        env_file=".env",
        case_sensitive=False,
        extra="ignore",
    )

    @field_validator("azure_openai_endpoint", mode="before")
    @classmethod
    def strip_trailing_slash(cls, v: Optional[str]) -> Optional[str]:
        return v.rstrip("/") if v else v


settings = Settings()
