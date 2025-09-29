from pydantic_settings import BaseSettings 

from typing import Optional

class Settings(BaseSettings):
    PROJECT_NAME: str = "DolphinDB Cloud Service"
    API_V1_STR: str = "/api/v1"

    # Security
    SECRET_KEY: str
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30

    # Database
    DATABASE_URL: str

    # Redis for ARQ
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379

    # Aliyun
    ALIYUN_ACCESS_KEY_ID: str
    ALIYUN_ACCESS_KEY_SECRET: str
    ALIYUN_REGION_ID: str
    ALIYUN_SECURITY_GROUP_ID: str
    ALIYUN_VSWITCH_ID: str
    DDB_CONTAINER_IMAGE_URL: str
    
    CODE_SERVER_CONTAINER_IMAGE_URL: str

    OPENAI_API_KEY: str
    OPENAI_API_BASE_URL: Optional[str] = None
    OPENAI_MODEL_NAME: Optional[str] = "gpt-3.5-turbo" # 提供一个默认模型

    DDB_HOST: str
    DDB_PORT: int
    DDB_USER: str
    DDB_PASSWORD: str

    LLM_API_KEY: str
    LLM_BASE_URL: Optional[str] = None
    LLM_MODEL: Optional[str] = "google/gemini-2.5-flash" # 提供一个默认模型

    class Config:
        case_sensitive = True
        env_file = ".env"

settings = Settings()