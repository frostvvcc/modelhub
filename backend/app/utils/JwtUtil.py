from datetime import datetime, timedelta
from typing import Optional

from jose import jwt, JWTError
from functools import wraps

from passlib.context import CryptContext

from app.config import settings

# 密码哈希上下文
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def get_password_hash(password: str) -> str:
    """生成密码哈希"""
    return pwd_context.hash(password)

def generate_jwt(id: int, name: str, email: str, token_version: int = 0) -> str:
    payload = {
        'id': id,
        'name': name,
        'email': email,
        'tv': token_version,
        'exp': datetime.utcnow() + timedelta(minutes=settings.access_token_expire_minutes)
    }
    return jwt.encode(payload, settings.secret_key, settings.algorithm)

def authenticate_user(user, email: str, password: str):
    """验证用户凭据"""
    if not verify_password(password, user.password):
        return False
    return True

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """验证密码"""
    return pwd_context.verify(plain_password, hashed_password)

def verify_jwt(token: str):
    try:
        return jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])
    except JWTError:
        return {'error': 'Invalid token'}

# login_required 装饰器已移除，FastAPI 使用依赖注入进行认证
# 请使用 app_fastapi/utils/auth.py 中的 get_current_user