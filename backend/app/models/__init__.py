from app.models.user import User
from app.models.vector_db import VectorDb
from app.models.model_info import ModelInfo
# 导入其他模型
from app.models.model_config import ModelConfig
from app.models.document import Document
from app.models.message import Message
from app.models.conversation import Conversation
# 导入组织架构和权限模型
from app.models.organization import Organization, OrganizationMember
from app.models.permission import Role, Permission, RolePermission, UserRole
from app.models.provider_config import ProviderConfig
from app.models.bot import Bot
from app.models.teaching_space import TeachingSpace, TeachingSpaceMajor, TeachingSpaceResource

__all__ = [
    "User",
    "VectorDb",
    "ModelInfo",
    "ModelConfig",
    "Document",
    "Message",
    "Conversation",
    "Organization",
    "OrganizationMember",
    "Role",
    "Permission",
    "RolePermission",
    "UserRole",
    "ProviderConfig",
    "Bot",
    "TeachingSpace",
    "TeachingSpaceMajor",
    "TeachingSpaceResource",
]