# app/utils/file_utils.py
import os
import uuid
import shutil
import logging

logger = logging.getLogger("FileUtils")


def save_uploaded_file(file, save_dir):
    """保存上传的文件到指定目录"""
    if not os.path.exists(save_dir):
        os.makedirs(save_dir)

    try:
        filename = getattr(file, 'filename', 'unknown')
        unique_filename = f"{uuid.uuid4().hex}_{filename}"
        save_path = os.path.join(save_dir, unique_filename)

        if hasattr(file, 'save'):
            file.save(save_path)
        elif hasattr(file, 'write'):
            with open(save_path, 'wb') as f:
                f.write(file.read())
        else:
            with open(save_path, 'wb') as f:
                shutil.copyfileobj(file, f)

        logger.info(f"文件保存成功: {save_path}")
        return unique_filename
    except Exception as e:
        logger.error(f"文件保存失败: {str(e)}")
        return None