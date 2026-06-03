"""
异步 LLM 调用工具
使用异步 HTTP 客户端调用 LLM API
"""
from typing import List, Sequence, Optional, Any
from sqlalchemy.ext.asyncio import AsyncSession
from llama_index.core.llms import ChatMessage, ChatResponse, MessageRole
from openai import AsyncOpenAI
import logging
import asyncio

from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


class AsyncChatGLM:
    """异步聊天模型类"""
    
    def __init__(
        self,
        model: str,
        api_key: Optional[str],
        base_url: Optional[str],
        system_prompt: str,
        top_p: float = 0.8,
        temperature: float = 0.7,
    ):
        self.model = model
        self.api_key = api_key
        self.base_url = base_url
        self.system_prompt = system_prompt
        self.top_p = top_p
        self.temperature = temperature
        self._client: Optional[AsyncOpenAI] = None
    
    def _get_client(self) -> AsyncOpenAI:
        """获取异步客户端"""
        if self._client is None:
            self._client = AsyncOpenAI(
                api_key=self.api_key,
                base_url=self.base_url
            )
        return self._client
    
    async def chat(self, messages: Sequence[ChatMessage], **kwargs: Any) -> ChatResponse:
        """异步聊天功能"""
        try:
            if isinstance(messages, str):
                user_messages = [ChatMessage(
                    content=messages,
                    role=MessageRole.USER
                )]
            else:
                user_messages = list(messages)

            message_dicts = [
                {
                    "role": msg.role.value,
                    "content": msg.content
                }
                for msg in user_messages
            ]
            
            # 异步调用 API
            client = self._get_client()
            response = await client.chat.completions.create(
                model=self.model,
                messages=message_dicts,
                top_p=self.top_p,
                temperature=self.temperature,
                max_tokens=kwargs.pop("max_tokens", 4096),
                **kwargs
            )
            
            # 构建响应
            chat_response = ChatResponse(
                message=ChatMessage(
                    content=response.choices[0].message.content,
                    role=MessageRole(response.choices[0].message.role),
                    additional_kwargs={}
                ),
                raw=response,
                additional_kwargs={
                    "token_counts": response.usage.total_tokens if response.usage else 0,
                    "prompt_tokens": response.usage.prompt_tokens if response.usage else 0,
                    "completion_tokens": response.usage.completion_tokens if response.usage else 0
                }
            )
            
            return chat_response
        except Exception as e:
            logger.error(f"异步 LLM 调用失败: {e}")
            raise


async def get_chatllm_async(model_config_id: int, session: AsyncSession):
    """异步获取聊天模型 (修复MissingGreenlet错误和API key为空的问题)"""
    from app.models.model_config import ModelConfig
    from app.models.model_info import ModelInfo
    from app.utils.async_db import AsyncDB
    from app.utils.error_handler import ValidationError
    from sqlalchemy import select
    from sqlalchemy.orm import joinedload

    # 异步查询模型配置
    model_config = await AsyncDB.get_by_id(session, ModelConfig, model_config_id)
    if not model_config:
        raise ValidationError("模型配置不存在")

    base_model_id = model_config.base_model_id
    # 将 Decimal 类型转换为 float，避免 JSON 序列化错误
    temperature = float(model_config.temperature) if model_config.temperature is not None else 0.7
    top_p = float(model_config.top_p) if model_config.top_p is not None else 0.8
    prompt = model_config.prompt
    
    # 异步查询基础模型信息，并预加载 provider 关系
    stmt = select(ModelInfo).where(ModelInfo.id == base_model_id).options(selectinload(ModelInfo.provider))
    result = await session.execute(stmt)
    base_model_info = result.scalar_one_or_none()
    if not base_model_info:
        raise ValidationError("基础模型信息不存在")

    model_name = base_model_info.model_name

    # 获取base_url和api_key（直接访问预加载的provider，避免懒加载问题）
    # 即使 joinedload 预加载了，也要检查 provider 是否实际可用
    logger.debug(f"Debug: base_model_info.provider = {base_model_info.provider}")
    logger.debug(f"Debug: type(base_model_info.provider) = {type(base_model_info.provider)}")

    if base_model_info.provider and base_model_info.provider.base_url:
        base_url = base_model_info.provider.base_url
        logger.debug(f"Debug: 使用 provider.base_url = {base_url}")
    else:
        base_url = base_model_info.base_url
        logger.debug(f"Debug: 使用 ModelInfo.base_url = {base_url}")

    if base_model_info.provider and base_model_info.provider.api_key:
        api_key = base_model_info.provider.api_key
        logger.debug(f"Debug: 使用 provider.api_key = {'***' + api_key[-4:] if api_key else 'None'}")
    else:
        api_key = base_model_info.api_key
        logger.debug(f"Debug: 使用 ModelInfo.api_key = {'***' + api_key[-4:] if api_key else 'None'}")

    # ⭐ 添加详细的错误检查和日志
    if not base_url:
        logger.error(f"模型 {model_name} (ID: {base_model_id}) 的 base_url 为空")
        logger.error(f"ModelInfo.base_url: {base_model_info.base_url}")
        logger.error(f"Provider: {base_model_info.provider.name if base_model_info.provider else 'None'}")
        logger.error(f"Provider.base_url: {base_model_info.provider.base_url if base_model_info.provider else 'None'}")
        raise ValidationError(f"模型 {model_name} 的 base_url 为空，请检查供应商配置")

    if not api_key:
        logger.error(f"模型 {model_name} (ID: {base_model_id}) 的 api_key 为空")
        logger.error(f"ModelInfo.api_key: {base_model_info.api_key}")
        logger.error(f"Provider: {base_model_info.provider.name if base_model_info.provider else 'None'}")
        logger.error(f"Provider.api_key: {'***' if base_model_info.provider and base_model_info.provider.api_key else 'None'}")
        raise ValidationError(f"模型 {model_name} 的 api_key 为空，请先在供应商配置中填写 API Key")

    logger.info(f"✅ 成功获取模型配置: {model_name}, base_url: {base_url}")

    try:
        chat_model = AsyncChatGLM(
            model=model_name,
            api_key=api_key,
            base_url=base_url,
            system_prompt=prompt or "",
            temperature=float(temperature) if temperature else 0.7,
            top_p=float(top_p) if top_p else 0.8
        )
        return chat_model
    except Exception as e:
        raise Exception(f"聊天模型创建失败: {str(e)}")
