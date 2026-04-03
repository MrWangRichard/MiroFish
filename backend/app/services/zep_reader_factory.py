"""
实体读取器工厂
根据配置动态选择 Zep 或 LightRAG 后端

用法：
    from app.services.zep_reader_factory import create_entity_reader
    reader = create_entity_reader()
    # 根据 GRAPH_BACKEND 配置自动返回 Zep 或 LightRAG 版本
"""

from ..config import Config


def create_entity_reader(api_key: str = None):
    """
    创建实体读取器实例

    根据 Config.GRAPH_BACKEND 配置自动选择后端：
    - "zep": 使用 Zep Cloud（原始实现）
    - "lightrag": 使用 LightRAG（本地部署，Neo4j 存储）

    Args:
        api_key: API 密钥（Zep 需要，LightRAG 忽略）

    Returns:
        实体读取器实例（ZepEntityReader 或 LightRAGEntityReader）

    Raises:
        ValueError: 配置的后端类型无效
        ImportError: 所需依赖未安装
    """
    backend = Config.GRAPH_BACKEND.lower()

    if backend == 'zep':
        # 使用 Zep Cloud 后端
        from .zep_entity_reader import ZepEntityReader
        return ZepEntityReader(api_key=api_key)

    elif backend == 'lightrag':
        # 使用 LightRAG 后端
        from .lightrag_entity_reader import LightRAGEntityReader
        return LightRAGEntityReader(api_key=api_key)

    else:
        raise ValueError(
            f"无效的 GRAPH_BACKEND 配置：'{backend}'，有效值：'zep' | 'lightrag'"
        )


# 便捷函数：获取后端类型名称
def get_backend_name() -> str:
    """获取当前配置的实体读取器后端名称"""
    return Config.GRAPH_BACKEND


# 便捷函数：检查后端是否可用
def is_backend_available(backend: str = None) -> bool:
    """
    检查指定后端是否可用

    Args:
        backend: 后端名称（默认使用配置值）

    Returns:
        True 如果后端可用且依赖已安装
    """
    backend = backend or Config.GRAPH_BACKEND

    if backend == 'zep':
        try:
            import zep_cloud
            return bool(Config.ZEP_API_KEY)
        except ImportError:
            return False

    elif backend == 'lightrag':
        try:
            import neo4j
            return bool(Config.NEO4J_URI)
        except ImportError:
            return False

    return False
