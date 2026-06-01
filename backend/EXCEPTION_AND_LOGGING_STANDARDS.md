# 异常处理和日志记录规范

## 概述

本文档定义了 ModelHub 后端项目的统一异常处理和日志记录规范，确保代码的一致性和可维护性。

## 异常处理规范

### 1. 异常类型

项目使用统一的异常类体系，所有异常都继承自 `AppException`：

- **`ValidationError`** (400): 请求参数验证错误
- **`UnauthorizedError`** (401): 未授权错误
- **`ForbiddenError`** (403): 禁止访问错误
- **`NotFoundError`** (404): 资源不存在错误
- **`ConflictError`** (409): 资源冲突错误（如重复创建）
- **`InternalServerError`** (500): 服务器内部错误

### 2. 使用方式

#### 服务层 (Service Layer)

```python
from app.utils.error_handler import NotFoundError, ValidationError, InternalServerError
from app.utils.logger_config import get_logger

logger = get_logger(__name__)

class AsyncUserService:
    @staticmethod
    async def get_user(user_id: int):
        logger.debug(f"获取用户: user_id={user_id}")
        
        user = await get_user_from_db(user_id)
        if not user:
            logger.warning(f"用户不存在: user_id={user_id}")
            raise NotFoundError("用户不存在")
        
        try:
            # 业务逻辑
            return user
        except Exception as e:
            logger.error(f"获取用户失败: {str(e)}", exc_info=True)
            raise InternalServerError(f"获取用户失败: {str(e)}")
```

#### 路由层 (Router Layer)

路由层**不需要**手动处理异常，直接抛出即可，中间件会自动处理：

```python
from app.utils.logger_config import get_logger

logger = get_logger(__name__)

@router.get("/users/{user_id}")
async def get_user(user_id: int, db: AsyncSession = Depends(get_async_db)):
    """获取用户信息"""
    # 直接调用服务，异常由中间件统一处理
    user = await AsyncUserService.get_user(db, user_id)
    return SuccessResponse(message="获取成功", data=user)
```

### 3. 异常转换

旧格式的异常（`Exception({'code': 401, 'msg': "..."})`）会自动转换为标准异常：

```python
# 旧代码（已废弃）
raise Exception({'code': 401, 'msg': "用户不存在"})

# 新代码（推荐）
raise NotFoundError("用户不存在")
```

## 日志记录规范

### 1. 日志配置

使用统一的日志配置模块 `app.utils.logger_config`：

```python
from app.utils.logger_config import get_logger

logger = get_logger(__name__)
```

### 2. 日志级别

- **DEBUG**: 详细的调试信息，如方法调用、参数值等
- **INFO**: 重要的业务操作，如用户注册、登录、数据创建等
- **WARNING**: 警告信息，如资源不存在、验证失败等
- **ERROR**: 错误信息，需要记录异常堆栈（使用 `exc_info=True`）

### 3. 日志格式

日志格式统一为：
```
%(asctime)s - %(name)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s
```

示例输出：
```
2024-01-15 10:30:45 - app.services.user_service - INFO - [user_service.py:35] - 用户注册成功: user_id=123, email=user@example.com
```

### 4. 日志记录最佳实践

#### 方法入口和出口

```python
@staticmethod
async def create_user(session: AsyncSession, name: str, email: str):
    logger.info(f"创建用户: email={email}")
    
    try:
        # 业务逻辑
        user = await create_user_in_db(...)
        logger.info(f"用户创建成功: user_id={user.id}")
        return user
    except Exception as e:
        logger.error(f"用户创建失败: {str(e)}", exc_info=True)
        raise
```

#### 敏感信息过滤

不要在日志中记录敏感信息（密码、token、API密钥等）：

```python
# ❌ 错误
logger.info(f"用户登录: email={email}, password={password}")

# ✅ 正确
logger.info(f"用户登录: email={email}")
```

#### 异常记录

记录异常时使用 `exc_info=True` 以包含完整的堆栈信息：

```python
try:
    # 业务逻辑
    pass
except Exception as e:
    logger.error(f"操作失败: {str(e)}", exc_info=True)
    raise InternalServerError(f"操作失败: {str(e)}")
```

## 中间件处理

所有异常由 `app.middleware.error_middleware` 统一处理，自动转换为标准 HTTP 响应：

```python
{
    "success": False,
    "message": "错误消息",
    "code": 404,
    "details": {}
}
```

## 迁移指南

### 从旧代码迁移

1. **替换异常类型**：
   ```python
   # 旧代码
   raise Exception({'code': 404, 'msg': "用户不存在"})
   
   # 新代码
   raise NotFoundError("用户不存在")
   ```

2. **移除路由层的 try-except**：
   ```python
   # 旧代码
   try:
       result = await service.method()
       return SuccessResponse(data=result)
   except Exception as e:
       raise HTTPException(status_code=500, detail=str(e))
   
   # 新代码
   result = await service.method()
   return SuccessResponse(data=result)
   ```

3. **统一日志记录器**：
   ```python
   # 旧代码
   import logging
   logger = logging.getLogger(__name__)
   
   # 新代码
   from app.utils.logger_config import get_logger
   logger = get_logger(__name__)
   ```

## 示例

完整示例请参考：
- `app/services/user_service.py` - 服务层示例
- `app/routers/user.py` - 路由层示例
- `app/middleware/error_middleware.py` - 中间件实现

