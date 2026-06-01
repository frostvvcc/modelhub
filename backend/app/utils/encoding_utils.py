"""
文件编码检测和智能读取工具
支持多种编码格式的自动检测和读取
"""
import logging
import chardet
from typing import Optional, Tuple

logger = logging.getLogger(__name__)


class EncodingDetector:
    """文件编码检测器"""

    # 常见中文编码优先级列表
    PRIORITY_ENCODINGS = [
        'utf-8',
        'gbk',
        'gb2312',
        'gb18030',
        'big5',  # 繁体中文
        'utf-16',
        'utf-16-le',
        'utf-16-be',
    ]

    @staticmethod
    def detect_encoding(file_path: str) -> Tuple[str, float]:
        """
        检测文件编码

        Args:
            file_path: 文件路径

        Returns:
            (编码名称, 置信度) 元组
        """
        try:
            with open(file_path, 'rb') as f:
                raw_data = f.read()

            # 使用 chardet 检测编码
            result = chardet.detect(raw_data)

            encoding = result.get('encoding', 'utf-8')
            confidence = result.get('confidence', 0.0)

            logger.info(f"检测到文件编码: {encoding}, 置信度: {confidence:.2f}")

            return encoding, confidence

        except Exception as e:
            logger.warning(f"编码检测失败: {e}, 默认使用utf-8")
            return 'utf-8', 0.0

    @staticmethod
    def read_file_with_fallback(file_path: str) -> Optional[str]:
        """
        智能读取文件内容,自动检测编码

        Args:
            file_path: 文件路径

        Returns:
            文件内容,如果读取失败返回None
        """
        # 第一次尝试: 自动检测编码
        encoding, confidence = EncodingDetector.detect_encoding(file_path)

        try:
            with open(file_path, 'r', encoding=encoding) as f:
                content = f.read()
            logger.info(f"✅ 使用 {encoding} 编码成功读取文件 (置信度: {confidence:.2f})")
            return content
        except UnicodeDecodeError:
            logger.warning(f"❌ 使用检测到的编码 {encoding} 读取失败,尝试备用编码...")

        # 第二次尝试: 遍历优先级编码列表
        for enc in EncodingDetector.PRIORITY_ENCODINGS:
            if enc == encoding:
                continue  # 已经尝试过

            try:
                with open(file_path, 'r', encoding=enc) as f:
                    content = f.read()

                logger.info(f"✅ 使用备用编码 {enc} 成功读取文件")
                return content

            except (UnicodeDecodeError, LookupError):
                continue

        # 第三次尝试: 使用 errors='ignore' 或 'replace'
        try:
            with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
                content = f.read()
            logger.warning(f"⚠️ 使用UTF-8 (with replacement) 读取文件,可能存在乱码")
            return content
        except Exception as e:
            logger.error(f"❌ 所有编码尝试均失败: {e}")
            return None

    @staticmethod
    def is_text_file(file_path: str) -> bool:
        """
        判断文件是否为文本文件

        Args:
            file_path: 文件路径

        Returns:
            是否为文本文件
        """
        try:
            # 读取文件前1024字节
            with open(file_path, 'rb') as f:
                raw_data = f.read(1024)

            # 如果全为0x00,可能是二进制文件
            if b'\x00' in raw_data[:100]:
                return False

            # 检测编码
            result = chardet.detect(raw_data)
            encoding = result.get('encoding', None)

            if encoding:
                return True

            return False

        except Exception as e:
            logger.warning(f"判断文件类型失败: {e}")
            return False


def read_file_smart(file_path: str) -> Optional[str]:
    """
    智能读取文件内容的便捷函数

    Args:
        file_path: 文件路径

    Returns:
        文件内容
    """
    detector = EncodingDetector()
    return detector.read_file_with_fallback(file_path)
