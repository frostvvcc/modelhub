"""
用户相关数据模型
"""
from pydantic import BaseModel, EmailStr, field_validator, Field
from typing import Optional


class RegisterRequest(BaseModel):
    """用户注册请求"""
    name: str
    password: str = Field(..., min_length=6, max_length=128)
    email: Optional[EmailStr] = None
    describe: Optional[str] = None
    role: Optional[str] = None
    school_id: Optional[int] = None
    organization_id: Optional[int] = None
    student_id: Optional[str] = None
    employee_id: Optional[str] = None

    @field_validator('role')
    @classmethod
    def validate_role(cls, v):
        if v and v not in ('student', 'teacher'):
            raise ValueError('自注册仅支持 student 或 teacher 角色')
        return v


class LoginRequest(BaseModel):
    """用户登录请求（学号/工号 + 密码）"""
    account: str
    password: str


class TokenResponse(BaseModel):
    """Token 响应"""
    token: str


class UserInfoResponse(BaseModel):
    """用户信息响应"""
    id: int
    name: str
    email: str
    avatar: Optional[str] = None
    describe: Optional[str] = None
    type: str


class UpdateProfileRequest(BaseModel):
    """更新个人资料请求"""
    name: Optional[str] = None
    describe: Optional[str] = None
    phone: Optional[str] = None
    student_id: Optional[str] = None
    employee_id: Optional[str] = None


class ChangePasswordRequest(BaseModel):
    """修改密码请求"""
    old_password: str
    new_password: str

