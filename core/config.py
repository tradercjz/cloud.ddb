from pydantic import EmailStr, Field
from pydantic_settings import BaseSettings 

from typing import Literal, Optional

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
    
    RAG_MODE: Literal["local", "graph"] = Field(
        default="local", 
        description="The retrieval strategy to use. 'local' for file-based vector search, 'graph' for the external graph RAG API."
    )
    GRAPH_RAG_API_URL: Optional[str] = Field(None, description="The URL for the Graph RAG query endpoint.")
    GRAPH_RAG_API_KEY: Optional[str] = Field(None, description="The API key for the Graph RAG service.")
    
    JINA_API_KEY: Optional[str] = Field(None, description="The API key for Jina AI Embedding service.")
    FAISS_INDEX_PATH: Optional[str] = Field(
        default="my_docs_advanced.index", 
        description="Path to the pre-built Faiss index file."
    )
    FAISS_CHUNKS_PATH: Optional[str] = Field(
        default="my_docs_chunks_advanced.pkl", 
        description="Path to the pickled document chunks corresponding to the Faiss index."
    )
    
    EMAIL_SERVICE_MODE: Literal["mock", "real"] = Field(
        default="real",
        description="'mock' to print emails to console, 'real' to send actual emails."
    )
    SMTP_HOST: Optional[str] = Field(None, description="SMTP server host.")
    SMTP_PORT: Optional[int] = Field(587, description="SMTP server port (587 for TLS is recommended).")
    SMTP_USER: Optional[str] = Field(None, description="Username for SMTP login.")
    SMTP_PASSWORD: Optional[str] = Field(None, description="Password for SMTP login (use App Password for services like Gmail).")
    EMAILS_FROM_EMAIL: Optional[EmailStr] = Field(None, description="The 'From' email address for outgoing emails.")
    EMAILS_FROM_NAME: Optional[str] = Field("DolphinDB Cloud Service", description="The 'From' name for outgoing emails.")
    EMAIL_VERIFICATION_CODE_EXPIRE_MINUTES: int = Field(10, description="Minutes until the verification code expires.")

    class Config:
        case_sensitive = True
        env_file = ".env"

settings = Settings()