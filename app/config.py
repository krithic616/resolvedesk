"""Environment configuration. API keys are local demo credentials, not bank credentials."""

from functools import lru_cache

from pydantic import SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    database_url: str = "sqlite:///./resolvedesk.db"
    agent_api_key: SecretStr
    manager_api_key: SecretStr
    auditor_api_key: SecretStr

    @model_validator(mode="after")
    def validate_keys(self):
        values = [
            self.agent_api_key.get_secret_value(),
            self.manager_api_key.get_secret_value(),
            self.auditor_api_key.get_secret_value(),
        ]
        if any(len(value) < 32 for value in values) or len(set(values)) != 3:
            raise ValueError("Configure three distinct API keys of at least 32 characters")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
