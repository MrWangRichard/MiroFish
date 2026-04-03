"""
图谱构建服务工厂
根据配置动态选择 Zep 或 LightRAG 后端

用法：
    from app.services.graph_builder_factory import create_graph_builder
    service = create_graph_builder()
    # 根据 GRAPH_BACKEND 配置自动返回 Zep 或 LightRAG 版本
"""

from ..config import Config


def create_graph_builder(api_key: str = None, backend: str = None):
    """
    创建图谱构建服务实例

    根据 Config.GRAPH_BACKEND 配置自动选择后端：
    - "zep": 使用 Zep Cloud（原始实现）
    - "lightrag": 使用 LightRAG（本地部署，Neo4j 存储）

    Args:
        api_key: API 密钥（Zep 需要，LightRAG 忽略）
        backend: 可选的后端覆盖值；未提供时使用 Config.GRAPH_BACKEND

    Returns:
        GraphBuilderService 实例（Zep 版本或 LightRAG 版本）

    Raises:
        ValueError: 配置的后端类型无效
        ImportError: 所需依赖未安装
    """
    backend = (backend or Config.GRAPH_BACKEND).lower()

    if backend == 'zep':
        # 使用 Zep Cloud 后端
        from .graph_builder import GraphBuilderService as ZepGraphBuilder
        return ZepGraphBuilder(api_key=api_key)

    elif backend == 'lightrag':
        # 使用 LightRAG 后端
        from .graph_builder_lightrag import GraphBuilderService as LightRAGGraphBuilder
        return LightRAGGraphBuilder(api_key=api_key)

    else:
        raise ValueError(
            f"无效的 GRAPH_BACKEND 配置：'{backend}'，有效值：'zep' | 'lightrag'"
        )


# 便捷函数：获取后端类型名称
def get_backend_name() -> str:
    """获取当前配置的图谱后端名称"""
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
            from lightrag import LightRAG
            return True
        except ImportError:
            return False

    return False
