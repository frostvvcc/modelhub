"""
FastAPI 应用初始化
"""
import os
os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"
from fastapi import FastAPI, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import RequestValidationError
from fastapi.requests import Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from app.config import settings
from app.database_async import async_engine
from app.routers import user, model, chat, vector, organization, permission, provider, bot, teaching_space
from app import services as services
from app.middleware.error_middleware import error_handler_middleware
import logging

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def create_app() -> FastAPI:
    """
    创建并配置 FastAPI 应用
    """
    app = FastAPI(
        title="ModelHub API - 大学综合检索对话平台",
        description="""
        ## ModelHub - 大学综合检索对话平台 API
        
        ### 核心功能
        
        - **组织架构管理**: 支持层级化组织架构（学校->学院->系->班级）
        - **权限管理**: 基于RBAC的层级化权限系统，支持权限继承
        - **知识库管理**: 组织级知识库管理，支持权限控制
        - **智能对话**: RAG增强的智能对话，支持组织上下文
        - **模型管理**: 模型供应商、基础模型和对话配置管理
        
        ### 认证
        
        所有API（除登录/注册外）都需要在请求头中携带JWT Token：
        ```
        Authorization: Bearer <token>
        ```
        
        ### 权限说明
        
        - 系统级权限：适用于所有组织
        - 组织级权限：仅适用于特定组织
        - 权限继承：下级组织自动继承上级组织的权限
        """,
        version="2.0.0",
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        contact={
            "name": "ModelHub Support",
            "email": "support@modelhub.com"
        },
        license_info={
            "name": "MIT License"
        }
    )
    
    # 添加 422 错误的异常处理器
    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        """处理请求验证错误（422）"""
        logger.error(f"422 错误 - 路径: {request.url.path}")
        logger.error(f"422 错误 - 详情: {exc.errors()}")
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content=jsonable_encoder({
                "success": False,
                "message": "请求参数验证失败",
                "code": 422,
                "details": exc.errors(),
            }),
        )

    # 添加错误处理中间件
    app.middleware("http")(error_handler_middleware)

    # CORS 配置放在最后注册，使其包住错误处理中间件，确保 4xx/5xx 响应也带 CORS 头。
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["Authorization"]
    )
    
    # 注册路由
    app.include_router(user.router, prefix="/user", tags=["用户管理"])
    app.include_router(model.router, prefix="/model", tags=["模型管理"])
    app.include_router(chat.router, prefix="/chat", tags=["对话"])
    app.include_router(vector.router, prefix="/vector", tags=["知识库管理"])
    app.include_router(organization.router, prefix="/organization", tags=["组织架构管理"])
    app.include_router(permission.router, prefix="/permission", tags=["权限管理"])
    app.include_router(provider.router, prefix="/provider", tags=["供应商配置管理"])
    app.include_router(bot.router, prefix="/bots", tags=["数字助理工厂"])
    app.include_router(teaching_space.router, prefix="/teaching-space", tags=["教学空间"])

    # 数据库初始化（改为延迟初始化，避免启动阻塞）
    @app.on_event("startup")
    async def startup():
        """应用启动时的初始化工作"""
        logger.info("应用启动中...")
        # 后台预加载 Reranker 模型，避免首请求延迟
        import asyncio
        async def _preload_reranker():
            try:
                from app.services.rag.reranker import _get_cross_encoder, RAG_RERANK_MODE
                if RAG_RERANK_MODE == "cross_encoder":
                    await _get_cross_encoder()
            except Exception as e:
                logger.warning(f"Reranker 预加载失败（非致命）: {e}")
        asyncio.create_task(_preload_reranker())
        logger.info("应用启动完成")
    
    @app.on_event("shutdown")
    async def shutdown():
        """应用关闭时的清理工作"""
        logger.info("应用正在关闭...")
        try:
            from app.services.rag.es_retrieval import close_es_client
            await close_es_client()
        except Exception as e:
            logger.warning(f"ES 客户端清理失败: {e}")
    
    # 健康检查
    @app.get("/health", tags=["系统"])
    async def health_check():
        """健康检查接口"""
        return {
            "status": "healthy",
            "message": "API is running",
            "version": "2.0.0"
        }
    
    return app
