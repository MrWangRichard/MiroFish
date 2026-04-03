"""
图谱相关 API 路由
采用项目上下文机制，服务端持久化状态

注意：此文件已修改为使用工厂模式，支持 Zep 和 LightRAG 两种后端
通过 Config.GRAPH_BACKEND 配置切换：
- "zep": 使用 Zep Cloud（原始实现）
- "lightrag": 使用 LightRAG（本地部署，Neo4j 存储）
"""

import os
import threading
import traceback
from datetime import datetime
from flask import request, jsonify

from . import graph_bp
from ..config import Config
from ..services.ontology_generator import OntologyGenerator
from ..services.graph_builder_factory import create_graph_builder, get_backend_name
from ..services.graph_view_service import GraphViewService
from ..services.text_processor import TextProcessor
from ..utils.file_parser import FileParser
from ..utils.logger import get_logger
from ..models.task import TaskManager, TaskStatus
from ..models.project import ProjectManager, ProjectStatus

# 获取日志器
logger = get_logger('mirofish.api')


def allowed_file(filename: str) -> bool:
    """检查文件扩展名是否允许"""
    if not filename or '.' not in filename:
        return False
    ext = os.path.splitext(filename)[1].lower().lstrip('.')
    return ext in Config.ALLOWED_EXTENSIONS


def _build_graph_task_type(graph_name: str) -> str:
    """统一图谱构建任务名称，便于恢复时复用。"""
    return f"构建图谱：{graph_name or 'MiroFish Graph'}"


def _build_graph_task_metadata(project_id: str, graph_name: str, backend_name: str) -> dict:
    """统一图谱构建任务元数据。"""
    return {
        "task_kind": "graph_build",
        "project_id": project_id,
        "graph_name": graph_name,
        "graph_backend": backend_name,
    }


def _parse_iso_datetime(value: str):
    """解析 ISO 时间字符串，失败时返回 None。"""
    if not value:
        return None

    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _restore_graph_task_from_project(task_id: str):
    """
    当任务缓存丢失时，根据项目状态恢复图谱构建任务。

    返回 Task 对象；若无法恢复则返回 None。
    """
    project = ProjectManager.find_project_by_graph_task_id(task_id)
    if not project:
        return None

    task_manager = TaskManager()
    graph_name = project.name or "MiroFish Graph"
    backend_name = project.graph_backend or get_backend_name()
    metadata = _build_graph_task_metadata(project.project_id, graph_name, backend_name)
    created_at = _parse_iso_datetime(project.created_at)
    updated_at = _parse_iso_datetime(project.updated_at)

    def restore_completed(graph_result: dict, message: str = "图谱构建完成"):
        project.status = ProjectStatus.GRAPH_COMPLETED
        project.error = None
        ProjectManager.save_project(project)
        return task_manager.restore_task(
            task_id=task_id,
            task_type=_build_graph_task_type(graph_name),
            status=TaskStatus.COMPLETED,
            progress=100,
            message=message,
            result=graph_result,
            metadata=metadata,
            created_at=created_at,
            updated_at=updated_at,
        )

    def restore_failed(error_message: str):
        project.status = ProjectStatus.FAILED
        project.error = error_message
        ProjectManager.save_project(project)
        return task_manager.restore_task(
            task_id=task_id,
            task_type=_build_graph_task_type(graph_name),
            status=TaskStatus.FAILED,
            progress=95 if project.graph_id else 0,
            message=f"构建失败：{error_message}",
            error=error_message,
            metadata=metadata,
            created_at=created_at,
            updated_at=updated_at,
        )

    if project.status == ProjectStatus.GRAPH_COMPLETED and project.graph_id:
        graph_result = {
            "project_id": project.project_id,
            "graph_id": project.graph_id,
        }

        try:
            builder = create_graph_builder(api_key=Config.ZEP_API_KEY, backend=backend_name)
            graph_data = builder.get_graph_data(project.graph_id)
            graph_result.update({
                "node_count": graph_data.get("node_count", 0),
                "edge_count": graph_data.get("edge_count", 0),
            })
        except Exception as exc:
            logger.warning(f"恢复已完成图谱任务时读取图谱统计失败：task_id={task_id}, error={exc}")

        return restore_completed(graph_result, message="图谱已构建完成")

    if project.status == ProjectStatus.FAILED:
        return restore_failed(project.error or "图谱构建失败")

    if project.status == ProjectStatus.GRAPH_BUILDING:
        if project.graph_id:
            try:
                builder = create_graph_builder(api_key=Config.ZEP_API_KEY, backend=backend_name)
                graph_data = builder.get_graph_data(project.graph_id)
                node_count = graph_data.get("node_count", 0)
                edge_count = graph_data.get("edge_count", 0)

                if node_count <= 0 and edge_count <= 0:
                    raise ValueError("图谱数据为空，无法确认构建已经完成")

                graph_result = {
                    "project_id": project.project_id,
                    "graph_id": project.graph_id,
                    "node_count": node_count,
                    "edge_count": edge_count,
                }
                return restore_completed(graph_result, message="图谱构建已恢复为完成状态")
            except Exception as exc:
                logger.warning(
                    f"图谱任务恢复时未能确认构建完成：task_id={task_id}, "
                    f"project_id={project.project_id}, graph_id={project.graph_id}, error={exc}"
                )

        return restore_failed("图谱构建任务状态已丢失，请重新构建")

    return task_manager.restore_task(
        task_id=task_id,
        task_type=_build_graph_task_type(graph_name),
        status=TaskStatus.FAILED,
        progress=0,
        message="构建失败：项目当前不处于图谱构建状态",
        error="项目当前不处于图谱构建状态",
        metadata=metadata,
        created_at=created_at,
        updated_at=updated_at,
    )


# ============== 项目管理接口 ==============

@graph_bp.route('/project/<project_id>', methods=['GET'])
def get_project(project_id: str):
    """
    获取项目详情
    """
    project = ProjectManager.get_project(project_id)

    if not project:
        return jsonify({
            "success": False,
            "error": f"项目不存在：{project_id}"
        }), 404

    return jsonify({
        "success": True,
        "data": project.to_dict()
    })


@graph_bp.route('/project/list', methods=['GET'])
def list_projects():
    """
    列出所有项目
    """
    limit = request.args.get('limit', 50, type=int)
    projects = ProjectManager.list_projects(limit=limit)

    return jsonify({
        "success": True,
        "data": [p.to_dict() for p in projects],
        "count": len(projects)
    })


@graph_bp.route('/project/<project_id>', methods=['DELETE'])
def delete_project(project_id: str):
    """
    删除项目
    """
    success = ProjectManager.delete_project(project_id)

    if not success:
        return jsonify({
            "success": False,
            "error": f"项目不存在或删除失败：{project_id}"
        }), 404

    return jsonify({
        "success": True,
        "message": f"项目已删除：{project_id}"
    })


@graph_bp.route('/project/<project_id>/reset', methods=['POST'])
def reset_project(project_id: str):
    """
    重置项目状态（用于重新构建图谱）
    """
    project = ProjectManager.get_project(project_id)

    if not project:
        return jsonify({
            "success": False,
            "error": f"项目不存在：{project_id}"
        }), 404

    # 重置到本体已生成状态
    if project.ontology:
        project.status = ProjectStatus.ONTOLOGY_GENERATED
    else:
        project.status = ProjectStatus.CREATED

    project.graph_id = None
    project.graph_build_task_id = None
    project.graph_backend = None
    project.error = None
    ProjectManager.save_project(project)

    return jsonify({
        "success": True,
        "message": f"项目已重置：{project_id}",
        "data": project.to_dict()
    })


# ============== 接口 1：上传文件并生成本体 ==============

@graph_bp.route('/ontology/generate', methods=['POST'])
def generate_ontology():
    """
    接口 1：上传文件，分析生成本体定义

    请求方式：multipart/form-data

    参数：
        files: 上传的文件（PDF/MD/TXT），可多个
        simulation_requirement: 模拟需求描述（必填）
        project_name: 项目名称（可选）
        additional_context: 额外说明（可选）

    返回：
        {
            "success": true,
            "data": {
                "project_id": "proj_xxxx",
                "ontology": {
                    "entity_types": [...],
                    "edge_types": [...],
                    "analysis_summary": "..."
                },
                "files": [...],
                "total_text_length": 12345
            }
        }
    """
    try:
        logger.info("=== 开始生成本体定义 ===")

        # 获取参数
        simulation_requirement = request.form.get('simulation_requirement', '')
        project_name = request.form.get('project_name', 'Unnamed Project')
        additional_context = request.form.get('additional_context', '')

        logger.debug(f"项目名称：{project_name}")
        logger.debug(f"模拟需求：{simulation_requirement[:100]}...")

        if not simulation_requirement:
            return jsonify({
                "success": False,
                "error": "请提供模拟需求描述 (simulation_requirement)"
            }), 400

        # 获取上传的文件
        uploaded_files = request.files.getlist('files')
        if not uploaded_files or all(not f.filename for f in uploaded_files):
            return jsonify({
                "success": False,
                "error": "请至少上传一个文档文件"
            }), 400

        # 创建项目
        project = ProjectManager.create_project(name=project_name)
        project.simulation_requirement = simulation_requirement
        logger.info(f"创建项目：{project.project_id}")

        # 保存文件并提取文本
        document_texts = []
        all_text = ""

        for file in uploaded_files:
            if file and file.filename and allowed_file(file.filename):
                # 保存文件到项目目录
                file_info = ProjectManager.save_file_to_project(
                    project.project_id,
                    file,
                    file.filename
                )
                project.files.append({
                    "filename": file_info["original_filename"],
                    "size": file_info["size"]
                })

                # 提取文本
                text = FileParser.extract_text(file_info["path"])
                text = TextProcessor.preprocess_text(text)
                document_texts.append(text)
                all_text += f"\n\n=== {file_info['original_filename']} ===\n{text}"

        if not document_texts:
            ProjectManager.delete_project(project.project_id)
            return jsonify({
                "success": False,
                "error": "没有成功处理任何文档，请检查文件格式"
            }), 400

        # 保存提取的文本
        project.total_text_length = len(all_text)
        ProjectManager.save_extracted_text(project.project_id, all_text)
        logger.info(f"文本提取完成，共 {len(all_text)} 字符")

        # 生成本体
        logger.info("调用 LLM 生成本体定义...")
        generator = OntologyGenerator()
        ontology = generator.generate(
            document_texts=document_texts,
            simulation_requirement=simulation_requirement,
            additional_context=additional_context if additional_context else None
        )

        # 保存本体到项目
        entity_count = len(ontology.get("entity_types", []))
        edge_count = len(ontology.get("edge_types", []))
        logger.info(f"本体生成完成：{entity_count} 个实体类型，{edge_count} 个关系类型")

        project.ontology = {
            "entity_types": ontology.get("entity_types", []),
            "edge_types": ontology.get("edge_types", [])
        }
        project.analysis_summary = ontology.get("analysis_summary", "")
        project.status = ProjectStatus.ONTOLOGY_GENERATED
        ProjectManager.save_project(project)
        logger.info(f"=== 本体生成完成 === 项目 ID: {project.project_id}")

        return jsonify({
            "success": True,
            "data": {
                "project_id": project.project_id,
                "project_name": project.name,
                "ontology": project.ontology,
                "analysis_summary": project.analysis_summary,
                "files": project.files,
                "total_text_length": project.total_text_length
            }
        })

    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


# ============== 接口 2：构建图谱 ==============

@graph_bp.route('/build', methods=['POST'])
def build_graph():
    """
    接口 2：根据 project_id 构建图谱

    请求（JSON）：
        {
            "project_id": "proj_xxxx",  // 必填，来自接口 1
            "graph_name": "图谱名称",    // 可选
            "chunk_size": 500,          // 可选，默认 500
            "chunk_overlap": 50         // 可选，默认 50
        }

    返回：
        {
            "success": true,
            "data": {
                "project_id": "proj_xxxx",
                "task_id": "task_xxxx",
                "message": "图谱构建任务已启动"
            }
        }
    """
    try:
        logger.info("=== 开始构建图谱 ===")

        # 检查配置
        errors = []
        backend_name = get_backend_name()
        logger.info(f"当前图谱后端：{backend_name}")

        if backend_name == 'zep' and not Config.ZEP_API_KEY:
            errors.append("ZEP_API_KEY 未配置")
        if errors:
            logger.error(f"配置错误：{errors}")
            return jsonify({
                "success": False,
                "error": "配置错误：" + "; ".join(errors)
            }), 500

        # 解析请求
        data = request.get_json() or {}
        project_id = data.get('project_id')
        logger.debug(f"请求参数：project_id={project_id}")

        if not project_id:
            return jsonify({
                "success": False,
                "error": "请提供 project_id"
            }), 400

        # 获取项目
        project = ProjectManager.get_project(project_id)
        if not project:
            return jsonify({
                "success": False,
                "error": f"项目不存在：{project_id}"
            }), 404

        # 检查项目状态
        force = data.get('force', False)  # 强制重新构建

        if project.status == ProjectStatus.CREATED:
            return jsonify({
                "success": False,
                "error": "项目尚未生成本体，请先调用 /ontology/generate"
            }), 400

        if project.status == ProjectStatus.GRAPH_BUILDING and not force:
            return jsonify({
                "success": False,
                "error": "图谱正在构建中，请勿重复提交。如需强制重建，请添加 force: true",
                "task_id": project.graph_build_task_id
            }), 400

        # 如果强制重建，重置状态
        if force and project.status in [ProjectStatus.GRAPH_BUILDING, ProjectStatus.FAILED, ProjectStatus.GRAPH_COMPLETED]:
            project.status = ProjectStatus.ONTOLOGY_GENERATED
            project.graph_id = None
            project.graph_build_task_id = None
            project.graph_backend = None
            project.error = None

        # 获取配置
        graph_name = data.get('graph_name', project.name or 'MiroFish Graph')
        chunk_size = data.get('chunk_size', project.chunk_size or Config.DEFAULT_CHUNK_SIZE)
        chunk_overlap = data.get('chunk_overlap', project.chunk_overlap or Config.DEFAULT_CHUNK_OVERLAP)

        # 更新项目配置
        project.chunk_size = chunk_size
        project.chunk_overlap = chunk_overlap

        # 获取提取的文本
        text = ProjectManager.get_extracted_text(project_id)
        if not text:
            return jsonify({
                "success": False,
                "error": "未找到提取的文本内容"
            }), 400

        # 获取本体
        ontology = project.ontology
        if not ontology:
            return jsonify({
                "success": False,
                "error": "未找到本体定义"
            }), 400

        # 创建异步任务
        task_manager = TaskManager()
        graph_task_metadata = _build_graph_task_metadata(project_id, graph_name, backend_name)
        task_id = task_manager.create_task(
            _build_graph_task_type(graph_name),
            metadata=graph_task_metadata
        )
        logger.info(f"创建图谱构建任务：task_id={task_id}, project_id={project_id}")

        # 更新项目状态
        project.status = ProjectStatus.GRAPH_BUILDING
        project.graph_build_task_id = task_id
        project.graph_backend = backend_name
        project.error = None
        ProjectManager.save_project(project)

        # 启动后台任务
        def build_task():
            backend_name = get_backend_name()
            build_logger = get_logger('mirofish.build')
            try:
                build_logger.info(f"[{task_id}] 开始构建图谱 (后端：{backend_name})...")
                task_manager.update_task(
                    task_id,
                    status=TaskStatus.PROCESSING,
                    message=f"初始化图谱构建服务 ({backend_name})...",
                    progress=5
                )

                # 创建图谱构建服务（使用工厂选择后端）
                builder = create_graph_builder(api_key=Config.ZEP_API_KEY)

                # 分块
                task_manager.update_task(
                    task_id,
                    message="文本分块中...",
                    progress=10
                )
                chunks = TextProcessor.split_text(
                    text,
                    chunk_size=chunk_size,
                    overlap=chunk_overlap
                )
                total_chunks = len(chunks)

                # 创建图谱
                task_manager.update_task(
                    task_id,
                    message=f"创建图谱 ({backend_name})...",
                    progress=15
                )
                graph_id = builder.create_graph(name=graph_name)

                # 更新项目的 graph_id
                project.graph_id = graph_id
                ProjectManager.save_project(project)

                # 设置本体
                task_manager.update_task(
                    task_id,
                    message="设置本体定义...",
                    progress=20
                )
                builder.set_ontology(graph_id, ontology)

                # 添加文本（progress_callback 签名是 (msg, progress_ratio)）
                def add_progress_callback(msg, progress_ratio):
                    progress = 20 + int(progress_ratio * 40)  # 20% - 60%
                    task_manager.update_task(
                        task_id,
                        message=msg,
                        progress=progress
                    )

                task_manager.update_task(
                    task_id,
                    message=f"开始添加 {total_chunks} 个文本块...",
                    progress=20
                )

                episode_uuids = builder.add_text_batches(
                    graph_id,
                    chunks,
                    batch_size=3,
                    progress_callback=add_progress_callback
                )

                # 等待处理完成
                task_manager.update_task(
                    task_id,
                    message="等待图谱处理完成...",
                    progress=60
                )

                def wait_progress_callback(msg, progress_ratio):
                    progress = 60 + int(progress_ratio * 30)  # 60% - 90%
                    task_manager.update_task(
                        task_id,
                        message=msg,
                        progress=progress
                    )

                builder._wait_for_episodes(episode_uuids, wait_progress_callback)

                # 获取图谱数据
                task_manager.update_task(
                    task_id,
                    message="获取图谱数据...",
                    progress=95
                )
                graph_data = builder.get_graph_data(graph_id)

                # 更新项目状态
                project.status = ProjectStatus.GRAPH_COMPLETED
                project.error = None
                ProjectManager.save_project(project)

                node_count = graph_data.get("node_count", 0)
                edge_count = graph_data.get("edge_count", 0)
                build_logger.info(f"[{task_id}] 图谱构建完成：graph_id={graph_id}, 节点={node_count}, 边={edge_count}")

                # 完成
                task_manager.update_task(
                    task_id,
                    status=TaskStatus.COMPLETED,
                    message="图谱构建完成",
                    progress=100,
                    result={
                        "project_id": project_id,
                        "graph_id": graph_id,
                        "node_count": node_count,
                        "edge_count": edge_count,
                        "chunk_count": total_chunks
                    }
                )

            except Exception as e:
                # 更新项目状态为失败
                build_logger.error(f"[{task_id}] 图谱构建失败：{str(e)}")
                build_logger.debug(traceback.format_exc())

                project.status = ProjectStatus.FAILED
                project.error = str(e)
                ProjectManager.save_project(project)

                task_manager.update_task(
                    task_id,
                    status=TaskStatus.FAILED,
                    message=f"构建失败：{str(e)}",
                    error=traceback.format_exc()
                )

        # 启动后台线程
        thread = threading.Thread(target=build_task, daemon=True)
        thread.start()

        return jsonify({
            "success": True,
            "data": {
                "project_id": project_id,
                "task_id": task_id,
                "message": f"图谱构建任务已启动 (后端：{backend_name})，请通过 /task/{{task_id}} 查询进度"
            }
        })

    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


# ============== 任务查询接口 ==============

@graph_bp.route('/task/<task_id>', methods=['GET'])
def get_task(task_id: str):
    """
    查询任务状态
    """
    task_manager = TaskManager()
    task = task_manager.get_task(task_id)

    if not task:
        task = _restore_graph_task_from_project(task_id)

    if not task:
        return jsonify({
            "success": False,
            "error": f"任务不存在：{task_id}"
        }), 404

    return jsonify({
        "success": True,
        "data": task.to_dict()
    })


@graph_bp.route('/tasks', methods=['GET'])
def list_tasks():
    """
    列出所有任务
    """
    tasks = TaskManager().list_tasks()

    return jsonify({
        "success": True,
        "data": tasks,
        "count": len(tasks)
    })


# ============== 图谱数据接口 ==============

@graph_bp.route('/entities/<graph_id>', methods=['GET'])
def get_graph_entities(graph_id: str):
    """
    获取图谱中的实体候选列表，支持按 uuid 或 name 搜索。
    """
    try:
        query = request.args.get('q', '', type=str)
        limit = request.args.get('limit', 100, type=int)
        limit = max(1, min(limit, 500))

        view_service = GraphViewService(api_key=Config.ZEP_API_KEY)
        result = view_service.get_entity_options(
            graph_id=graph_id,
            query=query,
            limit=limit,
        )

        return jsonify({
            "success": True,
            "data": result
        })

    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


@graph_bp.route('/data/<graph_id>', methods=['GET'])
def get_graph_data(graph_id: str):
    """
    获取图谱数据（节点和边）
    """
    try:
        limit = request.args.get('limit', default=None, type=int)

        view_service = GraphViewService(api_key=Config.ZEP_API_KEY)
        if limit is not None and limit > 0:
            graph_data = view_service.get_graph_view(graph_id=graph_id, limit=limit)
        else:
            builder = create_graph_builder(api_key=Config.ZEP_API_KEY)
            graph_data = builder.get_graph_data(graph_id)
            graph_data["display_node_count"] = len(graph_data.get("nodes", []) or [])
            graph_data["display_edge_count"] = len(graph_data.get("edges", []) or [])
            graph_data["view_mode"] = "full"
            graph_data["focus_node_uuid"] = None

        return jsonify({
            "success": True,
            "data": graph_data
        })

    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


@graph_bp.route('/data/<graph_id>/focus', methods=['GET'])
def get_focus_graph_data(graph_id: str):
    """
    获取围绕单个实体的一跳邻域子图。
    """
    try:
        entity_uuid = request.args.get('entity_uuid', '', type=str).strip()
        hops = request.args.get('hops', 1, type=int)
        per_hop_limit = request.args.get('per_hop_limit', 20, type=int)
        total_node_limit = request.args.get('total_node_limit', 150, type=int)

        if not entity_uuid:
            return jsonify({
                "success": False,
                "error": "请提供 entity_uuid"
            }), 400

        view_service = GraphViewService(api_key=Config.ZEP_API_KEY)
        graph_data = view_service.get_focus_graph_view(
            graph_id=graph_id,
            entity_uuid=entity_uuid,
            hops=hops,
            per_hop_limit=per_hop_limit,
            total_node_limit=total_node_limit,
        )

        if not graph_data:
            return jsonify({
                "success": False,
                "error": f"实体不存在：{entity_uuid}"
            }), 404

        return jsonify({
            "success": True,
            "data": graph_data
        })

    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


@graph_bp.route('/data/<graph_id>/expand', methods=['GET'])
def expand_graph_data(graph_id: str):
    """
    鎸夐渶澧炰噺鎵╁睍瀹炰綋閭诲煙瀛愬浘銆?
    """
    try:
        entity_uuid = request.args.get('entity_uuid', '', type=str).strip()
        hops = request.args.get('hops', 1, type=int)
        per_hop_limit = request.args.get('per_hop_limit', 20, type=int)
        total_node_limit = request.args.get('total_node_limit', 150, type=int)
        exclude_node_uuids_raw = request.args.get('exclude_node_uuids', '', type=str)

        if not entity_uuid:
            return jsonify({
                "success": False,
                "error": "璇锋彁渚?entity_uuid"
            }), 400

        exclude_node_uuids = [
            item.strip()
            for item in (exclude_node_uuids_raw or '').split(',')
            if item.strip()
        ]

        view_service = GraphViewService(api_key=Config.ZEP_API_KEY)
        graph_data = view_service.get_expand_graph_view(
            graph_id=graph_id,
            entity_uuid=entity_uuid,
            hops=hops,
            per_hop_limit=per_hop_limit,
            total_node_limit=total_node_limit,
            exclude_node_uuids=exclude_node_uuids,
        )

        if not graph_data:
            return jsonify({
                "success": False,
                "error": f"瀹炰綋涓嶅瓨鍦細{entity_uuid}"
            }), 404

        return jsonify({
            "success": True,
            "data": graph_data
        })

    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


@graph_bp.route('/delete/<graph_id>', methods=['DELETE'])
def delete_graph(graph_id: str):
    """
    删除图谱
    """
    try:
        # 使用工厂创建服务（自动选择后端）
        builder = create_graph_builder(api_key=Config.ZEP_API_KEY)
        builder.delete_graph(graph_id)

        return jsonify({
            "success": True,
            "message": f"图谱已删除：{graph_id}"
        })

    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500
