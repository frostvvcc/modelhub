"""
FastAPI 应用入口
"""
import os
# 修复 protobuf 版本兼容性问题
os.environ['PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION'] = 'python'

from app import create_app
import uvicorn

app = create_app()

if __name__ == "__main__":
    port = int(os.getenv("APP_PORT", "5000"))
    debug = os.getenv("APP_DEBUG", "true").lower() == "true"
    uvicorn.run(
        "main_fastapi:app",
        host="0.0.0.0",
        port=port,
        reload=debug,
        log_level="info"
    )

