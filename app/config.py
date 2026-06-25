"""
Diet Service - Configuration
"""

from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    APP_NAME: str = "NutriAI Diet Service"
    DATABASE_URL: str = "sqlite:///./test.db"

    AZURE_OPENAI_ENDPOINT: str = ""
    AZURE_OPENAI_KEY: str = ""
    AZURE_OPENAI_DEPLOYMENT_NAME: str = "gpt-5.1"
    AZURE_OPENAI_API_VERSION: str = "2024-02-01"
    AZURE_SERVICE_BUS_CONNECTION_STRING: str = ""
    AZURE_SERVICE_BUS_FULLY_QUALIFIED_NAMESPACE: str = ""  # e.g. "nutriai-sb-prod.servicebus.windows.net"
    AZURE_SERVICE_BUS_TOPIC_NAME: str = "email-notifications"

    APPLICATIONINSIGHTS_CONNECTION_STRING: str = ""

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = True


@lru_cache()
def get_settings() -> Settings:
    return Settings()
