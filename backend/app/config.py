"""
FastAPI 应用配置
使用 Pydantic Settings 管理配置
"""
from pathlib import Path
from dotenv import load_dotenv
from pydantic_settings import BaseSettings
from typing import List
import os
from urllib.parse import quote_plus
from pydantic import field_validator, model_validator

# 确保从项目根目录加载.env
env_path = Path(__file__).parent.parent / ".env"
load_dotenv(env_path)


class Settings(BaseSettings):
    """FastAPI 应用配置"""
    
    # 数据库配置
    db_connection: str = os.getenv("DB_CONNECTION", "mysql")
    db_host: str = os.getenv("DB_HOST", "127.0.0.1")
    db_port: str = os.getenv("DB_PORT", "3306")
    db_database: str = os.getenv("DB_DATABASE", "modelhub")
    db_username: str = os.getenv("DB_USERNAME", "root")
    db_password: str = os.getenv("DB_PASSWORD", "")
    
    # 数据库连接池配置
    db_pool_size: int = 10
    db_max_overflow: int = 20
    db_pool_recycle: int = 300
    db_pool_timeout: int = 30
    
    @property
    def database_url(self) -> str:
        """生成数据库连接 URL（用于同步操作）"""
        encoded_password = quote_plus(self.db_password)
        if self.db_connection == "mysql":
            return f"mysql+pymysql://{self.db_username}:{encoded_password}@{self.db_host}:{self.db_port}/{self.db_database}"
        return f"{self.db_connection}://{self.db_username}:{encoded_password}@{self.db_host}:{self.db_port}/{self.db_database}"
    
    # JWT 认证配置
    # 生产环境必须通过环境变量设置 SECRET_KEY，禁止使用默认值
    secret_key: str = os.getenv("SECRET_KEY", "CHANGE_ME_IN_PRODUCTION_USE_ENV_VAR")
    algorithm: str = os.getenv("ALGORITHM", "HS256")
    access_token_expire_minutes: int = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", 1440))

    @model_validator(mode='after')
    def _validate_critical_config(self):
        import warnings
        env = os.getenv("APP_ENV", "development")

        if self.secret_key == "CHANGE_ME_IN_PRODUCTION_USE_ENV_VAR":
            if env == "production":
                raise ValueError("生产环境禁止使用默认 SECRET_KEY，请在 .env 中设置 SECRET_KEY")
            warnings.warn(
                "SECRET_KEY 使用了不安全的默认值，请在 .env 中设置 SECRET_KEY 环境变量",
                stacklevel=2,
            )

        if not self.embedding_api_key:
            warnings.warn(
                "EMBEDDING_API_KEY 未配置，Embedding 和 RAG 功能将不可用",
                stacklevel=2,
            )

        if not self.rag_llm_api_key and not self.embedding_api_key:
            warnings.warn(
                "RAG_LLM_API_KEY 和 EMBEDDING_API_KEY 均未配置，所有 LLM 功能将不可用",
                stacklevel=2,
            )
        return self
    
    # CORS 配置
    cors_origins: List[str] = os.getenv(
        "CORS_ORIGINS",
        "http://127.0.0.1:5173,http://localhost:5173"
    ).split(",")

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _parse_cors_origins(cls, value):
        if isinstance(value, str):
            value = value.strip()
            if not value:
                return []
            if value.startswith("["):
                return value
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value
    
    # 嵌入模型配置
    embedding_model: str = os.getenv("EMBEDDING_MODEL", "text-embedding-v3")
    embedding_base_url: str = os.getenv("EMBEDDING_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")
    embedding_api_key: str = os.getenv("EMBEDDING_API_KEY", "")
    
    # ChromaDB 配置
    chroma_server_host: str = os.getenv("CHROMA_SERVER_HOST", "127.0.0.1")
    chroma_server_port: int = int(os.getenv("CHROMA_SERVER_PORT", "8002"))
    chroma_api_path: str = os.getenv("CHROMA_API_PATH", "/api/v1")

    # RAG 增强管线 LLM 配置（与 embedding 解耦）
    rag_llm_model: str = os.getenv("RAG_LLM_MODEL", "qwen-plus")
    rag_llm_api_key: str = os.getenv("RAG_LLM_API_KEY", "")
    rag_llm_base_url: str = os.getenv("RAG_LLM_BASE_URL", "")
    rag_domain_description: str = os.getenv(
        "RAG_DOMAIN_DESCRIPTION",
        "大学教务知识库，包含通知公告、规章制度、办事指南等官方文档"
    )

    # OCR配置
    ocr_provider: str = os.getenv("OCR_PROVIDER", "local")  # local, baidu, tencent, aliyun
    # 百度OCR配置
    baidu_ocr_api_key: str = os.getenv("BAIDU_OCR_API_KEY", "")
    baidu_ocr_secret_key: str = os.getenv("BAIDU_OCR_SECRET_KEY", "")
    # 腾讯OCR配置
    tencent_ocr_secret_id: str = os.getenv("TENCENT_OCR_SECRET_ID", "")
    tencent_ocr_secret_key: str = os.getenv("TENCENT_OCR_SECRET_KEY", "")
    # 阿里云OCR配置
    aliyun_ocr_access_key_id: str = os.getenv("ALIYUN_OCR_ACCESS_KEY_ID", "")
    aliyun_ocr_access_key_secret: str = os.getenv("ALIYUN_OCR_ACCESS_KEY_SECRET", "")
    aliyun_ocr_endpoint: str = os.getenv("ALIYUN_OCR_ENDPOINT", "ocr.cn-shanghai.aliyuncs.com")
    
    # 文件上传配置
    @property
    def uploads_dir(self) -> str:
        """上传目录路径"""
        project_root = Path(__file__).parent.parent
        uploads_path = project_root / "uploads"
        uploads_path.mkdir(exist_ok=True)
        return str(uploads_path)
    
    class Config:
        env_file = ".env"
        case_sensitive = False
        extra = "ignore"  # 忽略未定义的字段，不报错


settings = Settings()
