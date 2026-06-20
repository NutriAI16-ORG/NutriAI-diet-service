"""
Diet Service - Configuration
"""

from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    APP_NAME: str = "NutriAI Diet Service"
    DATABASE_URL: str = "postgresql://nutriai_user:nutriai_password@localhost:5432/nutriai"

    AZURE_OPENAI_ENDPOINT: str = ""
    AZURE_OPENAI_KEY: str = ""
    AZURE_OPENAI_DEPLOYMENT_NAME: str = "gpt-4"
    AZURE_OPENAI_API_VERSION: str = "2024-02-01"

    AZURE_SERVICE_BUS_CONNECTION_STRING: str = ""
    AZURE_SERVICE_BUS_TOPIC_NAME: str = "meal-reminders"

    APPLICATIONINSIGHTS_CONNECTION_STRING: str = ""

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = True


@lru_cache()
def get_settings() -> Settings:
    return Settings()
