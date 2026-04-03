"""
配置管理
统一从项目根目录的 .env 文件加载配置
"""

import os
from dotenv import load_dotenv

# 加载项目根目录的 .env 文件
# 路径：MiroFish/.env (相对于 backend/app/config.py)
project_root_env = os.path.join(os.path.dirname(__file__), '../../.env')

if os.path.exists(project_root_env):
    load_dotenv(project_root_env, override=True)
else:
    # 如果根目录没有 .env，尝试加载环境变量（用于生产环境）
    load_dotenv(override=True)


class Config:
    """Flask 配置类"""

    # Flask 配置
    SECRET_KEY = os.environ.get('SECRET_KEY', 'mirofish-secret-key')
    DEBUG = os.environ.get('FLASK_DEBUG', 'True').lower() == 'true'

    # JSON 配置 - 禁用 ASCII 转义，让中文直接显示（而不是 \uXXXX 格式）
    JSON_AS_ASCII = False

    # LLM 配置（统一使用 OpenAI 格式）
    LLM_API_KEY = os.environ.get('LLM_API_KEY')
    LLM_BASE_URL = os.environ.get('LLM_BASE_URL', 'https://api.openai.com/v1')
    LLM_MODEL_NAME = os.environ.get('LLM_MODEL_NAME', 'gpt-4o-mini')

    # Zep 配置
    ZEP_API_KEY = os.environ.get('ZEP_API_KEY')

    # LightRAG 配置
    LIGHTTRAG_WORKING_DIR = os.environ.get('LIGHTTRAG_WORKING_DIR', './uploads/lightrag_storage')
    LIGHTRAG_WORKSPACE = os.environ.get('LIGHTTRAG_WORKSPACE', 'mirofish')
    LIGHTRAG_EMBEDDING_DIM = int(os.environ.get('LIGHTTRAG_EMBEDDING_DIM', '1536'))
    LIGHTTRAG_MAX_TOKEN_SIZE = int(os.environ.get('LIGHTTRAG_MAX_TOKEN_SIZE', '8192'))
    LIGHTTRAG_EMBEDDING_MODEL = os.environ.get('LIGHTTRAG_EMBEDDING_MODEL', 'text-embedding-3-small')
    # LightRAG 语言配置（用于实体和关系抽取）
    LIGHTTRAG_LANGUAGE = os.environ.get('SUMMARY_LANGUAGE', 'Chinese')

    # LightRAG 存储后端配置
    LIGHTTRAG_GRAPH_STORAGE = os.environ.get('LIGHTTRAG_GRAPH_STORAGE', 'Neo4JStorage')
    LIGHTTRAG_VECTOR_STORAGE = os.environ.get('LIGHTTRAG_VECTOR_STORAGE', 'NanoVectorDBStorage')
    LIGHTTRAG_KV_STORAGE = os.environ.get('LIGHTTRAG_KV_STORAGE', 'JsonKVStorage')
    LIGHTTRAG_DOC_STATUS_STORAGE = os.environ.get('LIGHTTRAG_DOC_STATUS_STORAGE', 'JsonDocStatusStorage')
    LIGHTTRAG_WORKSPACE = os.environ.get('LIGHTTRAG_WORKSPACE', 'mirofish')

    # Neo4j 配置
    NEO4J_URI = os.environ.get('NEO4J_URI', 'bolt://localhost:7687')
    NEO4J_USERNAME = os.environ.get('NEO4J_USERNAME', 'neo4j')
    NEO4J_PASSWORD = os.environ.get('NEO4J_PASSWORD', '')

    # 图谱后端配置（重要：选择使用 Zep 还是 LightRAG）
    # 可选值："zep" | "lightrag"
    GRAPH_BACKEND = os.environ.get('GRAPH_BACKEND', 'zep')

    # 文件上传配置
    MAX_CONTENT_LENGTH = 50 * 1024 * 1024  # 50MB
    UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), '../uploads')
    ALLOWED_EXTENSIONS = {'pdf', 'md', 'txt', 'markdown'}

    # 文本处理配置
    DEFAULT_CHUNK_SIZE = 1000  # 默认切块大小
    DEFAULT_CHUNK_OVERLAP = 50  # 默认重叠大小

    # OASIS 模拟配置
    OASIS_DEFAULT_MAX_ROUNDS = int(os.environ.get('OASIS_DEFAULT_MAX_ROUNDS', '10'))
    OASIS_SIMULATION_DATA_DIR = os.path.join(os.path.dirname(__file__), '../uploads/simulations')

    # OASIS 平台可用动作配置
    OASIS_TWITTER_ACTIONS = [
        'CREATE_POST', 'LIKE_POST', 'REPOST', 'FOLLOW', 'DO_NOTHING', 'QUOTE_POST'
    ]
    OASIS_REDDIT_ACTIONS = [
        'LIKE_POST', 'DISLIKE_POST', 'CREATE_POST', 'CREATE_COMMENT',
        'LIKE_COMMENT', 'DISLIKE_COMMENT', 'SEARCH_POSTS', 'SEARCH_USER',
        'TREND', 'REFRESH', 'DO_NOTHING', 'FOLLOW', 'MUTE'
    ]

    # Report Agent 配置
    REPORT_AGENT_MAX_TOOL_CALLS = int(os.environ.get('REPORT_AGENT_MAX_TOOL_CALLS', '5'))
    REPORT_AGENT_MAX_REFLECTION_ROUNDS = int(os.environ.get('REPORT_AGENT_MAX_REFLECTION_ROUNDS', '2'))
    REPORT_AGENT_TEMPERATURE = float(os.environ.get('REPORT_AGENT_TEMPERATURE', '0.5'))

    @classmethod
    def validate(cls):
        """验证必要配置"""
        errors = []
        if not cls.LLM_API_KEY:
            errors.append("LLM_API_KEY 未配置")
        # ZEP 可选（使用 LightRAG 时不需要）
        # if not cls.ZEP_API_KEY:
        #     errors.append("ZEP_API_KEY 未配置")
        # LightRAG 可选（使用本地存储时不需要额外配置）
        return errors

