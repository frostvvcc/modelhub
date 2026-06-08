"""
压缩包处理工具
支持 zip、tar、tar.gz 等格式的解压
"""
import os
import zipfile
import tarfile
import tempfile
from pathlib import Path
from typing import List, Dict, Optional, Tuple
import logging

logger = logging.getLogger(__name__)

# 支持的文件格式（用于向量化）
SUPPORTED_FILE_EXTENSIONS = {
    '.txt', '.md', '.pdf', '.doc', '.docx', 
    '.html', '.htm', '.xml', '.json', '.csv',
    '.py', '.js', '.ts', '.java', '.cpp', '.c', '.h',
    '.sh', '.bat', '.sql', '.yaml', '.yml',
    # 图片格式（支持OCR）
    '.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp', '.tiff', '.tif'
}

# 图片文件格式
IMAGE_EXTENSIONS = {
    '.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp', '.tiff', '.tif'
}

# 支持的压缩包格式
ARCHIVE_EXTENSIONS = {
    '.zip': 'zip',
    '.tar': 'tar',
    '.tar.gz': 'tar.gz',
    '.tgz': 'tar.gz',
    '.tar.bz2': 'tar.bz2',
    '.tar.xz': 'tar.xz'
}


def is_archive_file(filename: str) -> bool:
    """判断文件是否为压缩包"""
    filename_lower = filename.lower()
    return any(filename_lower.endswith(ext) for ext in ARCHIVE_EXTENSIONS.keys())


def is_supported_file(filename: str) -> bool:
    """判断文件是否为支持的文件格式"""
    ext = Path(filename).suffix.lower()
    return ext in SUPPORTED_FILE_EXTENSIONS


def is_image_file(filename: str) -> bool:
    """判断文件是否为图片格式"""
    ext = Path(filename).suffix.lower()
    return ext in IMAGE_EXTENSIONS


def extract_archive(archive_path: str, extract_to: str) -> List[Dict[str, any]]:
    """
    解压压缩包并返回文件列表
    
    Args:
        archive_path: 压缩包路径
        extract_to: 解压目标目录
        
    Returns:
        文件列表，每个元素包含：
        - path: 文件相对路径（包含目录结构）
        - full_path: 完整文件路径
        - is_dir: 是否为目录
        - size: 文件大小
    """
    archive_path_obj = Path(archive_path)
    filename_lower = archive_path_obj.name.lower()
    
    files = []
    
    try:
        # 创建解压目录
        os.makedirs(extract_to, exist_ok=True)
        
        # 根据文件扩展名选择解压方法
        if filename_lower.endswith('.zip'):
            files = _extract_zip(archive_path, extract_to)
        elif filename_lower.endswith(('.tar', '.tar.gz', '.tgz', '.tar.bz2', '.tar.xz')):
            files = _extract_tar(archive_path, extract_to)
        else:
            raise ValueError(f"不支持的压缩包格式: {archive_path}")
        
        logger.info(f"成功解压压缩包: {archive_path}, 共 {len(files)} 个文件/目录")
        return files
        
    except Exception as e:
        logger.error(f"解压压缩包失败: {archive_path}, 错误: {str(e)}", exc_info=True)
        raise


MAX_EXTRACT_SIZE = 500 * 1024 * 1024
MAX_COMPRESS_RATIO = 100
MAX_TOTAL_EXTRACT_SIZE = 1024 * 1024 * 1024


def _extract_zip(zip_path: str, extract_to: str) -> List[Dict[str, any]]:
    """解压 ZIP 文件 (含路径穿越和 ZIP Bomb 防护)"""
    files = []
    real_extract = os.path.realpath(extract_to)
    total_size = 0

    with zipfile.ZipFile(zip_path, 'r') as zip_ref:
        for info in zip_ref.infolist():
            filename = _decode_zip_filename(info.filename)

            if '__MACOSX' in filename or '.DS_Store' in filename:
                continue

            if info.file_size > MAX_EXTRACT_SIZE:
                logger.warning(f"跳过过大文件: {filename} ({info.file_size} bytes)")
                continue
            if info.compress_size > 0 and info.file_size / info.compress_size > MAX_COMPRESS_RATIO:
                logger.warning(f"跳过可疑压缩比: {filename}")
                continue
            total_size += info.file_size
            if total_size > MAX_TOTAL_EXTRACT_SIZE:
                logger.warning(f"总解压大小超限，停止解压")
                break

            try:
                extracted_path = os.path.join(extract_to, filename)
                real_target = os.path.realpath(extracted_path)
                if not real_target.startswith(real_extract + os.sep) and real_target != real_extract:
                    logger.warning(f"跳过路径穿越: {filename}")
                    continue

                os.makedirs(os.path.dirname(extracted_path), exist_ok=True)

                with zip_ref.open(info) as source:
                    with open(extracted_path, 'wb') as target:
                        target.write(source.read())

            except Exception as e:
                logger.warning(f"解压文件失败: {filename}, 错误: {str(e)}")
                continue

            # 构建文件信息
            if info.is_dir():
                files.append({
                    'path': filename.rstrip('/'),
                    'full_path': extracted_path,
                    'is_dir': True,
                    'size': 0
                })
            else:
                # 检查文件格式
                if is_supported_file(filename):
                    file_size = os.path.getsize(extracted_path) if os.path.exists(extracted_path) else 0
                    files.append({
                        'path': filename,
                        'full_path': extracted_path,
                        'is_dir': False,
                        'size': file_size
                    })
                else:
                    logger.info(f"跳过不支持的文件格式: {filename}")
                    # 删除不支持的文件
                    try:
                        if os.path.exists(extracted_path):
                            os.remove(extracted_path)
                    except Exception:
                        pass

    return files


def _decode_zip_filename(filename: str) -> str:
    """
    智能解码ZIP文件中的文件名

    处理Windows压缩工具创建的ZIP文件中的中文文件名编码问题
    - Windows: 通常使用GBK/CP936编码
    - macOS/Linux: 通常使用UTF-8编码

    Args:
        filename: 从zip文件中读取的原始文件名

    Returns:
        解码后的正确文件名
    """
    # 如果文件名不包含非ASCII字符,直接返回
    try:
        filename.encode('ascii')
        return filename
    except UnicodeEncodeError:
        pass  # 包含非ASCII字符,需要处理

    # 尝试1: 检查是否是UTF-8编码
    try:
        # 如果已经是正确的Unicode,直接返回
        if '\u4e00' <= filename <= '\u9fff':  # 包含中文字符
            return filename
    except:
        pass

    # 尝试2: 使用chardet检测编码
    try:
        import chardet
        # 将字符串编码为bytes(可能是错误的编码)
        filename_bytes = filename.encode('cp437')  # ZIP默认编码
        detected = chardet.detect(filename_bytes)
        encoding = detected.get('encoding', 'utf-8')

        if encoding and encoding.lower() not in ['utf-8', 'ascii']:
            try:
                decoded = filename_bytes.decode(encoding)
                logger.info(f"✓ 使用chardet检测的编码 {encoding} 解码文件名")
                return decoded
            except:
                pass
    except ImportError:
        pass  # chardet未安装

    # 尝试3: 尝试常见中文编码
    common_encodings = ['gbk', 'gb2312', 'gb18030', 'big5']

    for encoding in common_encodings:
        try:
            # ZIP文件在Windows下创建时,文件名会被错误地用cp437解码
            # 我们需要反转这个过程: cp437 encode → 目标编码 decode
            filename_bytes = filename.encode('cp437')
            decoded = filename_bytes.decode(encoding)

            # 检查解码后是否包含中文字符
            if '\u4e00' <= decoded <= '\u9fff':
                logger.info(f"✓ 使用 {encoding} 编码成功解码文件名: {decoded}")
                return decoded
        except (UnicodeEncodeError, UnicodeDecodeError):
            continue

    # 所有尝试都失败,返回原始文件名
    logger.warning(f"⚠️ 无法正确解码文件名,使用原始名称: {filename}")
    return filename


def _extract_tar(tar_path: str, extract_to: str) -> List[Dict[str, any]]:
    """解压 TAR 文件（支持 tar、tar.gz、tar.bz2、tar.xz）"""
    files = []
    
    # 根据扩展名选择打开模式
    filename_lower = Path(tar_path).name.lower()
    if filename_lower.endswith('.tar.gz') or filename_lower.endswith('.tgz'):
        mode = 'r:gz'
    elif filename_lower.endswith('.tar.bz2'):
        mode = 'r:bz2'
    elif filename_lower.endswith('.tar.xz'):
        mode = 'r:xz'
    else:
        mode = 'r'
    
    with tarfile.open(tar_path, mode) as tar_ref:
        for member in tar_ref.getmembers():
            # 跳过 macOS 的 __MACOSX 目录
            if '__MACOSX' in member.name or '.DS_Store' in member.name:
                continue
            
            # 安全检查：防止路径遍历攻击
            if os.path.isabs(member.name) or '..' in member.name:
                logger.warning(f"跳过不安全的路径: {member.name}")
                continue

            if member.issym() or member.islnk():
                logger.warning(f"跳过符号链接: {member.name}")
                continue

            try:
                if hasattr(tarfile, 'data_filter'):
                    tar_ref.extract(member, extract_to, filter='data')
                else:
                    tar_ref.extract(member, extract_to)
            except Exception as e:
                logger.warning(f"解压文件失败: {member.name}, 错误: {str(e)}")
                continue
            
            # 构建文件信息
            extracted_path = os.path.join(extract_to, member.name)
            
            if member.isdir():
                files.append({
                    'path': member.name.rstrip('/'),
                    'full_path': extracted_path,
                    'is_dir': True,
                    'size': 0
                })
            else:
                # 检查文件格式
                if is_supported_file(member.name):
                    file_size = os.path.getsize(extracted_path) if os.path.exists(extracted_path) else member.size
                    files.append({
                        'path': member.name,
                        'full_path': extracted_path,
                        'is_dir': False,
                        'size': file_size
                    })
                else:
                    logger.info(f"跳过不支持的文件格式: {member.name}")
                    # 删除不支持的文件
                    try:
                        if os.path.exists(extracted_path):
                            os.remove(extracted_path)
                    except Exception:
                        pass
    
    return files


def organize_files_by_structure(files: List[Dict[str, any]]) -> Dict[str, any]:
    """
    按照文件路径组织文件结构
    
    Returns:
        组织后的文件树结构
    """
    tree = {}
    
    for file_info in files:
        path_parts = file_info['path'].split('/')
        current = tree
        
        # 创建目录结构
        for i, part in enumerate(path_parts[:-1]):
            if part not in current:
                current[part] = {'type': 'dir', 'children': {}}
            current = current[part]['children']
        
        # 添加文件
        filename = path_parts[-1]
        if file_info['is_dir']:
            if filename not in current:
                current[filename] = {'type': 'dir', 'children': {}}
        else:
            current[filename] = {
                'type': 'file',
                'full_path': file_info['full_path'],
                'size': file_info['size']
            }
    
    return tree

