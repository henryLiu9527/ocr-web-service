import os

class Config:
    # 从环境变量获取配置，如果不存在则使用默认值
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'dev-key-123'
    
    # 上传文件夹路径 - 在Docker环境中会被挂载到/app/uploads
    UPLOAD_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'uploads')
    
    # 文件大小限制 - 从环境变量获取或使用默认值50MB
    MAX_CONTENT_LENGTH = int(os.environ.get('MAX_CONTENT_LENGTH', 50 * 1024 * 1024))
    
    # 最大文件数限制 - 从环境变量获取或使用默认值10
    MAX_FILES = int(os.environ.get('MAX_FILES', 10))
    
    # OCR处理并发数 - 从环境变量获取或使用默认值1
    CONCURRENT_PROCESSES = int(os.environ.get('CONCURRENT_PROCESSES', 1))
