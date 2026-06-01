"""
流式对话服务

基于 SSE (Server-Sent Events) 的流式对话，集成 Agent 引擎和 Trace 追踪。
支持两种模式：
  1. Agent 模式：ReAct 循环 + 工具调用 + 流式输出
  2. 简单流式：直接流式输出 LLM 回答（无工具调用）
"""
import json
import re
from typing import Optional, List, Dict, Any, AsyncGenerator
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession
from llama_index.core.llms import ChatMessage

from app.mappers.chat_mapper import AsyncChatMapper
from app.mappers.model_mapper import AsyncModelMapper
from app.mappers.user_mapper import AsyncUserMapper
from app.mappers.organization_mapper import AsyncOrganizationMapper
from app.utils.async_llm_pool import AsyncLLMPool
from app.services.vector_service import AsyncVectorService
from app.services.chat_service import AsyncChatService
from app.services.agent.engine import AgentEngine, SimpleStreamEngine, AgentEvent
from app.services.agent.tools import get_default_tools
from app.services.agent.memory import ConversationMemory, count_tokens
from app.utils.logger_config import get_logger

logger = get_logger(__name__)


def _sse_event(event_type: str, data: Any) -> str:
    """格式化 SSE 事件"""
    json_data = json.dumps(data, ensure_ascii=False, default=str)
    return f"event: {event_type}\ndata: {json_data}\n\n"


class StreamChatService:
    """流式对话服务"""

    @staticmethod
    async def chat_stream(
        session: AsyncSession,
        user_id: int,
        conversation_id: Optional[int],
        model_config_id: Optional[int],
        message: str,
        use_agent: bool = True,
        files: Optional[List[Any]] = None,
        vector_db_ids: Optional[List[int]] = None,
        quoted_content: Optional[str] = None,
        quoted_role: Optional[str] = None,
    ) -> AsyncGenerator[str, None]:
        """流式对话，返回 SSE 事件流"""

        try:
            # 1. 准备会话
            if not conversation_id:
                if not model_config_id:
                    model_config_id = await AsyncChatService.resolve_default_model_config_id(session, user_id)
                if not model_config_id:
                    yield _sse_event("error", {"message": "当前没有可用的模型配置"})
                    return
                await AsyncLLMPool.get_client(model_config_id, session)
                conversation_id = await AsyncChatService.create_conversation(session, user_id, model_config_id, message)

            if not conversation_id:
                yield _sse_event("error", {"message": "对话创建失败"})
                return

            await AsyncChatService._assert_conversation_owner(session, conversation_id, user_id)

            # 发送会话信息
            conversation = await AsyncChatMapper.get_conversation(session, conversation_id)
            if not conversation:
                yield _sse_event("error", {"message": "对话不存在"})
                return

            conversation_info = conversation['conversation_info']
            model_config_id = conversation_info['model_config_id']

            yield _sse_event("conversation", {
                "conversation_id": conversation_id,
                "conversation_name": conversation_info['name'],
            })

            # 2. 处理附件
            attachment_info = await AsyncVectorService.upload_conversation_attachments(
                session, user_id=user_id, conversation_id=conversation_id,
                model_config_id=model_config_id, files=files,
            )
            attachment_vector_db_ids = (
                [attachment_info["vector_db_id"]]
                if attachment_info.get("vector_db_id") and attachment_info.get("document_ids")
                else []
            )

            message_for_history = message
            if attachment_info.get("filenames"):
                attachment_names = "、".join(attachment_info["filenames"])
                message_for_history = f"{message}\n\n[已上传附件：{attachment_names}]"

            # 3. 保存用户消息
            user_metadata = None
            if quoted_content:
                user_metadata = {"quote": {"content": quoted_content, "role": quoted_role or "assistant"}}
            await AsyncChatMapper.save_message(session, conversation_id, "user", message_for_history, metadata=user_metadata)

            # 4. 加载历史
            conversation = await AsyncChatMapper.get_conversation(session, conversation_id)
            history = conversation['history']["messages"]

            # 5. 记忆管理 — token 压缩
            memory = ConversationMemory(max_tokens=3500)
            history_dicts = [{"role": msg['role'], "content": msg['content']} for msg in reversed(history)]
            model = await AsyncLLMPool.get_client(model_config_id, session)
            compressed = await memory.compress(history_dicts, model)
            token_stats = memory.get_token_stats(compressed)
            yield _sse_event("memory", token_stats)

            # 6. 构建 prompt 和 RAG
            model_config = await AsyncModelMapper.get_model_config_by_id(session, model_config_id)
            all_extra_ids = (vector_db_ids or []) + attachment_vector_db_ids

            if use_agent:
                # === Agent 模式 ===
                tools = get_default_tools(session, model_config_id, user_id, all_extra_ids if all_extra_ids else None)
                engine = AgentEngine(tools=tools, max_iterations=5)

                # 构建系统消息
                system_msgs = []
                if model_config and model_config.prompt:
                    variables = {
                        "user_question": message,
                        "current_date": datetime.now().strftime("%Y-%m-%d"),
                    }
                    variables.update(AsyncChatService._parse_prompt_variables(
                        getattr(model_config, "prompt_variables", None)
                    ))
                    rendered = AsyncChatService._render_template(model_config.prompt, variables).strip()
                    if rendered:
                        system_msgs.append({"role": "system", "content": rendered})

                system_msgs.append({"role": "system", "content": (
                    "你是一个智能助手，可以使用多种工具来回答用户问题。"
                    "当需要查找信息时使用 knowledge_search 工具，"
                    "需要计算时使用 calculator 工具，"
                    "需要时间信息时使用 datetime_info 工具。"
                    "如果不需要工具就能直接回答，请直接回答。"
                    "回答中引用知识库内容时，请标注 [来源N]。"
                )})

                # 运行 Agent
                accumulated_content = ""
                rag_result = None
                trace_data = None

                async for event in engine.run(compressed, model, system_msgs):
                    yield _sse_event(event.type, event.data)

                    if event.type == "done":
                        accumulated_content = event.data.get("content", "")
                        rag_result = event.data.get("rag_result")
                    elif event.type == "trace":
                        trace_data = event.data

            else:
                # === 简单流式模式 ===
                rag_result = {
                    "contexts": [], "sources": [], "used_knowledge_base": False,
                    "vector_db_id": None, "vector_db_ids": [], "queried_vector_db_ids": [],
                    "retrieval_layers": [], "total_results": 0, "avg_similarity": 0.0,
                    "fallback_used": False,
                }

                if model_config:
                    rag_result = await AsyncVectorService.query_vector_by_model(
                        session, model_config_id, message,
                        user_id=user_id,
                        extra_vector_db_ids=all_extra_ids if all_extra_ids else None,
                    )

                prompt_messages = []
                enriched_sources = []
                if model_config:
                    prompt_messages, enriched_sources, _ = AsyncChatService._build_prompt_orchestration(
                        model_config, message, rag_result,
                    )
                    if enriched_sources:
                        rag_result["sources"] = enriched_sources

                system_msgs = [{"role": m.role if isinstance(m.role, str) else m.role.value, "content": m.content} for m in prompt_messages]
                engine = SimpleStreamEngine()

                accumulated_content = ""
                trace_data = None

                async for event in engine.run(system_msgs + compressed, model):
                    yield _sse_event(event.type, event.data)
                    if event.type == "done":
                        accumulated_content = event.data.get("content", "")
                    elif event.type == "trace":
                        trace_data = event.data

            # 7. 后处理和保存
            content = accumulated_content

            raw_sources = (rag_result or {}).get("sources", [])
            source_citations = [
                {
                    "content": s.get("content", ""),
                    "source": s.get("source", ""),
                    "chunk_id": s.get("id", ""),
                    "similarity": round(s.get("similarity", 0.0), 4),
                    "vector_score": round(s.get("vector_score", 0.0), 4),
                    "bm25_score": round(s.get("bm25_score", 0.0), 4),
                    "final_score": round(s.get("final_score", 0.0), 4),
                    "retrieval_method": s.get("retrieval_method", "vector"),
                    "document_id": s.get("document_id", ""),
                    "vector_db_id": s.get("vector_db_id"),
                    "vector_db_name": s.get("vector_db_name", ""),
                    "citation_label": s.get("citation_label", ""),
                    "confidence_score": round(s.get("confidence_score", 0.0), 4),
                    "confidence_label": s.get("confidence_label", ""),
                }
                for s in raw_sources
            ]

            ct = getattr(model_config, "citation_template", None) if model_config else None
            content, source_citations = AsyncChatService._renumber_citations(content, source_citations, ct)

            used_kb = (rag_result or {}).get("used_knowledge_base", False)
            grounded_ratio = max(0.0, min(1.0, (rag_result or {}).get("avg_similarity", 0.0))) if used_kb else 0.0
            grounded_level = AsyncChatService._grounding_summary(grounded_ratio)

            # 保存到数据库
            assistant_metadata = {}
            if source_citations:
                assistant_metadata["sources"] = source_citations
            if grounded_ratio:
                assistant_metadata["grounded_ratio"] = round(grounded_ratio, 4)
                assistant_metadata["grounded_level"] = grounded_level
            if used_kb:
                assistant_metadata["rag_info"] = {
                    "used_knowledge_base": True,
                    "vector_db_ids": (rag_result or {}).get("vector_db_ids", []),
                    "total_results": (rag_result or {}).get("total_results", 0),
                    "avg_similarity": (rag_result or {}).get("avg_similarity", 0),
                }
            if trace_data:
                assistant_metadata["trace"] = trace_data
            if attachment_info and attachment_info.get("document_ids"):
                assistant_metadata["attachment_info"] = attachment_info

            await AsyncChatMapper.save_message(
                session, conversation_id, "assistant", content,
                metadata=assistant_metadata if assistant_metadata else None,
            )

            # 发送最终元数据
            yield _sse_event("sources", source_citations)
            yield _sse_event("metadata", {
                "grounded_ratio": round(grounded_ratio, 4),
                "grounded_level": grounded_level,
                "conversation_id": conversation_id,
                "conversation_name": conversation_info['name'],
                "used_knowledge_base": used_kb,
            })

        except Exception as e:
            logger.error(f"流式对话失败: {e}", exc_info=True)
            yield _sse_event("error", {"message": f"对话处理失败: {str(e)}"})

    @staticmethod
    async def bot_chat_stream(
        db: AsyncSession,
        user: Any,
        message: str,
        conversation_id: Optional[str],
        system_prompt: str,
        vector_db_ids: List[int],
        model_config_id: Optional[int],
        use_agent: bool = True,
    ) -> AsyncGenerator[str, None]:
        """Bot 流式对话"""
        try:
            if not model_config_id:
                yield _sse_event("error", {"message": "Bot 未关联模型配置"})
                return

            conv_id_int: Optional[int] = None
            if conversation_id:
                try:
                    conv_id_int = int(conversation_id)
                    await AsyncChatService._assert_conversation_owner(db, conv_id_int, user.id)
                except (ValueError, Exception):
                    conv_id_int = None

            if not conv_id_int:
                conv_id_int = await AsyncChatService.create_conversation(db, user.id, model_config_id, message)

            yield _sse_event("conversation", {"conversation_id": str(conv_id_int)})

            await AsyncChatMapper.save_message(db, conv_id_int, "user", message)

            conversation = await AsyncChatMapper.get_conversation(db, conv_id_int)
            history_messages = conversation["history"]["messages"] if conversation else []

            model_config = await AsyncModelMapper.get_model_config_by_id(db, model_config_id)
            model = await AsyncLLMPool.get_client(model_config_id, db)

            # 记忆管理
            memory = ConversationMemory(max_tokens=3500)
            history_dicts = [{"role": msg['role'], "content": msg['content']} for msg in reversed(history_messages)]
            compressed = await memory.compress(history_dicts, model)
            yield _sse_event("memory", memory.get_token_stats(compressed))

            if use_agent:
                # Agent 模式
                tools = get_default_tools(db, model_config_id, user.id, vector_db_ids if vector_db_ids else None)
                engine = AgentEngine(tools=tools, max_iterations=5)

                system_msgs = []
                if system_prompt:
                    system_msgs.append({"role": "system", "content": system_prompt})
                system_msgs.append({"role": "system", "content": (
                    "你是一个智能助手，可以使用工具来辅助回答。"
                    "需要查找资料时使用 knowledge_search 工具。"
                    "引用知识库内容时标注 [来源N]。"
                )})

                accumulated_content = ""
                rag_result = None
                trace_data = None

                async for event in engine.run(compressed, model, system_msgs):
                    yield _sse_event(event.type, event.data)
                    if event.type == "done":
                        accumulated_content = event.data.get("content", "")
                        rag_result = event.data.get("rag_result")
                    elif event.type == "trace":
                        trace_data = event.data
            else:
                # 简单流式
                rag_result = {"sources": [], "used_knowledge_base": False, "avg_similarity": 0.0}
                if vector_db_ids:
                    rag_result = await AsyncVectorService.query_vector_by_model(
                        db, model_config_id, message, user_id=user.id,
                        extra_vector_db_ids=vector_db_ids,
                    )
                elif model_config:
                    rag_result = await AsyncVectorService.query_vector_by_model(
                        db, model_config_id, message, user_id=user.id,
                    )

                prompt_messages = []
                if model_config:
                    prompt_messages, enriched, _ = AsyncChatService._build_prompt_orchestration(
                        model_config, message, rag_result,
                    )
                    if enriched:
                        rag_result["sources"] = enriched

                system_msgs_list = []
                if system_prompt:
                    system_msgs_list.append({"role": "system", "content": system_prompt})
                system_msgs_list.extend(
                    [{"role": m.role if isinstance(m.role, str) else m.role.value, "content": m.content} for m in prompt_messages]
                )

                engine = SimpleStreamEngine()
                accumulated_content = ""
                trace_data = None

                async for event in engine.run(system_msgs_list + compressed, model):
                    yield _sse_event(event.type, event.data)
                    if event.type == "done":
                        accumulated_content = event.data.get("content", "")
                    elif event.type == "trace":
                        trace_data = event.data

            # 后处理
            content = accumulated_content
            raw_sources = (rag_result or {}).get("sources", [])
            source_citations = [
                {
                    "content": s.get("content", ""),
                    "source": s.get("source", ""),
                    "chunk_id": s.get("id", ""),
                    "similarity": round(s.get("similarity", 0.0), 4),
                    "vector_score": round(s.get("vector_score", 0.0), 4),
                    "bm25_score": round(s.get("bm25_score", 0.0), 4),
                    "final_score": round(s.get("final_score", 0.0), 4),
                    "retrieval_method": s.get("retrieval_method", "vector"),
                    "document_id": s.get("document_id", ""),
                    "vector_db_id": s.get("vector_db_id"),
                    "vector_db_name": s.get("vector_db_name", ""),
                    "citation_label": s.get("citation_label", ""),
                    "confidence_score": round(s.get("confidence_score", 0.0), 4),
                    "confidence_label": s.get("confidence_label", ""),
                }
                for s in raw_sources
            ]

            ct = getattr(model_config, "citation_template", None) if model_config else None
            content, source_citations = AsyncChatService._renumber_citations(content, source_citations, ct)

            used_kb = (rag_result or {}).get("used_knowledge_base", False)
            grounded_ratio = max(0.0, min(1.0, (rag_result or {}).get("avg_similarity", 0.0))) if used_kb else 0.0
            grounded_level = AsyncChatService._grounding_summary(grounded_ratio)

            bot_metadata = {}
            if source_citations:
                bot_metadata["sources"] = source_citations
            if grounded_ratio:
                bot_metadata["grounded_ratio"] = round(grounded_ratio, 4)
                bot_metadata["grounded_level"] = grounded_level
            if trace_data:
                bot_metadata["trace"] = trace_data

            await AsyncChatMapper.save_message(
                db, conv_id_int, "assistant", content,
                metadata=bot_metadata if bot_metadata else None,
            )

            model_name = None
            if model_config:
                await db.refresh(model_config, ["base_model"])
                if model_config.base_model:
                    model_name = model_config.base_model.model_name

            yield _sse_event("sources", source_citations)
            yield _sse_event("metadata", {
                "grounded_ratio": round(grounded_ratio, 4),
                "grounded_level": grounded_level,
                "conversation_id": str(conv_id_int),
                "model_name": model_name,
                "used_knowledge_base": used_kb,
            })

        except Exception as e:
            logger.error(f"Bot 流式对话失败: {e}", exc_info=True)
            yield _sse_event("error", {"message": f"对话处理失败: {str(e)}"})
