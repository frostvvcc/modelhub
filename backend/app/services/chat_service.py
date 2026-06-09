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
        "【引用规则 — 必须遵守】\n"
        "1. 回答中每个来自上下文的事实都必须标注来源编号，如 [来源1]，不可省略。\n"
        "2. 来源编号必须与上面的 [来源N] 一一对应，不可编造不存在的编号。\n"
        "3. 如果一句话的信息来自多个来源，全部标注，如 [来源1][来源3]。\n\n"
        "【结果校验 — 必须遵守】\n"
        "4. 仔细核对上下文是否真正匹配用户的查询条件。特别注意：\n"
        "   - 如果用户指定了年份（如2019年），只引用该年份的内容，不要把其他年份的信息当作答案。\n"
        "   - 如果用户指定了院系/部门，只引用该院系的内容，不要混入其他院系的信息。\n"
        "5. 如果上下文中没有精确匹配用户指定条件的内容，必须明确说明未找到符合条件的信息，不要用不匹配的内容凑答案。"
    )
    DEFAULT_REFUSAL_STRATEGY = (
        "如果知识库资料不足以回答，请明确说明“当前知识库依据不足”，"
        "不要编造具体政策、日期、流程或数字。\n"
        "如果检索结果与用户查询的时间、院系等条件不匹配，"
        "请如实告知未找到符合条件的相关信息，而不是用不相关的内容回答。"
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
    def _relevance_from_source(source: Dict[str, Any]) -> tuple[float, str]:
        """计算单条检索结果的相关度（基于向量相似度），不是回答的可信度。"""
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
    def _count_tokens(text: str) -> int:
        """Token 精确计数，用于 context budget 控制。"""
        from app.services.agent.memory import count_tokens
        return count_tokens(text)

    @staticmethod
    def _build_context_blocks(
        raw_sources: List[Dict[str, Any]],
        citation_template: Optional[str],
        max_context_tokens: Optional[int],
    ) -> tuple[str, List[Dict[str, Any]], List[str]]:
        """把检索结果编排成带来源编号的上下文块，并按 token 预算截断。"""
        budget = max(500, min(int(max_context_tokens or 2000), 8000))
        blocks: List[str] = []
        enriched_sources: List[Dict[str, Any]] = []
        labels: List[str] = []
        used_tokens = 0
        label_counter = 0

        for source in raw_sources:
            confidence_score, confidence_label = AsyncChatService._relevance_from_source(source)
            content = (source.get("content") or "").strip()
            if not content:
                continue
            label_counter += 1
            label = AsyncChatService._make_citation_label(citation_template, label_counter)

            source_name = source.get('source') or '未知'
            if len(source_name) > 40:
                source_name = source_name[:37] + '...'
            header = f"{label}（{source_name}）"
            header_tokens = AsyncChatService._count_tokens(header)
            available_tokens = budget - used_tokens - header_tokens - 5
            if available_tokens <= 40:
                break
            content_tokens = AsyncChatService._count_tokens(content)
            if content_tokens > available_tokens:
                ratio = available_tokens / content_tokens
                trim_len = max(40, int(len(content) * ratio))
                trimmed_content = content[:trim_len].rstrip()
            else:
                trimmed_content = content
            block = f"{header}\n{trimmed_content}"
            block_tokens = AsyncChatService._count_tokens(block)
            blocks.append(block)
            used_tokens += block_tokens + 5
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
    async def _reformulate_for_retrieval(
        current_message: str,
        history_messages: List[Dict[str, str]],
    ) -> str:
        """
        Multi-turn Query Reformulation：结合对话历史将追问补全为独立查询。

        当用户追问"截止日期呢？"时，检索层不知道在问什么的截止日期。
        本方法利用对话历史将追问改写为独立的检索 query。

        Args:
            current_message: 当前用户消息
            history_messages: 逆序消息列表（最新在前），[0] 应为当前消息
        Returns:
            补全后的独立查询
        """
        if not history_messages or len(history_messages) <= 1:
            return current_message
        prior = history_messages[1:]
        if not prior:
            return current_message
        prior_chrono = list(reversed(prior))[-6:]
        from app.services.rag.query_rewriter import condense_follow_up
        return await condense_follow_up(current_message, prior_chrono)

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
        max_ctx_tokens = getattr(model_config, "max_context_tokens", None)
        if max_ctx_tokens is None:
            max_ctx_chars = getattr(model_config, "max_context_chars", None)
            max_ctx_tokens = int(max_ctx_chars) // 2 if max_ctx_chars else 2000
        context_blocks, enriched_sources, citation_labels = AsyncChatService._build_context_blocks(
            raw_sources,
            getattr(model_config, "citation_template", None),
            max_ctx_tokens,
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
        organization_id: Optional[int] = None,
        bot_id: Optional[int] = None
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
                organization_id=organization_id, school_id=school_id,
                bot_id=bot_id
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
    async def get_conversation(session: AsyncSession, user_id: int) -> List:
        """
        获取对话列表

        Raises:
            InternalServerError: 获取失败
        """
        logger.debug(f"获取对话列表: user_id={user_id}")
        try:
            # 批量查询：2 次 SQL 代替 N+1 次
            histories = await AsyncChatMapper.get_conversations_batch(session, user_id, msg_per_conv=10)
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
