# OCR功能设置指南

本文档说明如何设置OCR功能，以支持图片文件的自动文字识别。

## 功能说明

系统支持对上传的图片文件（JPG、PNG、GIF、BMP、WEBP、TIFF等格式）进行自动OCR文字识别，并将识别结果添加到向量数据库中进行检索。

## OCR引擎选择

系统支持多种OCR引擎，可通过配置选择：

### 本地OCR（无需API Key）

1. **PaddleOCR**（推荐）
   - 中文识别效果好（准确率 95%+）
   - 支持中英文混合识别
   - 需要安装PaddlePaddle和PaddleOCR
   - **无需API Key，完全免费**

2. **PPStructure**（高级版面分析）
   - 支持复杂布局识别（表格、标题、图片等）
   - 自动版面分析和恢复
   - 基于 PaddleOCR，同样无需 API Key

### 云端OCR服务（需要API Key）

3. **百度OCR**
   - 识别准确度高
   - 需要配置API Key和Secret Key
   - 有免费额度，超出后收费

4. **腾讯OCR**
   - 识别速度快
   - 需要配置Secret ID和Secret Key
   - 有免费额度，超出后收费

5. **阿里云OCR**
   - 识别准确度高
   - 需要配置Access Key ID和Access Key Secret
   - 有免费额度，超出后收费

## 配置方法

### 方式一：使用本地OCR（推荐，无需API Key）

在 `.env` 文件中配置：

```bash
# 使用本地OCR（默认）
OCR_PROVIDER=local
```

### 方式二：使用云端OCR服务（需要API Key）

#### 百度OCR配置

在 `.env` 文件中配置：

```bash
OCR_PROVIDER=baidu
BAIDU_OCR_API_KEY=your_api_key
BAIDU_OCR_SECRET_KEY=your_secret_key
```

获取API Key：
1. 访问 https://cloud.baidu.com/
2. 创建应用并开通文字识别服务
3. 获取API Key和Secret Key

#### 腾讯OCR配置

在 `.env` 文件中配置：

```bash
OCR_PROVIDER=tencent
TENCENT_OCR_SECRET_ID=your_secret_id
TENCENT_OCR_SECRET_KEY=your_secret_key
```

获取Secret：
1. 访问 https://cloud.tencent.com/
2. 开通文字识别服务
3. 获取Secret ID和Secret Key

#### 阿里云OCR配置

在 `.env` 文件中配置：

```bash
OCR_PROVIDER=aliyun
ALIYUN_OCR_ACCESS_KEY_ID=your_access_key_id
ALIYUN_OCR_ACCESS_KEY_SECRET=your_access_key_secret
ALIYUN_OCR_ENDPOINT=ocr.cn-shanghai.aliyuncs.com
```

获取Access Key：
1. 访问 https://www.aliyun.com/
2. 开通文字识别服务
3. 创建AccessKey获取ID和Secret

## 安装方法

### 方法一：使用PaddleOCR（本地OCR，推荐）

#### 1. 安装PaddlePaddle

```bash
# CPU版本
pip install paddlepaddle

# GPU版本（如果有CUDA）
pip install paddlepaddle-gpu
```

#### 2. 安装PaddleOCR

```bash
pip install paddleocr
```

#### 3. 首次运行会自动下载模型

首次使用时会自动下载OCR模型，可能需要一些时间。

### 方法二：使用云端OCR服务

如果选择使用云端OCR服务，需要安装对应的SDK：

**腾讯OCR：**
```bash
pip install tencentcloud-sdk-python
```

**阿里云OCR：**
```bash
pip install aliyun-python-sdk-core aliyun-python-sdk-ocr
```

**百度OCR：**
只需要 `requests` 库（已包含在依赖中）

## 验证安装

运行以下Python代码验证OCR是否可用：

```python
from app.utils.ocr_utils import get_ocr_processor

ocr_processor = get_ocr_processor()
if ocr_processor:
    print("OCR引擎初始化成功")
else:
    print("OCR引擎不可用，请检查安装")
```

## 使用说明

1. **上传图片文件**
   - 在向量数据库详情页面上传图片文件
   - 支持格式：JPG、JPEG、PNG、GIF、BMP、WEBP、TIFF、TIF

2. **自动OCR处理**
   - 系统会自动检测图片文件
   - 自动进行OCR文字识别
   - 将识别结果转换为文本并添加到向量数据库

3. **压缩包中的图片**
   - 如果压缩包中包含图片文件，也会自动进行OCR处理

## 注意事项

1. **性能考虑**
   - OCR处理需要一定时间，大图片可能需要更长时间
   - 建议图片大小不超过10MB

2. **识别准确度**
   - 清晰度高的图片识别效果更好
   - 建议使用分辨率较高的图片
   - 文字清晰、对比度高的图片识别准确度更高

3. **资源占用**
   - PaddleOCR首次运行需要下载模型（约100MB+）
   - OCR处理会占用一定的CPU/GPU资源

4. **错误处理**
   - 如果OCR识别失败，系统会记录错误日志
   - 如果未识别到文字，文件仍会被保存，但不会添加到向量数据库

## 故障排查

### 问题1：OCR处理器不可用

**可能原因：**
- 未安装OCR相关库
- 模型下载失败

**解决方法：**
- 检查是否安装了paddleocr或pytesseract
- 检查网络连接，确保可以下载模型
- 查看日志文件了解详细错误信息

### 问题2：识别结果为空

**可能原因：**
- 图片中没有文字
- 图片质量太低
- 语言包未安装（Tesseract）

**解决方法：**
- 使用更清晰的图片
- 确保安装了中文语言包（Tesseract）
- 检查图片是否包含可识别的文字

### 问题3：识别速度慢

**可能原因：**
- 图片太大
- CPU性能不足

**解决方法：**
- 压缩图片大小
- 使用GPU版本的PaddleOCR（如果有GPU）
- 考虑使用更小的OCR模型

## 依赖项

已添加到 `requirements-fastapi.txt`：

```
paddleocr>=2.7.0
pytesseract>=0.3.10
Pillow>=10.0.0
```

安装所有依赖：

```bash
pip install -r requirements-fastapi.txt
```

