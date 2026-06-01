"""
异步文件操作工具
"""
import os
import uuid
import shutil
import aiofiles
from pathlib import Path
from typing import Optional, Any
import logging

logger = logging.getLogger(__name__)


async def save_uploaded_file_async(file: Any, save_dir: str) -> Optional[str]:
    """异步保存上传的文件到指定目录"""
    if not os.path.exists(save_dir):
        os.makedirs(save_dir, exist_ok=True)
    
    try:
        filename = getattr(file, 'filename', 'unknown')
        unique_filename = f"{uuid.uuid4().hex}_{filename}"
        save_path = os.path.join(save_dir, unique_filename)
        
        # 异步读取文件内容
        if hasattr(file, 'read'):
            # FastAPI UploadFile
            file_content = await file.read()
            # 异步写入文件
            async with aiofiles.open(save_path, 'wb') as f:
                await f.write(file_content)
        elif hasattr(file, 'save'):
            # 支持 save 方法的文件对象
            file.save(save_path)
        else:
            # 其他文件对象
            async with aiofiles.open(save_path, 'wb') as f:
                if hasattr(file, 'read'):
                    content = await file.read()
                    await f.write(content)
                else:
                    shutil.copyfileobj(file, f)
        
        logger.info(f"文件保存成功: {save_path}")
        return unique_filename
    except Exception as e:
        logger.error(f"文件保存失败: {str(e)}")
        return None


async def read_file_async(file_path: str) -> Optional[bytes]:
    """异步读取文件"""
    try:
        async with aiofiles.open(file_path, 'rb') as f:
            content = await f.read()
        return content
    except Exception as e:
        logger.error(f"读取文件失败: {e}")
        return None


async def write_file_async(file_path: str, content: bytes) -> bool:
    """异步写入文件"""
    try:
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        async with aiofiles.open(file_path, 'wb') as f:
            await f.write(content)
        return True
    except Exception as e:
        logger.error(f"写入文件失败: {e}")
        return False


async def delete_file_async(file_path: str) -> bool:
    """异步删除文件"""
    import asyncio
    try:
        if os.path.exists(file_path):
            await asyncio.to_thread(os.remove, file_path)
            return True
        return False
    except Exception as e:
        logger.error(f"删除文件失败: {e}")
        return False

