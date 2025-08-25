from pydantic_settings import BaseSettings 

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

    class Config:
        case_sensitive = True
        env_file = ".env"

settings = Settings()