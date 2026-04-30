from pydantic_settings import BaseSettings
from pydantic import Field


class Settings(BaseSettings):
    azure_openai_endpoint: str = Field(default="", env="AZURE_OPENAI_ENDPOINT")
    azure_openai_key: str = Field(default="", env="AZURE_OPENAI_KEY")
    azure_openai_deployment: str = Field(default="gpt-4.1", env="AZURE_OPENAI_DEPLOYMENT")
    azure_openai_api_version: str = Field(default="2025-01-01-preview", env="AZURE_OPENAI_API_VERSION")

    faiss_index_path: str = Field(default="", env="POLICY_FAISS_INDEX_PATH")
    embedding_model: str = Field(default="all-MiniLM-L6-v2", env="POLICY_EMBEDDING_MODEL")
    rag_top_k: int = Field(default=6, env="POLICY_RAG_TOP_K")
    log_level: str = Field(default="INFO", env="LOG_LEVEL")

    class Config:
        env_file = (".env", ".env.infrastructure", ".env.local")
        env_file_encoding = "utf-8"
        extra = "ignore"


settings = Settings()
