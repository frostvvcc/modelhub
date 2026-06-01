"""
OCR工具类
支持图片文字识别，支持本地OCR和云端OCR服务
支持 PPStructure 版面分析，可处理复杂布局
"""
import os
import tempfile
import base64
import json
from pathlib import Path
from typing import Optional, List, Dict
import logging

logger = logging.getLogger(__name__)

_BACKEND_ROOT = Path(__file__).resolve().parents[2]
_OCR_CACHE_DIR = Path(
    os.getenv("MODELHUB_OCR_CACHE_DIR", str(_BACKEND_ROOT / "data" / "ocr_cache"))
).resolve()
_OCR_CACHE_DIR.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("PADDLE_PDX_CACHE_HOME", str(_OCR_CACHE_DIR / "paddlex"))
os.environ.setdefault("PADDLEOCR_HOME", str(_OCR_CACHE_DIR / "paddleocr"))
os.environ.setdefault("PADDLE_HOME", str(_OCR_CACHE_DIR / "paddle"))
os.environ.setdefault("HF_HOME", str(_OCR_CACHE_DIR / "huggingface"))


def _create_paddle_ocr(det_thresh: float = 0.3, box_thresh: float = 0.5):
    """Create PaddleOCR with arguments compatible with both 2.x and 3.x."""
    import inspect

    params = inspect.signature(PaddleOCR).parameters
    if "text_det_limit_side_len" in params:
        return PaddleOCR(
            lang="ch",
            text_detection_model_name=os.getenv("PADDLEOCR_DET_MODEL", "PP-OCRv5_mobile_det"),
            text_recognition_model_name=os.getenv("PADDLEOCR_REC_MODEL", "PP-OCRv5_mobile_rec"),
            text_det_limit_side_len=2560,
            text_det_thresh=det_thresh,
            text_det_box_thresh=box_thresh,
            use_textline_orientation=False,
            use_doc_orientation_classify=False,
            use_doc_unwarping=False,
        )

    return PaddleOCR(
        use_angle_cls=True,
        lang="ch",
        det_limit_side_len=2560,
        det_db_thresh=det_thresh,
        det_db_box_thresh=box_thresh,
        show_log=False,
    )


def _to_plain_data(value):
    if isinstance(value, dict):
        return value
    if hasattr(value, "json"):
        data = value.json() if callable(value.json) else value.json
        if isinstance(data, dict):
            return data.get("res", data)
    if hasattr(value, "to_dict"):
        data = value.to_dict()
        if isinstance(data, dict):
            return data.get("res", data)
    return value


def _bbox_center(bbox) -> tuple[float, float]:
    try:
        if hasattr(bbox, "tolist"):
            bbox = bbox.tolist()
        points = bbox or []
        y = sum(float(point[1]) for point in points) / len(points)
        x = sum(float(point[0]) for point in points) / len(points)
        return y, x
    except Exception:
        return 0.0, 0.0


def _extract_text_blocks_from_ocr_result(result) -> List[Dict]:
    """Normalize PaddleOCR 2.x/3.x outputs into text blocks."""
    result = _to_plain_data(result)
    if not result:
        return []

    if isinstance(result, dict):
        texts = result.get("rec_texts") or result.get("texts") or []
        scores = result.get("rec_scores") or result.get("scores") or []
        boxes = result.get("dt_polys") or result.get("rec_polys") or result.get("boxes") or []
        if isinstance(texts, str):
            texts = [texts]

        blocks = []
        for index, text in enumerate(texts):
            if not text:
                continue
            confidence = scores[index] if index < len(scores) else 0
            bbox = boxes[index] if index < len(boxes) else []
            y, x = _bbox_center(bbox)
            blocks.append({
                "text": str(text),
                "y": y,
                "x": x,
                "confidence": float(confidence or 0),
            })
        return blocks

    if isinstance(result, (list, tuple)):
        blocks = []
        for item in result:
            item = _to_plain_data(item)
            if isinstance(item, dict):
                blocks.extend(_extract_text_blocks_from_ocr_result(item))
                continue

            if isinstance(item, (list, tuple)) and len(item) >= 2:
                bbox = item[0]
                text_info = item[1]
                if isinstance(text_info, (list, tuple)) and text_info and isinstance(text_info[0], str):
                    text = text_info[0]
                    confidence = text_info[1] if len(text_info) > 1 else 0
                    if text:
                        y, x = _bbox_center(bbox)
                        blocks.append({
                            "text": str(text),
                            "y": y,
                            "x": x,
                            "confidence": float(confidence or 0),
                        })
                    continue

            if isinstance(item, (list, tuple)):
                blocks.extend(_extract_text_blocks_from_ocr_result(item))
        return blocks

    return []


def _run_paddle_ocr(ocr, image_path: str, det_thresh: Optional[float] = None, box_thresh: Optional[float] = None):
    if det_thresh is not None and hasattr(ocr, "predict"):
        try:
            return ocr.predict(
                image_path,
                text_det_thresh=det_thresh,
                text_det_box_thresh=box_thresh,
            )
        except TypeError:
            pass
    try:
        return ocr.ocr(image_path)
    except TypeError:
        return ocr.ocr(image_path, cls=True)

try:
    from PIL import Image, ImageEnhance
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

# 尝试导入PPStructure（版面分析）
try:
    from paddleocr import PPStructure
    PPSTRUCTURE_AVAILABLE = True
except ImportError:
    PPSTRUCTURE_AVAILABLE = False
    logger.info("PPStructure 不可用，将使用普通 PaddleOCR")

# 尝试导入PaddleOCR
try:
    from paddleocr import PaddleOCR
    PADDLEOCR_AVAILABLE = True
except ImportError:
    PADDLEOCR_AVAILABLE = False
    logger.warning("PaddleOCR未安装，OCR功能将不可用")


class AdvancedOCRProcessor:
    """
    高级OCR处理器（原 ocr_advanced.py，已合并）
    核心策略：图像预处理 + 多尺度识别 + 智能去重
    """

    def __init__(self):
        self.ocr = None
        self._init_ocr()

    def _init_ocr(self):
        if not PADDLEOCR_AVAILABLE:
            logger.error("PaddleOCR 不可用")
            return
        try:
            self.ocr = _create_paddle_ocr(det_thresh=0.25, box_thresh=0.45)
            logger.info("✅ 高级OCR处理器初始化成功")
        except Exception as e:
            logger.error(f"❌ 高级OCR初始化失败: {e}")
            self.ocr = None

    def preprocess_image(self, image_path: str) -> str:
        """预处理：添加边缘 padding，增强对比度/锐度"""
        if not PIL_AVAILABLE:
            return image_path
        try:
            img = Image.open(image_path)
            if img.mode != 'RGB':
                img = img.convert('RGB')
            from PIL import ImageOps
            img = ImageOps.expand(img, border=60, fill='white')
            img = ImageEnhance.Contrast(img).enhance(1.3)
            img = ImageEnhance.Sharpness(img).enhance(1.3)
            temp_path = image_path.replace('.', '_enhanced.')
            img.save(temp_path, 'JPEG', quality=95)
            return temp_path
        except Exception as e:
            logger.warning(f"图像预处理失败: {e}")
            return image_path

    def extract_text_from_image(self, image_path: str) -> Optional[str]:
        if not self.ocr or not os.path.exists(image_path):
            return None
        try:
            processed_path = self.preprocess_image(image_path)
            result1 = self._do_ocr(processed_path)
            lines1 = len([l for l in (result1 or '').split('\n') if l.strip()])
            final_result = result1
            if lines1 < 30:
                try:
                    result2 = self._do_ocr(processed_path, det_thresh=0.15, box_thresh=0.3)
                    lines2 = len([l for l in (result2 or '').split('\n') if l.strip()])
                    if lines2 > lines1:
                        final_result = result2
                except Exception:
                    pass
            if processed_path != image_path and os.path.exists(processed_path):
                try:
                    os.remove(processed_path)
                except Exception:
                    pass
            if not final_result or not final_result.strip():
                return None
            return self._deduplicate_text(final_result)
        except Exception as e:
            logger.error(f"高级OCR识别失败: {e}", exc_info=True)
            return None

    def _do_ocr(
        self,
        image_path: str,
        det_thresh: Optional[float] = None,
        box_thresh: Optional[float] = None
    ) -> Optional[str]:
        try:
            result = _run_paddle_ocr(self.ocr, image_path, det_thresh=det_thresh, box_thresh=box_thresh)
            texts_with_position = _extract_text_blocks_from_ocr_result(result)
            if not texts_with_position:
                return None
            texts_with_position = [
                item for item in texts_with_position
                if item.get('text') and item.get('confidence', 1) >= 0.3
            ]
            if not texts_with_position:
                return None
            texts_with_position.sort(key=lambda i: (i['y'], i['x']))
            return '\n'.join(item['text'] for item in texts_with_position)
        except Exception as e:
            logger.error(f"OCR执行失败: {e}")
            return None

    def _deduplicate_text(self, text: str) -> str:
        lines, filtered, prev = text.split('\n'), [], None
        for line in lines:
            if line.strip() and line != prev:
                filtered.append(line)
                prev = line
        return '\n'.join(filtered)


# 向后兼容的便捷函数
_advanced_ocr_instance = None


def get_advanced_ocr_processor() -> Optional[AdvancedOCRProcessor]:
    """获取高级OCR处理器单例（向后兼容）"""
    global _advanced_ocr_instance
    if _advanced_ocr_instance is None:
        _advanced_ocr_instance = AdvancedOCRProcessor()
    return _advanced_ocr_instance


def process_with_advanced_ocr(image_path: str) -> Optional[str]:
    """使用高级OCR处理图像（向后兼容）"""
    processor = get_advanced_ocr_processor()
    if not processor or not processor.ocr:
        return None
    return processor.extract_text_from_image(image_path)


class OCRProcessor:
    """OCR处理器"""

    def __init__(self, provider: str = "local"):
        """
        初始化OCR处理器

        Args:
            provider: OCR提供商，可选值：local, baidu, tencent, aliyun
        """
        self.provider = provider
        self.paddle_ocr = None
        self.advanced_ocr = None  # 高级OCR处理器
        self.ppstructure = None  # 添加 PPStructure 实例
        self._init_ocr()
    
    def _init_ocr(self):
        """初始化OCR引擎"""
        if self.provider == "local":
            # 优先使用高级OCR处理器 (最高优先级)
            if PADDLEOCR_AVAILABLE:
                try:
                    logger.info("🚀 正在初始化高级OCR处理器...")
                    self.advanced_ocr = AdvancedOCRProcessor()

                    if self.advanced_ocr.ocr:
                        logger.info("✅ 高级OCR处理器初始化成功")
                        return  # 使用高级OCR,直接返回
                    else:
                        logger.warning("高级OCR初始化失败,ocr对象为None")
                        self.advanced_ocr = None
                except Exception as e:
                    logger.error(f"高级OCR初始化异常: {e}", exc_info=True)
                    self.advanced_ocr = None

            # 如果高级OCR不可用，尝试 PPStructure（版面分析）
            if PPSTRUCTURE_AVAILABLE:
                try:
                    self.ppstructure = PPStructure(
                        show_log=False,
                        image_orientation=True,  # 自动检测图像方向
                        layout=True,              # 启用版面分析
                        table=True,               # 启用表格识别
                        ocr=True,                 # 启用 OCR
                        recovery=True             # 启用版面恢复
                    )
                    logger.info("PPStructure 初始化成功（支持复杂布局）")
                    return  # 成功初始化 PPStructure，直接返回
                except Exception as e:
                    logger.warning(f"PPStructure 初始化失败: {e}，将使用普通 PaddleOCR")
                    self.ppstructure = None

            # 如果 PPStructure 也不可用，使用普通 PaddleOCR
            if PADDLEOCR_AVAILABLE:
                try:
                    logger.info("正在初始化标准 PaddleOCR...")
                    self.paddle_ocr = _create_paddle_ocr(det_thresh=0.3, box_thresh=0.5)
                    logger.info("✅ PaddleOCR 初始化成功(标准模式)")
                except Exception as e:
                    logger.error(f"PaddleOCR 初始化失败: {e}")
                    self.paddle_ocr = None
                    logger.warning("没有可用的本地 OCR 引擎")
            else:
                logger.warning("没有可用的本地 OCR 引擎")
        elif self.provider in ["baidu", "tencent", "aliyun"]:
            # 云端OCR服务
            logger.info(f"使用云端OCR服务: {self.provider}")
            # 验证配置
            self._validate_cloud_config()
        else:
            logger.warning(f"未知的OCR提供商: {self.provider}，将尝试使用本地OCR")
            self.provider = "local"
            self._init_ocr()
    
    def _validate_cloud_config(self):
        """验证云端OCR配置"""
        from app.config import settings
        
        if self.provider == "baidu":
            if not settings.baidu_ocr_api_key or not settings.baidu_ocr_secret_key:
                logger.warning("百度OCR API Key未配置，将尝试使用本地OCR")
                self.provider = "local"
                self._init_ocr()
        elif self.provider == "tencent":
            if not settings.tencent_ocr_secret_id or not settings.tencent_ocr_secret_key:
                logger.warning("腾讯OCR Secret未配置，将尝试使用本地OCR")
                self.provider = "local"
                self._init_ocr()
        elif self.provider == "aliyun":
            if not settings.aliyun_ocr_access_key_id or not settings.aliyun_ocr_access_key_secret:
                logger.warning("阿里云OCR Access Key未配置，将尝试使用本地OCR")
                self.provider = "local"
                self._init_ocr()
    
    def extract_text_from_image(self, image_path: str) -> Optional[str]:
        """
        从图片中提取文字
        
        Args:
            image_path: 图片文件路径
            
        Returns:
            提取的文字内容，如果失败返回None
        """
        if not os.path.exists(image_path):
            logger.error(f"图片文件不存在: {image_path}")
            return None
        
        try:
            if self.provider == "local":
                # 优先使用高级OCR
                if self.advanced_ocr:
                    try:
                        logger.info("🚀 使用高级OCR处理图像")
                        return self.advanced_ocr.extract_text_from_image(image_path)
                    except Exception as e:
                        logger.warning(f"高级OCR识别失败，尝试使用 PPStructure: {e}")
                        if self.ppstructure:
                            return self._extract_with_ppstructure(image_path)
                        elif self.paddle_ocr:
                            return self._extract_with_paddleocr(image_path)
                        else:
                            logger.error("没有可用的备选 OCR 引擎")
                            return None

                # 优先使用 PPStructure（版面分析）
                if self.ppstructure:
                    try:
                        return self._extract_with_ppstructure(image_path)
                    except Exception as e:
                        logger.warning(f"PPStructure 识别失败，尝试使用 PaddleOCR: {e}")
                        if self.paddle_ocr:
                            return self._extract_with_paddleocr(image_path)
                        else:
                            logger.error("没有可用的备选 OCR 引擎")
                            return None

                # 如果没有 PPStructure，使用普通 PaddleOCR
                elif self.paddle_ocr:
                    try:
                        return self._extract_with_paddleocr(image_path)
                    except Exception as e:
                        logger.error(f"PaddleOCR 识别失败: {e}")
                        logger.error("没有可用的备选 OCR 引擎")
                        return None
                else:
                    logger.error("没有可用的本地 OCR 引擎")
                    return None
            elif self.provider == "baidu":
                return self._extract_with_baidu_ocr(image_path)
            elif self.provider == "tencent":
                return self._extract_with_tencent_ocr(image_path)
            elif self.provider == "aliyun":
                return self._extract_with_aliyun_ocr(image_path)
            else:
                logger.error(f"不支持的OCR提供商: {self.provider}")
                return None
        except Exception as e:
            logger.error(f"OCR识别失败: {image_path}, 错误: {str(e)}", exc_info=True)
            return None

    def _extract_with_ppstructure(self, image_path: str) -> Optional[str]:
        """使用 PPStructure 提取文字（支持版面分析）"""
        try:
            # 使用 PPStructure 处理图片
            result = self.ppstructure(image_path)

            if not result:
                logger.warning(f"PPStructure 未识别到内容: {image_path}")
                return None

            # 提取并组织文本
            extracted_text = self._format_ppstructure_result(result)

            logger.info(f"PPStructure 识别成功: {image_path}, 文字长度: {len(extracted_text)}")
            return extracted_text if extracted_text.strip() else None

        except Exception as e:
            logger.error(f"PPStructure 识别失败: {e}", exc_info=True)
            raise

    def _format_ppstructure_result(self, result: list) -> str:
        """
        格式化 PPStructure 的输出结果

        Args:
            result: PPStructure 返回的结果列表

        Returns:
            格式化后的文本
        """
        output_lines = []

        for item in result:
            if not isinstance(item, dict):
                continue

            # 获取区域类型
            type_name = item.get('type', 'unknown')
            # 获取区域内容
            res = item.get('res', [])

            if type_name == 'title':
                # 标题区域
                for line in res:
                    if isinstance(line, dict) and 'text' in line:
                        output_lines.append(f"【标题】{line['text']}")
                    elif isinstance(line, str):
                        output_lines.append(f"【标题】{line}")

            elif type_name == 'table':
                # 表格区域
                output_lines.append("[表格]")
                for line in res:
                    if isinstance(line, dict) and 'text' in line:
                        output_lines.append(f"  {line['text']}")
                    elif isinstance(line, str):
                        output_lines.append(f"  {line}")
                output_lines.append("[/表格]")

            elif type_name == 'figure':
                # 图片区域
                output_lines.append("[图片]")

            elif type_name == 'text':
                # 正文区域
                for line in res:
                    if isinstance(line, dict) and 'text' in line:
                        output_lines.append(line['text'])
                    elif isinstance(line, str):
                        output_lines.append(line)

            else:
                # 其他类型，直接提取文字
                for line in res:
                    if isinstance(line, dict) and 'text' in line:
                        output_lines.append(line['text'])
                    elif isinstance(line, str):
                        output_lines.append(line)

        return '\n'.join(output_lines)

    def _extract_with_paddleocr(self, image_path: str) -> Optional[str]:
        """使用PaddleOCR提取文字"""
        try:
            result = _run_paddle_ocr(self.paddle_ocr, image_path)
            texts_with_position = _extract_text_blocks_from_ocr_result(result)

            if not texts_with_position:
                logger.warning(f"PaddleOCR未识别到文字: {image_path}")
                return None

            # 先按 y 坐标（从上到下）排序，同行的按 x 坐标（从左到右）排序
            texts_with_position.sort(key=lambda item: (item['y'], item['x']))

            # 提取排序后的文字
            extracted_text = '\n'.join([item['text'] for item in texts_with_position])

            logger.info(f"PaddleOCR识别成功: {image_path}, 识别 {len(texts_with_position)} 个文本块, 文字总长度: {len(extracted_text)}")
            return extracted_text if extracted_text.strip() else None

        except Exception as e:
            logger.error(f"PaddleOCR识别失败: {e}", exc_info=True)
            return None

    def _extract_with_baidu_ocr(self, image_path: str) -> Optional[str]:
        """使用百度OCR提取文字"""
        try:
            from app.config import settings
            import requests
            
            # 读取图片并转换为base64
            with open(image_path, 'rb') as f:
                image_data = base64.b64encode(f.read()).decode('utf-8')
            
            # 获取access_token
            token_url = "https://aip.baidubce.com/oauth/2.0/token"
            token_params = {
                "grant_type": "client_credentials",
                "client_id": settings.baidu_ocr_api_key,
                "client_secret": settings.baidu_ocr_secret_key
            }
            token_response = requests.post(token_url, params=token_params)
            token_data = token_response.json()
            
            if "access_token" not in token_data:
                logger.error(f"百度OCR获取token失败: {token_data}")
                return None
            
            access_token = token_data["access_token"]
            
            # 调用OCR API
            ocr_url = f"https://aip.baidubce.com/rest/2.0/ocr/v1/general_basic?access_token={access_token}"
            ocr_data = {
                "image": image_data
            }
            ocr_response = requests.post(ocr_url, data=ocr_data)
            ocr_result = ocr_response.json()
            
            if "words_result" not in ocr_result:
                logger.warning(f"百度OCR未识别到文字: {ocr_result}")
                return None
            
            # 提取文字
            texts = [item["words"] for item in ocr_result["words_result"]]
            extracted_text = '\n'.join(texts)
            
            logger.info(f"百度OCR识别成功: {image_path}, 文字长度: {len(extracted_text)}")
            return extracted_text if extracted_text.strip() else None
            
        except Exception as e:
            logger.error(f"百度OCR识别失败: {e}", exc_info=True)
            return None
    
    def _extract_with_tencent_ocr(self, image_path: str) -> Optional[str]:
        """使用腾讯OCR提取文字"""
        try:
            from app.config import settings
            from tencentcloud.common import credential
            from tencentcloud.common.profile.client_profile import ClientProfile
            from tencentcloud.common.profile.http_profile import HttpProfile
            from tencentcloud.ocr.v20181119 import ocr_client, models
            
            # 读取图片
            with open(image_path, 'rb') as f:
                image_data = f.read()
            image_base64 = base64.b64encode(image_data).decode('utf-8')
            
            # 初始化客户端
            cred = credential.Credential(
                settings.tencent_ocr_secret_id,
                settings.tencent_ocr_secret_key
            )
            httpProfile = HttpProfile()
            httpProfile.endpoint = "ocr.tencentcloudapi.com"
            clientProfile = ClientProfile()
            clientProfile.httpProfile = httpProfile
            client = ocr_client.OcrClient(cred, "ap-beijing", clientProfile)
            
            # 调用OCR API
            req = models.GeneralBasicOCRRequest()
            req.ImageBase64 = image_base64
            resp = client.GeneralBasicOCR(req)
            
            # 提取文字
            texts = [item.TextDetections[0].DetectedText for item in resp.TextDetections]
            extracted_text = '\n'.join(texts)
            
            logger.info(f"腾讯OCR识别成功: {image_path}, 文字长度: {len(extracted_text)}")
            return extracted_text if extracted_text.strip() else None
            
        except ImportError:
            logger.error("腾讯云SDK未安装，请运行: pip install tencentcloud-sdk-python")
            return None
        except Exception as e:
            logger.error(f"腾讯OCR识别失败: {e}", exc_info=True)
            return None
    
    def _extract_with_aliyun_ocr(self, image_path: str) -> Optional[str]:
        """使用阿里云OCR提取文字"""
        try:
            from app.config import settings
            import requests
            import hmac
            import hashlib
            from datetime import datetime
            from urllib.parse import quote
            
            # 读取图片
            with open(image_path, 'rb') as f:
                image_data = f.read()
            image_base64 = base64.b64encode(image_data).decode('utf-8')
            
            # 阿里云OCR API参数
            endpoint = settings.aliyun_ocr_endpoint
            access_key_id = settings.aliyun_ocr_access_key_id
            access_key_secret = settings.aliyun_ocr_access_key_secret
            
            # 构建请求
            url = f"https://{endpoint}/api/predict/ocr_general"
            timestamp = datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ')
            
            # 构建签名（简化版，实际应该使用阿里云SDK）
            # 这里使用简化的方式，建议使用官方SDK
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"APPCODE {access_key_secret}"  # 如果使用APPCODE方式
            }
            
            data = {
                "image": image_base64
            }
            
            response = requests.post(url, json=data, headers=headers)
            result = response.json()
            
            if "content" in result:
                extracted_text = result["content"]
                logger.info(f"阿里云OCR识别成功: {image_path}, 文字长度: {len(extracted_text)}")
                return extracted_text if extracted_text.strip() else None
            else:
                logger.warning(f"阿里云OCR未识别到文字: {result}")
                return None
            
        except ImportError:
            logger.error("requests库未安装，请运行: pip install requests")
            return None
        except Exception as e:
            logger.error(f"阿里云OCR识别失败: {e}", exc_info=True)
            return None
    
    def save_ocr_result_to_file(self, ocr_text: str, output_path: str) -> bool:
        """
        将OCR结果保存到文件
        
        Args:
            ocr_text: OCR识别的文字内容
            output_path: 输出文件路径
            
        Returns:
            是否保存成功
        """
        try:
            # 确保输出目录存在
            output_dir = os.path.dirname(output_path)
            if output_dir and not os.path.exists(output_dir):
                os.makedirs(output_dir, exist_ok=True)
            
            # 保存文字内容到文件
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write(ocr_text)
            
            logger.info(f"OCR结果已保存到: {output_path}")
            return True
        except Exception as e:
            logger.error(f"保存OCR结果失败: {e}", exc_info=True)
            return False


# 全局OCR处理器实例
_ocr_processor: Optional[OCRProcessor] = None


def get_ocr_processor() -> Optional[OCRProcessor]:
    """获取OCR处理器实例（单例模式）"""
    global _ocr_processor
    if _ocr_processor is None:
        logger.info("=" * 80)
        logger.info("首次初始化OCR处理器...")
        logger.info("=" * 80)
        try:
            from app.config import settings
            provider = settings.ocr_provider
            _ocr_processor = OCRProcessor(provider=provider)

            # 检查初始化结果
            if _ocr_processor.advanced_ocr:
                logger.info("✅ OCR处理器就绪: 使用高级OCR")
            elif _ocr_processor.ppstructure:
                logger.info("✅ OCR处理器就绪: 使用PPStructure")
            elif _ocr_processor.paddle_ocr:
                logger.info("✅ OCR处理器就绪: 使用标准PaddleOCR")
            else:
                logger.warning("⚠️ OCR处理器就绪: 但没有可用的OCR引擎")

        except Exception as e:
            logger.error(f"❌ OCR处理器初始化失败: {e}", exc_info=True)
            _ocr_processor = None

    return _ocr_processor


def process_image_with_ocr(image_path: str, output_dir: Optional[str] = None) -> Optional[str]:
    """
    处理图片并进行OCR，返回OCR文本文件路径
    
    Args:
        image_path: 图片文件路径
        output_dir: 输出目录，如果为None则使用临时目录
        
    Returns:
        OCR文本文件路径，如果失败返回None
    """
    ocr_processor = get_ocr_processor()
    if not ocr_processor:
        logger.error("OCR处理器不可用")
        return None
    
    # 提取文字
    ocr_text = ocr_processor.extract_text_from_image(image_path)
    if not ocr_text:
        logger.warning(f"图片OCR未识别到文字: {image_path}")
        return None
    
    # 确定输出路径
    if output_dir is None:
        output_dir = tempfile.gettempdir()
    
    # 生成输出文件名（使用原文件名，扩展名改为.txt）
    image_name = Path(image_path).stem
    output_path = os.path.join(output_dir, f"{image_name}_ocr.txt")
    
    # 保存OCR结果
    if ocr_processor.save_ocr_result_to_file(ocr_text, output_path):
        return output_path
    else:
        return None
