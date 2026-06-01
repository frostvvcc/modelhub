"""
异步对话 Service
"""
from typing import Optional, List, Dict, Any
import json
import re
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession
from llama_index.core.llms import ChatMessage
from app.mappers.chat_mapper import AsyncChatMapper
from app.mappers.model_mapper import AsyncModelMapper
from app.mappers.organization_mapper import AsyncOrganizationMapper
from app.mappers.user_mapper import AsyncUserMapper
from app.utils.async_llm_pool import AsyncLLMPool
from app.services.vector_service import AsyncVectorService
from app.utils.logger_config import get_logger
from app.utils.error_handler import (
    ValidationError,
    NotFoundError,
    InternalServerError,
    UnauthorizedError,
    ForbiddenError
)

logger = get_logger(__name__)


class AsyncChatService:
    """异步对话服务类"""

    DEFAULT_CONTEXT_TEMPLATE = (
        "【知识库上下文】\n"
        "{context_blocks}\n\n"
        "请严格依据以上上下文回答。引用事实时在句末标注对应来源编号，例如 [来源1]。"
    )
    DEFAULT_REFUSAL_STRATEGY = (
        "如果知识库资料不足以回答，请明确说明“当前知识库依据不足”，"
        "不要编造具体政策、日期、流程或数字。"
    )

    @staticmethod
    async def _assert_conversation_owner(
        session: AsyncSession,
        conversation_id: int,
        user_id: Optional[int],
    ) -> dict:
        """确认会话属于当前用户，防止越权读取或修改。"""
        conversation_info = await AsyncChatMapper.get_conversation_info(session, conversation_id)
        if user_id is not None and conversation_info.get("user_id") != user_id:
            raise ForbiddenError("无权访问该对话")
        return conversation_info

    @staticmethod
    def _render_template(template: Optional[str], variables: Dict[str, Any]) -> str:
        """渲染轻量模板，兼容 {name} 和 {{name}} 两种写法。"""
        if not template:
            return ""
        rendered = template
        for key, value in variables.items():
            value_text = "" if value is None else str(value)
            rendered = rendered.replace("{{" + key + "}}", value_text)
            rendered = rendered.replace("{" + key + "}", value_text)
        return rendered

    @staticmethod
    def _parse_prompt_variables(raw_variables: Optional[str]) -> Dict[str, Any]:
        if not raw_variables:
            return {}
        try:
            data = json.loads(raw_variables)
            return data if isinstance(data, dict) else {}
        except Exception:
            logger.warning("Prompt 变量不是合法 JSON，已忽略")
            return {}

    @staticmethod
    def _make_citation_label(template: Optional[str], index: int) -> str:
        template = template or "[来源{index}]"
        return AsyncChatService._render_template(template, {"index": index})

    @staticmethod
    def _confidence_from_source(source: Dict[str, Any]) -> tuple[float, str]:
        similarity = float(source.get("similarity") or source.get("vector_score") or 0.0)
        score = max(0.0, min(1.0, similarity))
        if score >= 0.75:
            label = "高"
        elif score >= 0.55:
            label = "中"
        elif score > 0:
            label = "低"
        else:
            label = "不足"
        return score, label

    @staticmethod
    def _build_context_blocks(
        raw_sources: List[Dict[str, Any]],
        citation_template: Optional[str],
        max_context_chars: Optional[int],
    ) -> tuple[str, List[Dict[str, Any]], List[str]]:
        """把检索结果编排成带来源编号的上下文块，并按字符预算截断。"""
        budget = max(1000, min(int(max_context_chars or 6000), 30000))
        blocks: List[str] = []
        enriched_sources: List[Dict[str, Any]] = []
        labels: List[str] = []
        used_chars = 0
        label_counter = 0

        for source in raw_sources:
            confidence_score, confidence_label = AsyncChatService._confidence_from_source(source)
            content = (source.get("content") or "").strip()
            if not content:
                continue
            label_counter += 1
            label = AsyncChatService._make_citation_label(citation_template, label_counter)

            header = (
                f"{label} 文件：{source.get('source') or '未知'}；"
                f"知识库：{source.get('vector_db_name') or source.get('vector_db_id') or '未知'}；"
                f"检索方式：{source.get('retrieval_method') or 'vector'}；"
                f"依据充分程度：{confidence_label}"
            )
            available = budget - used_chars - len(header) - 2
            if available <= 80:
                break
            trimmed_content = content[:available].rstrip()
            block = f"{header}\n{trimmed_content}"
            blocks.append(block)
            used_chars += len(block) + 2
            labels.append(label)
            enriched = dict(source)
            enriched["citation_label"] = label
            enriched["confidence_score"] = round(confidence_score, 4)
            enriched["confidence_label"] = confidence_label
            enriched_sources.append(enriched)

        return "\n\n".join(blocks), enriched_sources, labels

    @staticmethod
    def _grounding_summary(grounded_ratio: float) -> str:
        if grounded_ratio >= 0.75:
            return "高"
        if grounded_ratio >= 0.55:
            return "中"
        if grounded_ratio > 0:
            return "低"
        return "不足"

    @staticmethod
    def _renumber_citations(
        content: str,
        enriched_sources: List[Dict[str, Any]],
        citation_template: Optional[str],
    ) -> tuple[str, List[Dict[str, Any]]]:
        """LLM 回复后处理：把实际引用的来源从 1 开始连续编号。"""
        cited_indices = sorted(set(int(m) for m in re.findall(r'\[来源(\d+)\]', content)))
        if not cited_indices:
            return content, enriched_sources

        if cited_indices == list(range(1, len(cited_indices) + 1)):
            return content, enriched_sources

        old_to_new = {old: new for new, old in enumerate(cited_indices, start=1)}

        # 第一遍：旧标签 → 占位符（避免替换冲突）
        for old_idx in cited_indices:
            old_label = AsyncChatService._make_citation_label(citation_template, old_idx)
            content = content.replace(old_label, f"__CITE_{old_to_new[old_idx]}__")
        # 第二遍：占位符 → 新标签
        for new_idx in range(1, len(cited_indices) + 1):
            new_label = AsyncChatService._make_citation_label(citation_template, new_idx)
            content = content.replace(f"__CITE_{new_idx}__", new_label)

        # 按引用顺序重排 sources
        source_by_old_idx: Dict[int, Dict[str, Any]] = {}
        for src in enriched_sources:
            m = re.search(r'(\d+)', src.get("citation_label", ""))
            if m:
                source_by_old_idx[int(m.group(1))] = src

        new_sources: List[Dict[str, Any]] = []
        for old_idx in cited_indices:
            src = source_by_old_idx.pop(old_idx, None)
            if src:
                new_src = dict(src)
                new_src["citation_label"] = AsyncChatService._make_citation_label(
                    citation_template, old_to_new[old_idx]
                )
                new_sources.append(new_src)
        # 未被引用的来源追加到末尾，继续编号
        for remaining_src in source_by_old_idx.values():
            counter = len(new_sources) + 1
            new_src = dict(remaining_src)
            new_src["citation_label"] = AsyncChatService._make_citation_label(citation_template, counter)
            new_sources.append(new_src)

        return content, new_sources

    @staticmethod
    def _build_prompt_orchestration(
        model_config: Any,
        message: str,
        rag_result: Dict[str, Any],
    ) -> tuple[List[ChatMessage], List[Dict[str, Any]], List[str]]:
        raw_sources = rag_result.get("sources", [])
        context_blocks, enriched_sources, citation_labels = AsyncChatService._build_context_blocks(
            raw_sources,
            getattr(model_config, "citation_template", None),
            getattr(model_config, "max_context_chars", 6000),
        )
        variables = {
            "user_question": message,
            "current_date": datetime.now().strftime("%Y-%m-%d"),
            "source_count": len(enriched_sources),
            "citation_labels": " ".join(citation_labels),
            "context_blocks": context_blocks,
        }
        variables.update(
            AsyncChatService._parse_prompt_variables(
                getattr(model_config, "prompt_variables", None)
            )
        )

        messages: List[ChatMessage] = []
        rendered_prompt = AsyncChatService._render_template(
            getattr(model_config, "prompt", None),
            variables,
        ).strip()
        if rendered_prompt:
            messages.append(ChatMessage(role="system", content=f"【Prompt 模板】\n{rendered_prompt}"))

        if context_blocks:
            context_template = (
                getattr(model_config, "knowledge_context_template", None)
                or AsyncChatService.DEFAULT_CONTEXT_TEMPLATE
            )
            messages.append(ChatMessage(
                role="system",
                content=AsyncChatService._render_template(context_template, variables),
            ))

        refusal = (
            getattr(model_config, "refusal_strategy", None)
            or AsyncChatService.DEFAULT_REFUSAL_STRATEGY
        )
        messages.append(ChatMessage(role="system", content=f"【禁止回答策略】\n{refusal}"))
        return messages, enriched_sources, citation_labels

    @staticmethod
    async def resolve_default_model_config_id(
        session: AsyncSession,
        user_id: int
    ) -> Optional[int]:
        """为普通聊天入口选择一个当前用户可见的默认模型配置。"""
        user = await AsyncUserMapper.get_user_by_id(session, user_id)
        if not user:
            return None

        user_orgs = await AsyncOrganizationMapper.get_user_organizations(session, user_id)
        organization_id = user_orgs[0].id if user_orgs else None
        school_id = user.school_id or (user_orgs[0].school_id if user_orgs else None)

        configs = await AsyncModelMapper.get_model_config_by_user_id(
            session,
            user_id,
            school_id=school_id,
            organization_id=organization_id
        )
        if not configs:
            configs = await AsyncModelMapper.get_all_public_model_config(
                session,
                school_id=school_id,
                organization_id=organization_id
            )

        return configs[0].id if configs else None
    
    @staticmethod
    async def create_conversation(
        session: AsyncSession,
        user_id: int,
        model_config_id: Optional[int],
        message: str,
        organization_id: Optional[int] = None
    ) -> int:
        """
        创建对话（支持组织关联）
        
        Raises:
            ValidationError: 模型配置不存在
            InternalServerError: 创建失败
        """
        logger.info(f"创建对话: user_id={user_id}, model_config_id={model_config_id}, org_id={organization_id}")
        try:
            name = message[:10] if len(message) > 10 else message
            if not model_config_id:
                logger.warning(f"创建对话失败: 模型配置不存在 - user_id={user_id}")
                raise ValidationError("当前没有可用的模型配置，请先在“模型配置”中创建配置")
            
            # 如果未指定组织，从用户信息获取
            if not organization_id:
                user = await AsyncUserMapper.get_user_by_id(session, user_id)
                if user and user.school_id:
                    # 默认使用用户的学校
                    organization_id = user.school_id
            
            # 获取学校ID
            school_id = None
            if organization_id:
                org = await AsyncOrganizationMapper.get_organization_by_id(session, organization_id)
                if org:
                    school_id = org.school_id or (org.id if org.type == "school" else None)
            
            conversation_id = await AsyncChatMapper.create_conversation(
                session, user_id, name, model_config_id,
                organization_id=organization_id, school_id=school_id
            )
            logger.info(f"成功创建对话: conversation_id={conversation_id}")
            return conversation_id
        except ValidationError:
            raise
        except Exception as e:
            logger.error(f"创建对话失败: {str(e)}", exc_info=True)
            raise InternalServerError(f"创建对话失败: {str(e)}")
    
    @staticmethod
    def extract_response_content(response: any) -> str:
        """从不同格式的响应中提取内容"""
        if hasattr(response, 'message') and hasattr(response.message, 'content'):
            return response.message.content
        
        if isinstance(response, str):
            for prefix in ["assistant: ", "Assistant: ", "AI: "]:
                if response.startswith(prefix):
                    return response[len(prefix):]
            return response
        
        if isinstance(response, dict):
            return response.get('content', response.get('response', str(response)))
        
        return str(response)
    
    @staticmethod
    async def chat(
        session: AsyncSession,
        user_id: int,
        conversation_id: Optional[int],
        model_config_id: Optional[int],
        message: str,
        files: Optional[List[Any]] = None,
        vector_db_ids: Optional[List[int]] = None,
        quoted_content: Optional[str] = None,
        quoted_role: Optional[str] = None,
    ) -> dict:
        """
        获取回答并保存
        
        Raises:
            ValidationError: 模型配置不存在或对话创建失败
            NotFoundError: 对话不存在
            InternalServerError: 处理失败
        """
        logger.info(f"处理聊天请求: user_id={user_id}, conversation_id={conversation_id}")
        try:
            if not conversation_id:
                if not model_config_id:
                    model_config_id = await AsyncChatService.resolve_default_model_config_id(
                        session,
                        user_id
                    )
                if not model_config_id:
                    logger.warning(f"聊天失败: 没有可用模型配置 - user_id={user_id}")
                    raise ValidationError("当前没有可用的模型配置，请先在“模型配置”中创建配置")
                # 先校验 LLM 配置，避免 API Key 缺失时创建失败会话。
                await AsyncLLMPool.get_client(model_config_id, session)
                conversation_id = await AsyncChatService.create_conversation(
                    session, user_id, model_config_id, message
                )
            
            if not conversation_id:
                logger.error(f"聊天失败: 对话创建失败 - user_id={user_id}")
                raise ValidationError("对话创建失败")

            await AsyncChatService._assert_conversation_owner(session, conversation_id, user_id)

            # 获取对话信息
            conversation = await AsyncChatMapper.get_conversation(session, conversation_id)
            if not conversation:
                logger.warning(f"聊天失败: 对话不存在 - conversation_id={conversation_id}")
                raise NotFoundError("对话不存在")
            
            conversation_info = conversation['conversation_info']
            model_config_id = conversation_info['model_config_id']
            model = await AsyncLLMPool.get_client(model_config_id, session)

            attachment_info = await AsyncVectorService.upload_conversation_attachments(
                session,
                user_id=user_id,
                conversation_id=conversation_id,
                model_config_id=model_config_id,
                files=files,
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

            # 保存用户消息
            user_metadata = None
            if quoted_content:
                user_metadata = {"quote": {"content": quoted_content, "role": quoted_role or "assistant"}}
            await AsyncChatMapper.save_message(session, conversation_id, "user", message_for_history, metadata=user_metadata)

            conversation = await AsyncChatMapper.get_conversation(session, conversation_id)
            if not conversation:
                logger.warning(f"聊天失败: 对话不存在 - conversation_id={conversation_id}")
                raise NotFoundError("对话不存在")

            conversation_info = conversation['conversation_info']
            history = conversation['history']["messages"]
            
            # 构建消息列表
            chat_messages_list = []
            for msg in reversed(history):
                chat_messages_list.append(ChatMessage(role=msg['role'], content=msg['content']))

            if quoted_content and chat_messages_list:
                last_msg = chat_messages_list[-1]
                if last_msg.role == "user":
                    chat_messages_list[-1] = ChatMessage(
                        role="user",
                        content=f"[用户引用了之前的对话内容: \"{quoted_content[:500]}\"]\n\n{last_msg.content}",
                    )
            
            # 查询上下文（向量数据库）- 异步（带权限检查）
            # 获取模型配置以检查向量数据库权限
            model_config = await AsyncModelMapper.get_model_config_by_id(session, model_config_id)
            rag_result = {
                "contexts": [],
                "sources": [],
                "used_knowledge_base": False,
                "vector_db_id": None,
                "vector_db_ids": [],
                "queried_vector_db_ids": [],
                "retrieval_layers": [],
                "total_results": 0,
                "avg_similarity": 0.0,
                "fallback_used": False,
            }

            all_extra_ids = (vector_db_ids or []) + attachment_vector_db_ids
            if model_config:
                rag_result = await AsyncVectorService.query_vector_by_model(
                    session,
                    model_config_id,
                    message,
                    user_id=user_id,
                    extra_vector_db_ids=all_extra_ids if all_extra_ids else None,
                )

            prompt_messages: List[ChatMessage] = []
            enriched_sources: List[Dict[str, Any]] = []
            citation_labels: List[str] = []
            if model_config:
                prompt_messages, enriched_sources, citation_labels = AsyncChatService._build_prompt_orchestration(
                    model_config,
                    message,
                    rag_result,
                )
                if enriched_sources:
                    rag_result["sources"] = enriched_sources
                    rag_result["contexts"] = [source["content"] for source in enriched_sources]

            # 构建提示词（根据是否使用知识库）
            if rag_result["used_knowledge_base"]:
                chat_messages_list = prompt_messages + chat_messages_list
                logger.info(
                    "✅ [RAG] 使用知识库生成答案: vector_db_ids=%s, layers=%s, 片段数=%s",
                    rag_result.get("vector_db_ids") or [rag_result.get("vector_db_id")],
                    rag_result.get("retrieval_layers", []),
                    rag_result["total_results"],
                )
            else:
                # 未使用知识库：提示LLM说明情况
                no_kb_prompt = (
                    prompt_messages
                    or [ChatMessage(role="system", content="【通用回答】\n\n知识库中未找到与用户问题相关的信息。回答时请明确说明这不是基于知识库的内容。")]
                )
                chat_messages_list = no_kb_prompt + chat_messages_list
                logger.info(f"ℹ️  [RAG] 未使用知识库，使用通用知识回答")

            # 异步调用 LLM
            response = await model.chat(chat_messages_list)

            # 提取内容
            content = AsyncChatService.extract_response_content(response)

            # 根据是否使用知识库，在答案前添加标注
            if rag_result["used_knowledge_base"]:
                grounded_level = AsyncChatService._grounding_summary(rag_result["avg_similarity"])
                source_prefix = f"【平均匹配度 {rag_result['avg_similarity']:.2%}】\n\n"
                content = source_prefix + content
                logger.info(f"✅ [RAG] 答案已添加知识库来源标注")

            # 幻觉溯源：构建 source_citations 列表（在保存前构建，以便一起持久化）
            raw_sources = rag_result.get("sources", [])
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
                    "retrieval_layer": s.get("retrieval_layer", ""),
                    "citation_label": s.get("citation_label", ""),
                    "confidence_score": round(s.get("confidence_score", 0.0), 4),
                    "confidence_label": s.get("confidence_label", ""),
                }
                for s in raw_sources
            ]
            # 后处理：重新编号，确保引用从 [来源1] 开始连续
            ct = getattr(model_config, "citation_template", None) if model_config else None
            content, source_citations = AsyncChatService._renumber_citations(content, source_citations, ct)

            grounded_ratio = max(0.0, min(1.0, rag_result["avg_similarity"])) if rag_result["used_knowledge_base"] else 0.0
            grounded_level = AsyncChatService._grounding_summary(grounded_ratio)

            # 保存助手回复（含富数据）
            assistant_metadata = {}
            if source_citations:
                assistant_metadata["sources"] = source_citations
            if grounded_ratio:
                assistant_metadata["grounded_ratio"] = round(grounded_ratio, 4)
                assistant_metadata["grounded_level"] = grounded_level
            if rag_result["used_knowledge_base"]:
                assistant_metadata["rag_info"] = {
                    "used_knowledge_base": True,
                    "vector_db_id": rag_result["vector_db_id"],
                    "vector_db_ids": rag_result.get("vector_db_ids", []),
                    "queried_vector_db_ids": rag_result.get("queried_vector_db_ids", []),
                    "retrieval_layers": rag_result.get("retrieval_layers", []),
                    "fallback_used": rag_result.get("fallback_used", False),
                    "total_results": rag_result["total_results"],
                    "avg_similarity": rag_result["avg_similarity"],
                    "grounded_level": grounded_level,
                }
            if attachment_info and attachment_info.get("document_ids"):
                assistant_metadata["attachment_info"] = attachment_info

            res = await AsyncChatMapper.save_message(
                session, conversation_id, "assistant", content,
                metadata=assistant_metadata if assistant_metadata else None,
            )

            logger.info(f"成功处理聊天请求: conversation_id={conversation_id}")
            return {
                "response": res,
                "conversation_id": conversation_id,
                "conversation_name": conversation_info['name'],
                "rag_info": {
                    "used_knowledge_base": rag_result["used_knowledge_base"],
                    "vector_db_id": rag_result["vector_db_id"],
                    "vector_db_ids": rag_result.get("vector_db_ids", []),
                    "queried_vector_db_ids": rag_result.get("queried_vector_db_ids", []),
                    "retrieval_layers": rag_result.get("retrieval_layers", []),
                    "fallback_used": rag_result.get("fallback_used", False),
                    "total_results": rag_result["total_results"],
                    "avg_similarity": rag_result["avg_similarity"],
                    "grounded_level": grounded_level,
                },
                "attachment_info": attachment_info,
                "sources": source_citations,
                "grounded_ratio": round(grounded_ratio, 4),
                "grounded_level": grounded_level,
            }
        except (ValidationError, NotFoundError, ForbiddenError):
            raise
        except Exception as e:
            logger.error(f"处理聊天请求失败: {str(e)}", exc_info=True)
            raise InternalServerError(f"处理聊天请求失败: {str(e)}")
    
    @staticmethod
    async def rechat(session: AsyncSession, conversation_id: int, user_id: Optional[int] = None) -> dict:
        """
        重新回答
        
        Raises:
            NotFoundError: 对话不存在
            InternalServerError: 处理失败
        """
        logger.info(f"重新回答: conversation_id={conversation_id}")
        try:
            await AsyncChatService._assert_conversation_owner(session, conversation_id, user_id)
            conversation = await AsyncChatMapper.get_conversation(session, conversation_id)
            if not conversation:
                logger.warning(f"重新回答失败: 对话不存在 - conversation_id={conversation_id}")
                raise NotFoundError("对话不存在")
            
            conversation_info = conversation['conversation_info']
            model_config_id = conversation_info['model_config_id']
            history = conversation['history']["messages"]

            last_user_message = next(
                (msg["content"] for msg in history if msg.get("role") == "user"),
                None,
            )
            if not last_user_message:
                raise ValidationError("该对话没有可重新回答的用户消息")

            # 去掉最近一次助手回复，基于同一个用户问题重新生成。
            history_for_regeneration = list(history)
            if history_for_regeneration and history_for_regeneration[0].get("role") == "assistant":
                history_for_regeneration = history_for_regeneration[1:]

            chat_messages_list = []
            for msg in reversed(history_for_regeneration):
                chat_messages_list.append(ChatMessage(role=msg['role'], content=msg['content']))

            model_config = await AsyncModelMapper.get_model_config_by_id(session, model_config_id)
            rag_result = {
                "contexts": [],
                "sources": [],
                "used_knowledge_base": False,
                "vector_db_id": None,
                "vector_db_ids": [],
                "queried_vector_db_ids": [],
                "retrieval_layers": [],
                "total_results": 0,
                "avg_similarity": 0.0,
                "fallback_used": False,
            }
            if model_config and user_id is not None:
                rag_result = await AsyncVectorService.query_vector_by_model(
                    session,
                    model_config_id,
                    last_user_message,
                    user_id=user_id,
                )

            prompt_messages: List[ChatMessage] = []
            enriched_sources: List[Dict[str, Any]] = []
            citation_labels: List[str] = []
            if model_config:
                prompt_messages, enriched_sources, citation_labels = AsyncChatService._build_prompt_orchestration(
                    model_config,
                    last_user_message,
                    rag_result,
                )
                if enriched_sources:
                    rag_result["sources"] = enriched_sources
                    rag_result["contexts"] = [source["content"] for source in enriched_sources]

            if rag_result["used_knowledge_base"]:
                chat_messages_list = prompt_messages + chat_messages_list
            elif prompt_messages:
                chat_messages_list = prompt_messages + chat_messages_list

            # 获取异步 LLM 客户端
            model = await AsyncLLMPool.get_client(model_config_id, session)
            
            # 异步调用 LLM
            response = await model.chat(chat_messages_list)
            content = AsyncChatService.extract_response_content(response)

            if rag_result["used_knowledge_base"]:
                grounded_level = AsyncChatService._grounding_summary(rag_result["avg_similarity"])
                content = (
                    f"【平均匹配度 {rag_result['avg_similarity']:.2%}】\n\n"
                    f"{content}"
                )

            raw_sources = rag_result.get("sources", [])
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
                    "retrieval_layer": s.get("retrieval_layer", ""),
                    "citation_label": s.get("citation_label", ""),
                    "confidence_score": round(s.get("confidence_score", 0.0), 4),
                    "confidence_label": s.get("confidence_label", ""),
                }
                for s in raw_sources
            ]
            ct_rechat = getattr(model_config, "citation_template", None) if model_config else None
            content, source_citations = AsyncChatService._renumber_citations(content, source_citations, ct_rechat)

            grounded_ratio = max(0.0, min(1.0, rag_result["avg_similarity"])) if rag_result["used_knowledge_base"] else 0.0
            grounded_level = AsyncChatService._grounding_summary(grounded_ratio)

            # 保存回复（含富数据）
            rechat_metadata = {}
            if source_citations:
                rechat_metadata["sources"] = source_citations
            if grounded_ratio:
                rechat_metadata["grounded_ratio"] = round(grounded_ratio, 4)
                rechat_metadata["grounded_level"] = grounded_level
            res = await AsyncChatMapper.save_message(
                session, conversation_id, "assistant", content,
                metadata=rechat_metadata if rechat_metadata else None,
            )

            logger.info(f"成功重新回答: conversation_id={conversation_id}")
            return {
                "response": res,
                "conversation_id": conversation_id,
                "conversation_name": conversation_info['name'],
                "rag_info": {
                    "used_knowledge_base": rag_result["used_knowledge_base"],
                    "vector_db_id": rag_result["vector_db_id"],
                    "vector_db_ids": rag_result.get("vector_db_ids", []),
                    "queried_vector_db_ids": rag_result.get("queried_vector_db_ids", []),
                    "retrieval_layers": rag_result.get("retrieval_layers", []),
                    "fallback_used": rag_result.get("fallback_used", False),
                    "total_results": rag_result["total_results"],
                    "avg_similarity": rag_result["avg_similarity"],
                    "grounded_level": grounded_level,
                },
                "sources": source_citations,
                "grounded_ratio": round(grounded_ratio, 4),
                "grounded_level": grounded_level,
            }
        except (ValidationError, NotFoundError, ForbiddenError):
            raise
        except Exception as e:
            logger.error(f"重新回答失败: {str(e)}", exc_info=True)
            raise InternalServerError(f"重新回答失败: {str(e)}")
    
    @staticmethod
    async def get_conversation(session: AsyncSession, user_id: int) -> List:
        """
        获取对话列表

        Raises:
            InternalServerError: 获取失败
        """
        logger.debug(f"获取对话列表: user_id={user_id}")
        try:
            conversation_id_list = await AsyncChatMapper.get_conversation_id(session, user_id)
            histories = []
            for item in conversation_id_list:
                conversation_id = item["conversation_id"]
                try:
                    history = await AsyncChatMapper.get_conversation(session, conversation_id, 10)
                    histories.append(history)
                except Exception as e:
                    logger.warning(f"跳过加载失败的对话 {conversation_id}: {e}")
            logger.debug(f"成功获取对话列表: user_id={user_id}, 共 {len(histories)} 个对话")
            return histories
        except Exception as e:
            logger.error(f"获取对话列表失败: {str(e)}", exc_info=True)
            raise InternalServerError(f"获取对话列表失败: {str(e)}")
    
    @staticmethod
    async def get_history(
        session: AsyncSession,
        conversation_id: int,
        user_id: Optional[int] = None,
    ) -> dict:
        """
        获取对话历史
        
        Raises:
            NotFoundError: 对话不存在
            InternalServerError: 获取失败
        """
        logger.debug(f"获取对话历史: conversation_id={conversation_id}")
        try:
            await AsyncChatService._assert_conversation_owner(session, conversation_id, user_id)
            conversation_info = await AsyncChatMapper.get_conversation_info(session, conversation_id)
            if not conversation_info:
                logger.warning(f"获取历史失败: 对话不存在 - conversation_id={conversation_id}")
                raise NotFoundError("对话不存在")
            
            history = await AsyncChatMapper.get_all_history(session, conversation_id)
            logger.debug(f"成功获取对话历史: conversation_id={conversation_id}")
            return {
                "conversation_info": conversation_info,
                "history": history
            }
        except (NotFoundError, ForbiddenError):
            raise
        except Exception as e:
            logger.error(f"获取历史记录失败: {str(e)}", exc_info=True)
            raise InternalServerError(f"获取历史记录失败: {str(e)}")
    
    @staticmethod
    async def delete_conversation(
        session: AsyncSession,
        conversation_id: int,
        user_id: Optional[int] = None
    ) -> int:
        """
        删除对话
        
        Raises:
            InternalServerError: 删除失败
        """
        logger.info(f"删除对话: conversation_id={conversation_id}")
        try:
            if user_id:
                await AsyncChatService._assert_conversation_owner(session, conversation_id, user_id)
                await AsyncVectorService.delete_conversation_attachment_vector_db(
                    session,
                    user_id=user_id,
                    conversation_id=conversation_id,
                )
            res = await AsyncChatMapper.delete_conversation(session, conversation_id)
            logger.info(f"成功删除对话: conversation_id={conversation_id}")
            return res
        except ForbiddenError:
            raise
        except Exception as e:
            logger.error(f"删除对话失败: {str(e)}", exc_info=True)
            raise InternalServerError(f"删除对话失败: {str(e)}")
    
    @staticmethod
    async def bot_chat(
        db: AsyncSession,
        user,
        message: str,
        conversation_id: Optional[str],
        system_prompt: str,
        vector_db_ids: List[int],
        model_config_id: Optional[int],
    ) -> Dict[str, Any]:
        """
        Bot 对话入口：两层 prompt 拼接。

        Layer 1 — Bot.system_prompt（人设/角色设定）
        Layer 2 — ModelConfig 的 RAG 编排（上下文模板、引用格式、拒答策略）
        """
        if not model_config_id:
            raise ValidationError("Bot 未关联模型配置，无法对话")

        # 创建或复用对话
        conv_id_int: Optional[int] = None
        if conversation_id:
            try:
                conv_id_int = int(conversation_id)
                await AsyncChatService._assert_conversation_owner(db, conv_id_int, user.id)
            except (ValueError, ForbiddenError):
                conv_id_int = None

        if not conv_id_int:
            conv_id_int = await AsyncChatService.create_conversation(
                db, user.id, model_config_id, message
            )

        # 保存用户消息
        await AsyncChatMapper.save_message(db, conv_id_int, "user", message)

        # 加载历史消息作为上下文
        conversation = await AsyncChatMapper.get_conversation(db, conv_id_int)
        history_messages = conversation["history"]["messages"] if conversation else []

        # 获取模型配置
        model_config = await AsyncModelMapper.get_model_config_by_id(db, model_config_id)

        # RAG 检索：Bot 的知识库优先，无则回退到 ModelConfig 默认行为
        rag_result = {
            "contexts": [], "sources": [], "used_knowledge_base": False,
            "vector_db_id": None, "vector_db_ids": [], "queried_vector_db_ids": [],
            "retrieval_layers": [], "total_results": 0, "avg_similarity": 0.0,
            "fallback_used": False,
        }
        if vector_db_ids:
            rag_result = await AsyncVectorService.query_vector_by_model(
                db, model_config_id, message,
                user_id=user.id,
                extra_vector_db_ids=vector_db_ids,
            )
        elif model_config:
            rag_result = await AsyncVectorService.query_vector_by_model(
                db, model_config_id, message, user_id=user.id,
            )

        # Layer 2: ModelConfig RAG 编排（引用格式、上下文模板、拒答策略）
        prompt_messages: List[ChatMessage] = []
        enriched_sources: List[Dict[str, Any]] = []
        citation_labels: List[str] = []
        if model_config:
            prompt_messages, enriched_sources, citation_labels = (
                AsyncChatService._build_prompt_orchestration(model_config, message, rag_result)
            )
            if enriched_sources:
                rag_result["sources"] = enriched_sources
                rag_result["contexts"] = [s["content"] for s in enriched_sources]

        # 拼接最终消息列表
        chat_messages: List[ChatMessage] = []

        # Layer 1: Bot 人设
        if system_prompt:
            chat_messages.append(ChatMessage(role="system", content=system_prompt))

        # Layer 2: RAG 编排消息
        if rag_result["used_knowledge_base"]:
            chat_messages.extend(prompt_messages)
            logger.info(
                "✅ [Bot RAG] 使用知识库: vector_db_ids=%s, layers=%s, 片段数=%s",
                rag_result.get("vector_db_ids") or [rag_result.get("vector_db_id")],
                rag_result.get("retrieval_layers", []),
                rag_result["total_results"],
            )
        elif prompt_messages:
            chat_messages.extend(prompt_messages)
            logger.info("ℹ️  [Bot RAG] 未命中知识库，使用通用知识回答")

        # 历史消息（按时间正序）
        for msg in reversed(history_messages):
            chat_messages.append(ChatMessage(role=msg["role"], content=msg["content"]))

        model = await AsyncLLMPool.get_client(model_config_id, db)
        response = await model.chat(chat_messages)
        answer = AsyncChatService.extract_response_content(response)

        # 后处理：来源标注与引用（与普通聊天一致）
        if rag_result["used_knowledge_base"]:
            grounded_level = AsyncChatService._grounding_summary(rag_result["avg_similarity"])
            answer = (
                f"【平均匹配度 {rag_result['avg_similarity']:.2%}】\n\n{answer}"
            )

        # 构建来源引用列表
        raw_sources = rag_result.get("sources", [])
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
                "retrieval_layer": s.get("retrieval_layer", ""),
                "citation_label": s.get("citation_label", ""),
                "confidence_score": round(s.get("confidence_score", 0.0), 4),
                "confidence_label": s.get("confidence_label", ""),
            }
            for s in raw_sources
        ]
        ct_bot = getattr(model_config, "citation_template", None) if model_config else None
        answer, source_citations = AsyncChatService._renumber_citations(answer, source_citations, ct_bot)

        grounded_ratio = max(0.0, min(1.0, rag_result["avg_similarity"])) if rag_result["used_knowledge_base"] else 0.0
        grounded_level = AsyncChatService._grounding_summary(grounded_ratio)

        # 保存助手回复（含富数据）
        bot_metadata = {}
        if source_citations:
            bot_metadata["sources"] = source_citations
        if grounded_ratio:
            bot_metadata["grounded_ratio"] = round(grounded_ratio, 4)
            bot_metadata["grounded_level"] = grounded_level
        await AsyncChatMapper.save_message(
            db, conv_id_int, "assistant", answer,
            metadata=bot_metadata if bot_metadata else None,
        )

        model_name = None
        if model_config:
            await db.refresh(model_config, ["base_model"])
            if model_config.base_model:
                model_name = model_config.base_model.model_name

        return {
            "answer": answer,
            "conversation_id": str(conv_id_int),
            "model_name": model_name,
            "rag_info": {
                "used_knowledge_base": rag_result["used_knowledge_base"],
                "vector_db_id": rag_result["vector_db_id"],
                "vector_db_ids": rag_result.get("vector_db_ids", []),
                "queried_vector_db_ids": rag_result.get("queried_vector_db_ids", []),
                "retrieval_layers": rag_result.get("retrieval_layers", []),
                "fallback_used": rag_result.get("fallback_used", False),
                "total_results": rag_result["total_results"],
                "avg_similarity": rag_result["avg_similarity"],
                "grounded_level": grounded_level,
            },
            "sources": source_citations,
            "grounded_ratio": round(grounded_ratio, 4),
            "grounded_level": grounded_level,
        }

    @staticmethod
    async def set_chat_history(
        session: AsyncSession,
        conversation_id: int,
        chat_history: int,
        user_id: Optional[int] = None,
    ) -> dict:
        """
        设置对话历史消息数量
        
        Raises:
            InternalServerError: 设置失败
        """
        logger.info(f"设置对话历史消息数量: conversation_id={conversation_id}, chat_history={chat_history}")
        try:
            await AsyncChatService._assert_conversation_owner(session, conversation_id, user_id)
            res = await AsyncChatMapper.set_chat_history(session, conversation_id, chat_history)
            logger.info(f"成功设置对话历史消息数量: conversation_id={conversation_id}")
            return res
        except ForbiddenError:
            raise
        except Exception as e:
            logger.error(f"设置历史消息数量失败: {str(e)}", exc_info=True)
            raise InternalServerError(f"设置历史消息数量失败: {str(e)}")
