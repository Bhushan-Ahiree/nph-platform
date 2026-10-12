# apps/api/config/settings.py
import os
from pydantic_settings import BaseSettings, SettingsConfigDict

class AppSettings(BaseSettings):
    """Centralized environment configurations with strict validation rules."""
    
    # Core API Configurations
    PROJECT_NAME: str = "NPH Property Intelligence Core"
    VERSION: str = "1.0.0"
    DEBUG: bool = False
    
    # Security Configurations
    JWT_SECRET: str  # Required: no default, startup fails if missing
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    
    # Database Configurations
    MONGO_URI: str = os.getenv("MONGO_URI", "")
    
    # Force reading of the system level .env file from root directory
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

# Initialize a single immutable settings instance across the application process
settings = AppSettings()