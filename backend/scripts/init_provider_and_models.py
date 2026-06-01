#!/usr/bin/env python3
"""
初始化供应商配置和模型数据
添加高质量的供应商和模型配置
"""
import asyncio
import sys
import json
from pathlib import Path

# 添加项目路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from app.database_async import AsyncSessionLocal
from app.mappers.provider_mapper import AsyncProviderMapper
from app.mappers.model_mapper import AsyncModelMapper
from app.models.model_info import ModelInfo
from app.utils.async_db import AsyncDB
from app.utils.logger_config import get_logger

logger = get_logger(__name__)


async def init_providers_and_models():
    """初始化供应商配置和模型数据"""
    async with AsyncSessionLocal() as db:
        try:
            # 1. 创建供应商配置
            logger.info("=" * 60)
            logger.info("开始初始化供应商配置和模型数据...")
            logger.info("=" * 60)
            
            providers_data = [
                {
                    "name": "OpenAI",
                    "code": "openai",
                    "provider_type": "openai",
                    "base_url": "https://api.openai.com/v1",
                    "api_key": None,  # 需要用户配置
                    "description": "OpenAI 官方 API，支持 GPT-4、GPT-3.5 等模型",
                    "is_active": True,
                    "is_default": True,
                    "priority": 100,
                    "rate_limit": 60,
                    "max_tokens": 4096,
                    "supported_model_types": "chatllm,embedding",
                    "config_json": json.dumps({
                        "timeout": 60,
                        "max_retries": 3,
                        "temperature_range": [0.0, 2.0]
                    })
                },
                {
                    "name": "阿里云通义千问",
                    "code": "aliyun",
                    "provider_type": "aliyun",
                    "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
                    "api_key": None,  # 需要用户配置
                    "description": "阿里云通义千问 API，支持 Qwen 系列模型",
                    "is_active": True,
                    "is_default": True,
                    "priority": 90,
                    "rate_limit": 100,
                    "max_tokens": 8192,
                    "supported_model_types": "chatllm,embedding",
                    "config_json": json.dumps({
                        "timeout": 60,
                        "max_retries": 3,
                        "region": "cn-beijing"
                    })
                },
                {
                    "name": "Anthropic Claude",
                    "code": "anthropic",
                    "provider_type": "anthropic",
                    "base_url": "https://api.anthropic.com/v1",
                    "api_key": None,  # 需要用户配置
                    "description": "Anthropic Claude API，支持 Claude 3 系列模型",
                    "is_active": True,
                    "is_default": False,
                    "priority": 85,
                    "rate_limit": 50,
                    "max_tokens": 200000,
                    "supported_model_types": "chatllm",
                    "config_json": json.dumps({
                        "timeout": 120,
                        "max_retries": 3,
                        "version": "2023-06-01"
                    })
                },
                {
                    "name": "OpenAI兼容本地服务",
                    "code": "local",
                    "provider_type": "local",
                    "base_url": "http://localhost:8000/v1",
                    "api_key": None,
                    "description": "兼容 OpenAI 协议的本地推理服务，支持 Qwen/Llama 等开源模型",
                    "is_active": True,
                    "is_default": False,
                    "priority": 50,
                    "rate_limit": None,
                    "max_tokens": None,
                    "supported_model_types": "chatllm,embedding",
                    "config_json": json.dumps({
                        "timeout": 300,
                        "max_retries": 1
                    })
                },
                {
                    "name": "自定义配置",
                    "code": "custom",
                    "provider_type": "custom",
                    "base_url": "",
                    "api_key": None,
                    "description": "自定义供应商配置",
                    "is_active": True,
                    "is_default": False,
                    "priority": 10,
                    "rate_limit": None,
                    "max_tokens": None,
                    "supported_model_types": "chatllm,embedding",
                    "config_json": None
                }
            ]
            
            created_providers = {}
            for provider_data in providers_data:
                existing = await AsyncProviderMapper.get_provider_by_code(db, provider_data["code"])
                if existing:
                    logger.info(f"✅ 供应商已存在: {provider_data['name']} ({provider_data['code']})")
                    created_providers[provider_data["code"]] = existing
                else:
                    provider = await AsyncProviderMapper.create_provider(
                        db,
                        **provider_data
                    )
                    logger.info(f"✅ 创建供应商: {provider.name} (ID: {provider.id}, Code: {provider.code})")
                    created_providers[provider_data["code"]] = provider
            
            await db.commit()
            
            # 2. 创建模型信息
            logger.info("")
            logger.info("开始创建模型信息...")
            
            models_data = [
                # OpenAI 模型
                {
                    "model_name": "gpt-4",
                    "type": "chatllm",
                    "provider_code": "openai",
                    "model_endpoint": "/chat/completions",
                    "describe": "GPT-4 是 OpenAI 最强大的语言模型，具有出色的推理能力和广泛的知识",
                    "version": "gpt-4",
                    "max_tokens": 8192,
                    "context_window": 8192,
                    "is_active": True,
                    "is_default": False,
                    "priority": 100
                },
                {
                    "model_name": "gpt-4-turbo",
                    "type": "chatllm",
                    "provider_code": "openai",
                    "model_endpoint": "/chat/completions",
                    "describe": "GPT-4 Turbo 是 GPT-4 的优化版本，速度更快，成本更低",
                    "version": "gpt-4-turbo-preview",
                    "max_tokens": 128000,
                    "context_window": 128000,
                    "is_active": True,
                    "is_default": False,
                    "priority": 95
                },
                {
                    "model_name": "gpt-3.5-turbo",
                    "type": "chatllm",
                    "provider_code": "openai",
                    "model_endpoint": "/chat/completions",
                    "describe": "GPT-3.5 Turbo 是快速且经济的对话模型",
                    "version": "gpt-3.5-turbo",
                    "max_tokens": 4096,
                    "context_window": 16385,
                    "is_active": True,
                    "is_default": False,
                    "priority": 80
                },
                {
                    "model_name": "text-embedding-3-large",
                    "type": "embedding",
                    "provider_code": "openai",
                    "model_endpoint": "/embeddings",
                    "describe": "OpenAI 最新的嵌入模型，支持 3072 维向量",
                    "version": "text-embedding-3-large",
                    "max_tokens": None,
                    "context_window": 8191,
                    "is_active": True,
                    "is_default": True,
                    "priority": 100
                },
                {
                    "model_name": "text-embedding-3-small",
                    "type": "embedding",
                    "provider_code": "openai",
                    "model_endpoint": "/embeddings",
                    "describe": "OpenAI 小型嵌入模型，速度快，成本低",
                    "version": "text-embedding-3-small",
                    "max_tokens": None,
                    "context_window": 8191,
                    "is_active": True,
                    "is_default": False,
                    "priority": 70
                },
                # 阿里云模型
                {
                    "model_name": "qwen3.6-plus",
                    "type": "chatllm",
                    "provider_code": "aliyun",
                    "model_endpoint": "/chat/completions",
                    "describe": "通义千问 Qwen3.6 Plus，适合毕业设计联调和复杂问答",
                    "version": "qwen3.6-plus",
                    "max_tokens": 8192,
                    "context_window": 128000,
                    "is_active": True,
                    "is_default": False,
                    "priority": 96
                },
                {
                    "model_name": "qwen-turbo",
                    "type": "chatllm",
                    "provider_code": "aliyun",
                    "model_endpoint": "/chat/completions",
                    "describe": "通义千问 Turbo 版本，速度快，适合实时对话",
                    "version": "qwen-turbo",
                    "max_tokens": 8192,
                    "context_window": 8192,
                    "is_active": True,
                    "is_default": True,
                    "priority": 90
                },
                {
                    "model_name": "qwen-plus",
                    "type": "chatllm",
                    "provider_code": "aliyun",
                    "model_endpoint": "/chat/completions",
                    "describe": "通义千问 Plus 版本，性能更强，适合复杂任务",
                    "version": "qwen-plus",
                    "max_tokens": 32000,
                    "context_window": 32000,
                    "is_active": True,
                    "is_default": False,
                    "priority": 85
                },
                {
                    "model_name": "qwen-max",
                    "type": "chatllm",
                    "provider_code": "aliyun",
                    "model_endpoint": "/chat/completions",
                    "describe": "通义千问 Max 版本，最强性能，适合复杂推理",
                    "version": "qwen-max",
                    "max_tokens": 8000,
                    "context_window": 8000,
                    "is_active": True,
                    "is_default": False,
                    "priority": 95
                },
                {
                    "model_name": "text-embedding-v3",
                    "type": "embedding",
                    "provider_code": "aliyun",
                    "model_endpoint": "/embeddings",
                    "describe": "阿里云文本嵌入模型 v3，用于知识库向量化",
                    "version": "text-embedding-v3",
                    "max_tokens": None,
                    "context_window": 8192,
                    "is_active": True,
                    "is_default": True,
                    "priority": 92
                },
                {
                    "model_name": "text-embedding-v2",
                    "type": "embedding",
                    "provider_code": "aliyun",
                    "model_endpoint": "/embeddings",
                    "describe": "阿里云文本嵌入模型 v2，支持 1536 维向量",
                    "version": "text-embedding-v2",
                    "max_tokens": None,
                    "context_window": 2048,
                    "is_active": True,
                    "is_default": False,
                    "priority": 80
                },
                # Anthropic 模型
                {
                    "model_name": "claude-3-opus",
                    "type": "chatllm",
                    "provider_code": "anthropic",
                    "model_endpoint": "/messages",
                    "describe": "Claude 3 Opus 是最强大的 Claude 模型，具有出色的推理能力",
                    "version": "claude-3-opus-20240229",
                    "max_tokens": 4096,
                    "context_window": 200000,
                    "is_active": True,
                    "is_default": True,
                    "priority": 100
                },
                {
                    "model_name": "claude-3-sonnet",
                    "type": "chatllm",
                    "provider_code": "anthropic",
                    "model_endpoint": "/messages",
                    "describe": "Claude 3 Sonnet 是平衡性能和速度的模型",
                    "version": "claude-3-sonnet-20240229",
                    "max_tokens": 4096,
                    "context_window": 200000,
                    "is_active": True,
                    "is_default": False,
                    "priority": 90
                },
                {
                    "model_name": "claude-3-haiku",
                    "type": "chatllm",
                    "provider_code": "anthropic",
                    "model_endpoint": "/messages",
                    "describe": "Claude 3 Haiku 是最快的 Claude 模型，适合实时应用",
                    "version": "claude-3-haiku-20240307",
                    "max_tokens": 4096,
                    "context_window": 200000,
                    "is_active": True,
                    "is_default": False,
                    "priority": 75
                },
                # OpenAI 兼容本地模型
                {
                    "model_name": "qwen2.5-7b-instruct",
                    "type": "chatllm",
                    "provider_code": "local",
                    "model_endpoint": "/chat/completions",
                    "describe": "Qwen2.5 7B 本地部署，需通过 OpenAI 兼容接口提供服务",
                    "version": "qwen2.5-7b-instruct",
                    "max_tokens": 4096,
                    "context_window": 32768,
                    "is_active": True,
                    "is_default": True,
                    "priority": 50
                },
                {
                    "model_name": "llama-3.1-8b-instruct",
                    "type": "chatllm",
                    "provider_code": "local",
                    "model_endpoint": "/chat/completions",
                    "describe": "Llama 3.1 8B 本地部署，需通过 OpenAI 兼容接口提供服务",
                    "version": "llama-3.1-8b-instruct",
                    "max_tokens": 8192,
                    "context_window": 8192,
                    "is_active": True,
                    "is_default": False,
                    "priority": 45
                }
            ]
            
            created_models = []
            for model_data in models_data:
                provider_code = model_data.pop("provider_code")
                provider = created_providers.get(provider_code)
                if not provider:
                    logger.warning(f"⚠️  供应商不存在: {provider_code}，跳过模型 {model_data['model_name']}")
                    continue
                
                # 检查模型是否已存在
                existing = await AsyncDB.get_by_field(db, ModelInfo, "model_name", model_data["model_name"])
                if existing:
                    logger.info(f"✅ 模型已存在: {model_data['model_name']}")
                    created_models.append(existing)
                    continue
                
                model = ModelInfo(
                    model_name=model_data["model_name"],
                    type=model_data["type"],
                    provider_id=provider.id,
                    model_endpoint=model_data.get("model_endpoint"),
                    describe=model_data.get("describe"),
                    version=model_data.get("version"),
                    max_tokens=model_data.get("max_tokens"),
                    context_window=model_data.get("context_window"),
                    is_active=model_data.get("is_active", True),
                    is_default=model_data.get("is_default", False),
                    priority=model_data.get("priority", 0)
                )
                
                model = await AsyncDB.create(db, model)
                created_models.append(model)
                logger.info(f"✅ 创建模型: {model.model_name} (ID: {model.id}, Provider: {provider.name})")
            
            await db.commit()
            
            logger.info("")
            logger.info("=" * 60)
            logger.info("✅ 供应商配置和模型数据初始化完成！")
            logger.info("=" * 60)
            logger.info(f"创建了 {len(created_providers)} 个供应商配置")
            logger.info(f"创建了 {len(created_models)} 个模型")
            logger.info("")
            logger.info("供应商列表：")
            for code, provider in created_providers.items():
                logger.info(f"  - {provider.name} ({code})")
            logger.info("")
            logger.info("模型列表：")
            for model in created_models:
                provider = created_providers.get(model.provider.code if model.provider else None)
                provider_name = provider.name if provider else "Unknown"
                logger.info(f"  - {model.model_name} ({model.type}) - {provider_name}")
            
        except Exception as e:
            await db.rollback()
            logger.error(f"初始化失败: {str(e)}", exc_info=True)
            raise


if __name__ == "__main__":
    asyncio.run(init_providers_and_models())
