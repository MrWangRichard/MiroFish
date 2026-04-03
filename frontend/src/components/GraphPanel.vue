<template>
  <div class="graph-panel">
    <div class="panel-header">
      <div class="header-primary">
        <span class="panel-title">Graph Relationship Visualization</span>
        <span v-if="currentGraphData" class="panel-subtitle">{{ graphSummaryText }}</span>
      </div>
      <div class="header-controls">
        <div class="entity-controls">
          <select
            v-model="selectedEntityUuid"
            class="entity-select"
            :disabled="!graphId || entitySearchLoading || focusLoading"
            @change="handleEntitySelect"
          >
            <option value="">Select entity</option>
            <option v-for="entity in entityOptions" :key="entity.uuid" :value="entity.uuid">
              {{ formatEntityOption(entity) }}
            </option>
          </select>
          <input
            v-model="entitySearchInput"
            class="entity-search-input"
            type="text"
            placeholder="Search entity by id or name"
            :disabled="!graphId || focusLoading"
            @keydown.enter.prevent="handleSearch"
          />
          <button class="tool-btn compact" @click="handleSearch" :disabled="!graphId || focusLoading" title="搜索实体">
            <span>{{ focusLoading ? '...' : 'Search' }}</span>
          </button>
          <button class="tool-btn ghost" @click="resetToDefaultView" :disabled="!props.graphData || focusLoading" title="恢复默认视图">
            <span>Reset</span>
          </button>
        </div>
        <div class="header-tools">
          <button class="tool-btn" @click="$emit('refresh')" :disabled="isPanelLoading" title="刷新图谱">
            <span class="icon-refresh" :class="{ 'spinning': isPanelLoading }">?</span>
            <span class="btn-text">Refresh</span>
          </button>
          <button class="tool-btn" @click="$emit('toggle-maximize')" title="最大化/还原">
            <span class="icon-maximize">?</span>
          </button>
        </div>
      </div>
    </div>

    <div v-if="controlMessage" class="search-status">
      {{ controlMessage }}
    </div>
    
    <div class="graph-container" ref="graphContainer">
      <!-- 图谱可视化 -->
      <div v-if="currentGraphData" class="graph-view">
        <svg ref="graphSvg" class="graph-svg"></svg>
        
        <!-- 构建中/模拟中提示 -->
        <div v-if="currentPhase === 1 || isSimulating" class="graph-building-hint">
          <div class="memory-icon-wrapper">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="memory-icon">
              <path d="M9.5 2A2.5 2.5 0 0 1 12 4.5v15a2.5 2.5 0 0 1-4.96.44 2.5 2.5 0 0 1-2.96-3.08 3 3 0 0 1-.34-5.58 2.5 2.5 0 0 1 1.32-4.24 2.5 2.5 0 0 1 4.44-4.04z" />
              <path d="M14.5 2A2.5 2.5 0 0 0 12 4.5v15a2.5 2.5 0 0 0 4.96.44 2.5 2.5 0 0 0 2.96-3.08 3 3 0 0 0 .34-5.58 2.5 2.5 0 0 0-1.32-4.24 2.5 2.5 0 0 0-4.44-4.04z" />
            </svg>
          </div>
          {{ isSimulating ? 'GraphRAG长短期记忆实时更新中' : '实时更新中...' }}
        </div>
        
        <!-- 模拟结束后的提示 -->
        <div v-if="showSimulationFinishedHint" class="graph-building-hint finished-hint">
          <div class="hint-icon-wrapper">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="hint-icon">
              <circle cx="12" cy="12" r="10"></circle>
              <line x1="12" y1="16" x2="12" y2="12"></line>
              <line x1="12" y1="8" x2="12.01" y2="8"></line>
            </svg>
          </div>
          <span class="hint-text">还有少量内容处理中，建议稍后手动刷新图谱</span>
          <button class="hint-close-btn" @click="dismissFinishedHint" title="关闭提示">
            <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2">
              <line x1="18" y1="6" x2="6" y2="18"></line>
              <line x1="6" y1="6" x2="18" y2="18"></line>
            </svg>
          </button>
        </div>
        
        <!-- 节点/边详情面板 -->
        <div v-if="selectedItem" class="detail-panel">
          <div class="detail-panel-header">
            <span class="detail-title">{{ selectedItem.type === 'node' ? 'Node Details' : 'Relationship' }}</span>
            <span v-if="selectedItem.type === 'node'" class="detail-type-badge" :style="{ background: selectedItem.color, color: '#fff' }">
              {{ selectedItem.entityType }}
            </span>
            <button class="detail-close" @click="closeDetailPanel">×</button>
          </div>
          
          <!-- 节点详情 -->
          <div v-if="selectedItem.type === 'node'" class="detail-content">
            <div class="detail-row">
              <span class="detail-label">Name:</span>
              <span class="detail-value">{{ selectedItem.data.name }}</span>
            </div>
            <div class="detail-row">
              <span class="detail-label">UUID:</span>
              <span class="detail-value uuid-text">{{ selectedItem.data.uuid }}</span>
            </div>
            <div class="detail-row" v-if="selectedItem.data.created_at">
              <span class="detail-label">Created:</span>
              <span class="detail-value">{{ formatDateTime(selectedItem.data.created_at) }}</span>
            </div>
            <div class="detail-row" v-if="typeof selectedItem.data.degree === 'number'">
              <span class="detail-label">Connections:</span>
              <span class="detail-value">
                {{ selectedItem.data.visible_degree ?? 0 }}/{{ selectedItem.data.degree }} shown
              </span>
            </div>
            <div class="detail-row" v-if="typeof selectedItem.data.distance === 'number'">
              <span class="detail-label">Distance:</span>
              <span class="detail-value">{{ selectedItem.data.distance }} hop{{ selectedItem.data.distance === 1 ? '' : 's' }}</span>
            </div>

            <div class="detail-actions">
              <button
                class="detail-action-btn"
                :disabled="!canExpandSelectedNode || focusLoading"
                @click="expandSelectedNode"
              >
                {{ focusLoading ? '...' : 'Expand 1 Hop' }}
              </button>
              <span v-if="expandedAnchorLabel" class="detail-action-context">
                Anchor: {{ expandedAnchorLabel }}
              </span>
              <span v-if="selectedItem.data.has_more_neighbors === false" class="detail-action-hint">
                No more unseen neighbors
              </span>
            </div>
            
            <!-- Properties -->
            <div class="detail-section" v-if="selectedItem.data.attributes && Object.keys(selectedItem.data.attributes).length > 0">
              <div class="section-title">Properties:</div>
              <div class="properties-list">
                <div v-for="(value, key) in selectedItem.data.attributes" :key="key" class="property-item">
                  <span class="property-key">{{ key }}:</span>
                  <span class="property-value">{{ value || 'None' }}</span>
                </div>
              </div>
            </div>
            
            <!-- Summary -->
            <div class="detail-section" v-if="selectedItem.data.summary">
              <div class="section-title">Summary:</div>
              <div class="summary-text">{{ selectedItem.data.summary }}</div>
            </div>
            
            <!-- Labels -->
            <div class="detail-section" v-if="selectedItem.data.labels && selectedItem.data.labels.length > 0">
              <div class="section-title">Labels:</div>
              <div class="labels-list">
                <span v-for="label in selectedItem.data.labels" :key="label" class="label-tag">
                  {{ label }}
                </span>
              </div>
            </div>
          </div>
          
          <!-- 边详情 -->
          <div v-else class="detail-content">
            <!-- 自环组详情 -->
            <template v-if="selectedItem.data.isSelfLoopGroup">
              <div class="edge-relation-header self-loop-header">
                {{ selectedItem.data.source_name }} - Self Relations
                <span class="self-loop-count">{{ selectedItem.data.selfLoopCount }} items</span>
              </div>
              
              <div class="self-loop-list">
                <div 
                  v-for="(loop, idx) in selectedItem.data.selfLoopEdges" 
                  :key="loop.uuid || idx" 
                  class="self-loop-item"
                  :class="{ expanded: expandedSelfLoops.has(loop.uuid || idx) }"
                >
                  <div 
                    class="self-loop-item-header"
                    @click="toggleSelfLoop(loop.uuid || idx)"
                  >
                    <span class="self-loop-index">#{{ idx + 1 }}</span>
                    <span class="self-loop-name">{{ loop.name || loop.fact_type || 'RELATED' }}</span>
                    <span class="self-loop-toggle">{{ expandedSelfLoops.has(loop.uuid || idx) ? '?' : '+' }}</span>
                  </div>
                  
                  <div class="self-loop-item-content" v-show="expandedSelfLoops.has(loop.uuid || idx)">
                    <div class="detail-row" v-if="loop.uuid">
                      <span class="detail-label">UUID:</span>
                      <span class="detail-value uuid-text">{{ loop.uuid }}</span>
                    </div>
                    <div class="detail-row" v-if="loop.fact">
                      <span class="detail-label">Fact:</span>
                      <span class="detail-value fact-text">{{ loop.fact }}</span>
                    </div>
                    <div class="detail-row" v-if="loop.fact_type">
                      <span class="detail-label">Type:</span>
                      <span class="detail-value">{{ loop.fact_type }}</span>
                    </div>
                    <div class="detail-row" v-if="loop.created_at">
                      <span class="detail-label">Created:</span>
                      <span class="detail-value">{{ formatDateTime(loop.created_at) }}</span>
                    </div>
                    <div v-if="loop.episodes && loop.episodes.length > 0" class="self-loop-episodes">
                      <span class="detail-label">Episodes:</span>
                      <div class="episodes-list compact">
                        <span v-for="ep in loop.episodes" :key="ep" class="episode-tag small">{{ ep }}</span>
                      </div>
                    </div>
                  </div>
                </div>
              </div>
            </template>
            
            <!-- 普通边详情 -->
            <template v-else>
              <div class="edge-relation-header">
                {{ selectedItem.data.source_name }} → {{ selectedItem.data.name || 'RELATED_TO' }} → {{ selectedItem.data.target_name }}
              </div>
              
              <div class="detail-row">
                <span class="detail-label">UUID:</span>
                <span class="detail-value uuid-text">{{ selectedItem.data.uuid }}</span>
              </div>
              <div class="detail-row">
                <span class="detail-label">Label:</span>
                <span class="detail-value">{{ selectedItem.data.name || 'RELATED_TO' }}</span>
              </div>
              <div class="detail-row">
                <span class="detail-label">Type:</span>
                <span class="detail-value">{{ selectedItem.data.fact_type || 'Unknown' }}</span>
              </div>
              <div class="detail-row" v-if="selectedItem.data.fact">
                <span class="detail-label">Fact:</span>
                <span class="detail-value fact-text">{{ selectedItem.data.fact }}</span>
              </div>
              
              <!-- Episodes -->
              <div class="detail-section" v-if="selectedItem.data.episodes && selectedItem.data.episodes.length > 0">
                <div class="section-title">Episodes:</div>
                <div class="episodes-list">
                  <span v-for="ep in selectedItem.data.episodes" :key="ep" class="episode-tag">
                    {{ ep }}
                  </span>
                </div>
              </div>
              
              <div class="detail-row" v-if="selectedItem.data.created_at">
                <span class="detail-label">Created:</span>
                <span class="detail-value">{{ formatDateTime(selectedItem.data.created_at) }}</span>
              </div>
              <div class="detail-row" v-if="selectedItem.data.valid_at">
                <span class="detail-label">Valid From:</span>
                <span class="detail-value">{{ formatDateTime(selectedItem.data.valid_at) }}</span>
              </div>
            </template>
          </div>
        </div>
      </div>
      
      <!-- 加载状态 -->
      <div v-else-if="isPanelLoading" class="graph-state">
        <div class="loading-spinner"></div>
        <p>图谱数据加载中...</p>
      </div>
      
      <!-- 等待/空状态 -->
      <div v-else class="graph-state">
        <div class="empty-icon">?</div>
        <p class="empty-text">等待本体生成...</p>
      </div>
    </div>

    <!-- 底部图例 (Bottom Left) -->
    <div v-if="currentGraphData && entityTypes.length" class="graph-legend">
      <span class="legend-title">Entity Types</span>
      <div class="legend-items">
        <div class="legend-item" v-for="type in entityTypes" :key="type.name">
          <span class="legend-dot" :style="{ background: type.color }"></span>
          <span class="legend-label">{{ type.name }}</span>
        </div>
      </div>
    </div>
    
    <!-- 显示边标签开关 -->
    <div v-if="currentGraphData" class="edge-labels-toggle">
      <label class="toggle-switch">
        <input type="checkbox" v-model="showEdgeLabels" />
        <span class="slider"></span>
      </label>
      <span class="toggle-label">Show Edge Labels</span>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted, watch, nextTick, computed } from 'vue'
import * as d3 from 'd3'
import { getExpandedGraphData, getGraphEntities, getFocusedGraphData } from '../api/graph'

const DEFAULT_ENTITY_LIMIT = 100
const ENTITY_SEARCH_LIMIT = 20
const ENTITY_SEARCH_DEBOUNCE_MS = 300
const DEFAULT_FOCUS_HOPS = 1
const DEFAULT_EXPAND_HOPS = 1
const GRAPH_PER_HOP_LIMIT = 20
const GRAPH_TOTAL_NODE_LIMIT = 150

const props = defineProps({
  graphId: String,
  graphData: Object,
  loading: Boolean,
  currentPhase: Number,
  isSimulating: Boolean
})

const emit = defineEmits(['refresh', 'toggle-maximize'])

const graphContainer = ref(null)
const graphSvg = ref(null)
const selectedItem = ref(null)
const showEdgeLabels = ref(true) // 默认显示边标签
const expandedSelfLoops = ref(new Set()) // 展开的自环项
const showSimulationFinishedHint = ref(false) // 模拟结束后的提示
const wasSimulating = ref(false) // 追踪之前是否在模拟中
const displayGraphData = ref(null)
const entityOptions = ref([])
const selectedEntityUuid = ref('')
const entitySearchInput = ref('')
const entitySearchLoading = ref(false)
const focusLoading = ref(false)
const controlMessage = ref('')
const expandedAnchorUuid = ref('')
let entitySearchTimer = null
let currentZoomTransform = d3.zoomIdentity
let zoomBehaviorRef = null
let pendingExpandedNodeIds = new Set()
let pendingAnchorVisibilityUuid = ''
const nodePositionCache = new Map()

const currentGraphData = computed(() => displayGraphData.value || props.graphData || null)
const isPanelLoading = computed(() => props.loading || focusLoading.value)
const expandedAnchorLabel = computed(() => {
  if (!expandedAnchorUuid.value) return ''
  const anchorNode = (currentGraphData.value?.nodes || []).find(node => node.uuid === expandedAnchorUuid.value)
  return anchorNode?.name || expandedAnchorUuid.value
})

const graphSummaryText = computed(() => {
  if (!currentGraphData.value) return ''

  const totalNodes = currentGraphData.value.node_count || 0
  const totalEdges = currentGraphData.value.edge_count || 0
  const displayNodes = currentGraphData.value.display_node_count || currentGraphData.value.nodes?.length || 0
  const displayEdges = currentGraphData.value.display_edge_count || currentGraphData.value.edges?.length || 0
  const viewMode = currentGraphData.value.view_mode || 'full'

  if (viewMode.startsWith('focus')) {
    return `Focused neighborhood · ${displayNodes}/${totalNodes} nodes · ${displayEdges}/${totalEdges} edges`
  }

  if (viewMode.startsWith('expand')) {
    return `Expanded neighborhood · ${displayNodes}/${totalNodes} nodes · ${displayEdges}/${totalEdges} edges`
  }

  if (viewMode === 'default') {
    return `Default view · ${displayNodes}/${totalNodes} nodes · ${displayEdges}/${totalEdges} edges`
  }

  return `${totalNodes} nodes · ${totalEdges} edges`
})

const canExpandSelectedNode = computed(() => {
  if (!selectedItem.value || selectedItem.value.type !== 'node') return false
  if (!props.graphId || !currentGraphData.value) return false
  return selectedItem.value.data?.has_more_neighbors !== false
})

// 关闭模拟结束提示
const dismissFinishedHint = () => {
  showSimulationFinishedHint.value = false
}

// 监听 isSimulating 变化，检测模拟结束
watch(() => props.isSimulating, (newValue, oldValue) => {
  if (wasSimulating.value && !newValue) {
    // 从模拟中变为非模拟状态，显示结束提示
    showSimulationFinishedHint.value = true
  }
  wasSimulating.value = newValue
}, { immediate: true })

// 切换自环项展开/折叠状态
const toggleSelfLoop = (id) => {
  const newSet = new Set(expandedSelfLoops.value)
  if (newSet.has(id)) {
    newSet.delete(id)
  } else {
    newSet.add(id)
  }
  expandedSelfLoops.value = newSet
}

const getNodeEntityType = (node) => {
  if (!node) return 'Entity'
  return node.labels?.find(label => label !== 'Entity' && label !== 'Node') || 'Entity'
}

const getEntityTypeColor = (entityType) => {
  const matchedType = entityTypes.value.find(item => item.name === entityType)
  return matchedType?.color || '#999'
}

const cacheNodePositions = (nodes = []) => {
  nodes.forEach(node => {
    if (!node?.id) return
    if (!Number.isFinite(node.x) || !Number.isFinite(node.y)) return
    nodePositionCache.set(node.id, { x: node.x, y: node.y })
  })
}

const resetGraphViewportState = ({ clearAnchor = false } = {}) => {
  currentZoomTransform = d3.zoomIdentity
  zoomBehaviorRef = null
  pendingExpandedNodeIds = new Set()
  pendingAnchorVisibilityUuid = ''
  nodePositionCache.clear()
  if (clearAnchor) {
    expandedAnchorUuid.value = ''
  }
}

const syncDisplayGraphData = (graphData) => {
  displayGraphData.value = graphData || null
  selectedItem.value = null
  expandedSelfLoops.value = new Set()
}

const buildEdgeKey = (edge) => {
  if (!edge) return ''
  return edge.uuid || [
    edge.source_node_uuid || '',
    edge.target_node_uuid || '',
    edge.name || edge.fact_type || ''
  ].join('::')
}

const mergeGraphData = (baseGraphData, deltaGraphData) => {
  const mergedNodeMap = new Map()
  const mergedEdgeMap = new Map()

  ;(baseGraphData?.nodes || []).forEach(node => {
    if (node?.uuid) {
      mergedNodeMap.set(node.uuid, node)
    }
  })
  ;(deltaGraphData?.nodes || []).forEach(node => {
    if (node?.uuid) {
      mergedNodeMap.set(node.uuid, node)
    }
  })

  ;(baseGraphData?.edges || []).forEach(edge => {
    const key = buildEdgeKey(edge)
    if (key) {
      mergedEdgeMap.set(key, edge)
    }
  })
  ;(deltaGraphData?.edges || []).forEach(edge => {
    const key = buildEdgeKey(edge)
    if (key) {
      mergedEdgeMap.set(key, edge)
    }
  })

  const mergedNodes = Array.from(mergedNodeMap.values())
  const mergedEdges = Array.from(mergedEdgeMap.values())

  return {
    ...(baseGraphData || {}),
    ...(deltaGraphData || {}),
    nodes: mergedNodes,
    edges: mergedEdges,
    display_node_count: mergedNodes.length,
    display_edge_count: mergedEdges.length,
    node_count: deltaGraphData?.node_count ?? baseGraphData?.node_count ?? mergedNodes.length,
    edge_count: deltaGraphData?.edge_count ?? baseGraphData?.edge_count ?? mergedEdges.length,
    focus_node_uuid: deltaGraphData?.focus_node_uuid ?? baseGraphData?.focus_node_uuid ?? null
  }
}

const buildTransform = (transform = d3.zoomIdentity) => (
  d3.zoomIdentity.translate(transform.x, transform.y).scale(transform.k)
)

const getNodeInitialPosition = (nodeData, index, totalCount, width, height) => {
  const cachedPosition = nodePositionCache.get(nodeData.uuid)
  if (cachedPosition) {
    return cachedPosition
  }

  if (nodeData.is_focus) {
    return { x: width / 2, y: height / 2 }
  }

  const anchorPosition = expandedAnchorUuid.value
    ? nodePositionCache.get(expandedAnchorUuid.value)
    : null

  if (anchorPosition && pendingExpandedNodeIds.has(nodeData.uuid)) {
    const pendingIds = Array.from(pendingExpandedNodeIds)
    const pendingIndex = Math.max(0, pendingIds.indexOf(nodeData.uuid))
    const angle = (pendingIndex / Math.max(pendingIds.length, 1)) * Math.PI * 2
    const radius = 90 + Math.floor(pendingIndex / 8) * 28
    return {
      x: anchorPosition.x + Math.cos(angle) * radius,
      y: anchorPosition.y + Math.sin(angle) * radius
    }
  }

  const angle = (index / Math.max(totalCount, 1)) * Math.PI * 2
  const radius = Math.min(width, height) * 0.22
  return {
    x: width / 2 + Math.cos(angle) * radius,
    y: height / 2 + Math.sin(angle) * radius
  }
}

const keepNodeInView = (nodeDatum) => {
  if (!zoomBehaviorRef || !graphSvg.value || !graphContainer.value || !nodeDatum) return
  if (!Number.isFinite(nodeDatum.x) || !Number.isFinite(nodeDatum.y)) return

  const width = graphContainer.value.clientWidth
  const height = graphContainer.value.clientHeight
  const margin = 100
  const k = currentZoomTransform.k
  const screenX = nodeDatum.x * k + currentZoomTransform.x
  const screenY = nodeDatum.y * k + currentZoomTransform.y

  let dx = 0
  let dy = 0

  if (screenX < margin) {
    dx = margin - screenX
  } else if (screenX > width - margin) {
    dx = width - margin - screenX
  }

  if (screenY < margin) {
    dy = margin - screenY
  } else if (screenY > height - margin) {
    dy = height - margin - screenY
  }

  if (dx === 0 && dy === 0) return

  const nextTransform = d3.zoomIdentity
    .translate(currentZoomTransform.x + dx, currentZoomTransform.y + dy)
    .scale(currentZoomTransform.k)

  d3.select(graphSvg.value)
    .transition()
    .duration(250)
    .call(zoomBehaviorRef.transform, nextTransform)
}

const formatEntityOption = (entity) => {
  if (!entity) return ''
  if (entity.name && entity.uuid && entity.name !== entity.uuid) {
    return `${entity.name} (${entity.uuid})`
  }
  return entity.name || entity.uuid || ''
}

const loadEntityOptions = async (query = '') => {
  if (!props.graphId) {
    entityOptions.value = []
    return
  }

  entitySearchLoading.value = true
  const trimmedQuery = query.trim()

  try {
    const res = await getGraphEntities(props.graphId, {
      q: trimmedQuery || undefined,
      limit: trimmedQuery ? ENTITY_SEARCH_LIMIT : DEFAULT_ENTITY_LIMIT
    })

    if (res.success) {
      entityOptions.value = res.data?.entities || []
      if (trimmedQuery) {
        controlMessage.value = entityOptions.value.length > 0
          ? `找到 ${entityOptions.value.length} 个候选实体`
          : '未找到匹配实体'
      } else if (!focusLoading.value) {
        controlMessage.value = ''
      }
    } else {
      controlMessage.value = res.error || '实体候选加载失败'
    }
  } catch (err) {
    controlMessage.value = `实体候选加载失败: ${err.message}`
  } finally {
    entitySearchLoading.value = false
  }
}

const focusOnEntity = async (entityUuid) => {
  if (!props.graphId || !entityUuid) return

  focusLoading.value = true

  try {
    const res = await getFocusedGraphData(props.graphId, {
      entity_uuid: entityUuid,
      hops: DEFAULT_FOCUS_HOPS,
      per_hop_limit: GRAPH_PER_HOP_LIMIT,
      total_node_limit: GRAPH_TOTAL_NODE_LIMIT
    })

    if (res.success) {
      resetGraphViewportState()
      expandedAnchorUuid.value = entityUuid
      syncDisplayGraphData(res.data)
      controlMessage.value = '已切换到实体邻域视图'
    } else {
      controlMessage.value = res.error || '实体邻域加载失败'
    }
  } catch (err) {
    controlMessage.value = `实体邻域加载失败: ${err.message}`
  } finally {
    focusLoading.value = false
  }
}

const expandSelectedNode = async () => {
  const selectedNode = selectedItem.value?.type === 'node' ? selectedItem.value.data : null
  if (!props.graphId || !selectedNode?.uuid || !currentGraphData.value) return

  focusLoading.value = true

  try {
    const excludeNodeUuids = (currentGraphData.value.nodes || [])
      .map(node => node.uuid)
      .filter(Boolean)
      .join(',')

    const res = await getExpandedGraphData(props.graphId, {
      entity_uuid: selectedNode.uuid,
      hops: DEFAULT_EXPAND_HOPS,
      per_hop_limit: GRAPH_PER_HOP_LIMIT,
      total_node_limit: GRAPH_TOTAL_NODE_LIMIT,
      exclude_node_uuids: excludeNodeUuids || undefined
    })

    if (res.success) {
      expandedAnchorUuid.value = selectedNode.uuid
      pendingAnchorVisibilityUuid = selectedNode.uuid
      const mergedGraphData = mergeGraphData(currentGraphData.value, res.data)
      const previousNodeCount = currentGraphData.value.nodes?.length || 0
      const previousNodeIds = new Set((currentGraphData.value.nodes || []).map(node => node.uuid).filter(Boolean))
      pendingExpandedNodeIds = new Set(
        (mergedGraphData.nodes || [])
          .map(node => node.uuid)
          .filter(uuid => uuid && !previousNodeIds.has(uuid))
      )
      syncDisplayGraphData(mergedGraphData)

      const refreshedNode = mergedGraphData.nodes.find(node => node.uuid === selectedNode.uuid)
      if (refreshedNode) {
        const entityType = getNodeEntityType(refreshedNode)
        selectedItem.value = {
          type: 'node',
          data: refreshedNode,
          entityType,
          color: getEntityTypeColor(entityType)
        }
      }

      const nextNodeCount = mergedGraphData.nodes?.length || 0
      controlMessage.value = nextNodeCount > previousNodeCount
        ? `已从 ${refreshedNode?.name || selectedNode.uuid} 扩展一跳邻域`
        : '该实体没有更多可扩展的相邻实体'
    } else {
      controlMessage.value = res.error || '实体扩展失败'
    }
  } catch (err) {
    controlMessage.value = `实体扩展失败: ${err.message}`
  } finally {
    focusLoading.value = false
  }
}

const handleSearch = async () => {
  const query = entitySearchInput.value.trim()

  if (selectedEntityUuid.value) {
    await focusOnEntity(selectedEntityUuid.value)
    return
  }

  if (!query) {
    controlMessage.value = '请输入实体名称或ID'
    return
  }

  await loadEntityOptions(query)
  const firstMatch = entityOptions.value[0]
  if (!firstMatch) {
    controlMessage.value = '未找到匹配实体'
    return
  }

  selectedEntityUuid.value = firstMatch.uuid
  await focusOnEntity(firstMatch.uuid)
}

const handleEntitySelect = async () => {
  if (!selectedEntityUuid.value) {
    resetToDefaultView()
    return
  }

  const entity = entityOptions.value.find(item => item.uuid === selectedEntityUuid.value)
  if (entity) {
    entitySearchInput.value = entity.name || entity.uuid || ''
  }

  await focusOnEntity(selectedEntityUuid.value)
}

const resetToDefaultView = () => {
  resetGraphViewportState({ clearAnchor: true })
  syncDisplayGraphData(props.graphData)
  selectedEntityUuid.value = ''
  entitySearchInput.value = ''
  controlMessage.value = ''
  loadEntityOptions()
}

// 计算实体类型用于图例
const entityTypes = computed(() => {
  if (!currentGraphData.value?.nodes) return []
  const typeMap = {}
  // 美观的颜色调色板
  const colors = ['#FF6B35', '#004E89', '#7B2D8E', '#1A936F', '#C5283D', '#E9724C', '#3498db', '#9b59b6', '#27ae60', '#f39c12']
  
  currentGraphData.value.nodes.forEach(node => {
    const type = node.labels?.find(l => l !== 'Entity') || 'Entity'
    if (!typeMap[type]) {
      typeMap[type] = { name: type, count: 0, color: colors[Object.keys(typeMap).length % colors.length] }
    }
    typeMap[type].count++
  })
  return Object.values(typeMap)
})

// 格式化时间
const formatDateTime = (dateStr) => {
  if (!dateStr) return ''
  try {
    const date = new Date(dateStr)
    return date.toLocaleString('en-US', { 
      month: 'short', 
      day: 'numeric', 
      year: 'numeric',
      hour: 'numeric',
      minute: '2-digit',
      hour12: true 
    })
  } catch {
    return dateStr
  }
}

const closeDetailPanel = () => {
  selectedItem.value = null
  expandedSelfLoops.value = new Set() // 重置展开状态
}

let currentSimulation = null
let linkLabelsRef = null
let linkLabelBgRef = null

const renderGraph = () => {
  if (!graphSvg.value || !currentGraphData.value) return
  
  // 停止之前的仿真
  if (currentSimulation) {
    cacheNodePositions(currentSimulation.nodes())
    currentSimulation.stop()
  }
  
  const container = graphContainer.value
  const width = container.clientWidth
  const height = container.clientHeight
  
  const svg = d3.select(graphSvg.value)
    .attr('width', width)
    .attr('height', height)
    .attr('viewBox', `0 0 ${width} ${height}`)
    
  svg.selectAll('*').remove()
  
  const nodesData = currentGraphData.value.nodes || []
  const edgesData = currentGraphData.value.edges || []
  
  if (nodesData.length === 0) {
    linkLabelsRef = null
    linkLabelBgRef = null
    return
  }

  // Prep data
  const nodeMap = {}
  nodesData.forEach(n => nodeMap[n.uuid] = n)

  const nodes = nodesData.map((n, index) => ({
    id: n.uuid,
    name: n.name || 'Unnamed',
    type: n.labels?.find(l => l !== 'Entity' && l !== 'Node') || 'Entity',
    rawData: n,
    ...getNodeInitialPosition(n, index, nodesData.length, width, height)
  }))

  pendingExpandedNodeIds = new Set()
  
  const nodeIds = new Set(nodes.map(n => n.id))
  
  // 处理边数据，计算同一对节点间的边数量和索引
  const edgePairCount = {}
  const selfLoopEdges = {} // 按节点分组的自环边
  const tempEdges = edgesData
    .filter(e => nodeIds.has(e.source_node_uuid) && nodeIds.has(e.target_node_uuid))
  
  // 统计每对节点之间的边数量，收集自环边
  tempEdges.forEach(e => {
    if (e.source_node_uuid === e.target_node_uuid) {
      // 自环 - 收集到数组中
      if (!selfLoopEdges[e.source_node_uuid]) {
        selfLoopEdges[e.source_node_uuid] = []
      }
      selfLoopEdges[e.source_node_uuid].push({
        ...e,
        source_name: nodeMap[e.source_node_uuid]?.name,
        target_name: nodeMap[e.target_node_uuid]?.name
      })
    } else {
      const pairKey = [e.source_node_uuid, e.target_node_uuid].sort().join('_')
      edgePairCount[pairKey] = (edgePairCount[pairKey] || 0) + 1
    }
  })
  
  // 记录当前处理到每对节点的第几条边
  const edgePairIndex = {}
  const processedSelfLoopNodes = new Set() // 已处理的自环节点
  
  const edges = []
  
  tempEdges.forEach(e => {
    const isSelfLoop = e.source_node_uuid === e.target_node_uuid
    
    if (isSelfLoop) {
      // 自环边 - 每个节点只添加一条合并的自环
      if (processedSelfLoopNodes.has(e.source_node_uuid)) {
        return // 已处理过，跳过
      }
      processedSelfLoopNodes.add(e.source_node_uuid)
      
      const allSelfLoops = selfLoopEdges[e.source_node_uuid]
      const nodeName = nodeMap[e.source_node_uuid]?.name || 'Unknown'
      
      edges.push({
        source: e.source_node_uuid,
        target: e.target_node_uuid,
        type: 'SELF_LOOP',
        name: `Self Relations (${allSelfLoops.length})`,
        curvature: 0,
        isSelfLoop: true,
        rawData: {
          isSelfLoopGroup: true,
          source_name: nodeName,
          target_name: nodeName,
          selfLoopCount: allSelfLoops.length,
          selfLoopEdges: allSelfLoops // 存储所有自环边的详细信息
        }
      })
      return
    }
    
    const pairKey = [e.source_node_uuid, e.target_node_uuid].sort().join('_')
    const totalCount = edgePairCount[pairKey]
    const currentIndex = edgePairIndex[pairKey] || 0
    edgePairIndex[pairKey] = currentIndex + 1
    
    // 判断边的方向是否与标准化方向一致（源UUID < 目标UUID）
    const isReversed = e.source_node_uuid > e.target_node_uuid
    
    // 计算曲率：多条边时分散开，单条边为直线
    let curvature = 0
    if (totalCount > 1) {
      // 均匀分布曲率，确保明显区分
      // 曲率范围根据边数量增加，边越多曲率范围越大
      const curvatureRange = Math.min(1.2, 0.6 + totalCount * 0.15)
      curvature = ((currentIndex / (totalCount - 1)) - 0.5) * curvatureRange * 2
      
      // 如果边的方向与标准化方向相反，翻转曲率
      // 这样确保所有边在同一参考系下分布，不会因方向不同而重叠
      if (isReversed) {
        curvature = -curvature
      }
    }
    
    edges.push({
      source: e.source_node_uuid,
      target: e.target_node_uuid,
      type: e.fact_type || e.name || 'RELATED',
      name: e.name || e.fact_type || 'RELATED',
      curvature,
      isSelfLoop: false,
      pairIndex: currentIndex,
      pairTotal: totalCount,
      rawData: {
        ...e,
        source_name: nodeMap[e.source_node_uuid]?.name,
        target_name: nodeMap[e.target_node_uuid]?.name
      }
    })
  })
    
  // Color scale
  const colorMap = {}
  entityTypes.value.forEach(t => colorMap[t.name] = t.color)
  const getColor = (type) => colorMap[type] || '#999'

  // Simulation - 根据边数量动态调整节点间距
  const simulation = d3.forceSimulation(nodes)
    .force('link', d3.forceLink(edges).id(d => d.id).distance(d => {
      // 根据这对节点之间的边数量动态调整距离
      // 基础距离 150，每多一条边增加 40
      const baseDistance = 150
      const edgeCount = d.pairTotal || 1
      return baseDistance + (edgeCount - 1) * 50
    }))
    .force('charge', d3.forceManyBody().strength(-400))
    .force('center', d3.forceCenter(width / 2, height / 2))
    .force('collide', d3.forceCollide(50))
    // 添加向中心的引力，让独立的节点群聚集到中心区域
    .force('x', d3.forceX(width / 2).strength(0.015))
    .force('y', d3.forceY(height / 2).strength(0.015))
  
  currentSimulation = simulation

  const g = svg.append('g')
  
  // Zoom
  zoomBehaviorRef = d3.zoom()
    .extent([[0, 0], [width, height]])
    .scaleExtent([0.1, 4])
    .on('zoom', (event) => {
      currentZoomTransform = event.transform
      g.attr('transform', event.transform)
    })

  svg.call(zoomBehaviorRef)
  svg.call(zoomBehaviorRef.transform, buildTransform(currentZoomTransform))

  // Links - 使用 path 支持曲线
  const linkGroup = g.append('g').attr('class', 'links')
  
  // 计算曲线路径
  const getLinkPath = (d) => {
    const sx = d.source.x, sy = d.source.y
    const tx = d.target.x, ty = d.target.y
    
    // 检测自环
    if (d.isSelfLoop) {
      // 自环：绘制一个圆弧从节点出发再返回
      const loopRadius = 30
      // 从节点右侧出发，绕一圈回来
      const x1 = sx + 8  // 起点偏移
      const y1 = sy - 4
      const x2 = sx + 8  // 终点偏移
      const y2 = sy + 4
      // 使用圆弧绘制自环（sweep-flag=1 顺时针）
      return `M${x1},${y1} A${loopRadius},${loopRadius} 0 1,1 ${x2},${y2}`
    }
    
    if (d.curvature === 0) {
      // 直线
      return `M${sx},${sy} L${tx},${ty}`
    }
    
    // 计算曲线控制点 - 根据边数量和距离动态调整
    const dx = tx - sx, dy = ty - sy
    const dist = Math.sqrt(dx * dx + dy * dy)
    // 垂直于连线方向的偏移，根据距离比例计算，保证曲线明显可见
    // 边越多，偏移量占距离的比例越大
    const pairTotal = d.pairTotal || 1
    const offsetRatio = 0.25 + pairTotal * 0.05 // 基础25%，每多一条边增加5%
    const baseOffset = Math.max(35, dist * offsetRatio)
    const offsetX = -dy / dist * d.curvature * baseOffset
    const offsetY = dx / dist * d.curvature * baseOffset
    const cx = (sx + tx) / 2 + offsetX
    const cy = (sy + ty) / 2 + offsetY
    
    return `M${sx},${sy} Q${cx},${cy} ${tx},${ty}`
  }
  
  // 计算曲线中点（用于标签定位）
  const getLinkMidpoint = (d) => {
    const sx = d.source.x, sy = d.source.y
    const tx = d.target.x, ty = d.target.y
    
    // 检测自环
    if (d.isSelfLoop) {
      // 自环标签位置：节点右侧
      return { x: sx + 70, y: sy }
    }
    
    if (d.curvature === 0) {
      return { x: (sx + tx) / 2, y: (sy + ty) / 2 }
    }
    
    // 二次贝塞尔曲线的中点 t=0.5
    const dx = tx - sx, dy = ty - sy
    const dist = Math.sqrt(dx * dx + dy * dy)
    const pairTotal = d.pairTotal || 1
    const offsetRatio = 0.25 + pairTotal * 0.05
    const baseOffset = Math.max(35, dist * offsetRatio)
    const offsetX = -dy / dist * d.curvature * baseOffset
    const offsetY = dx / dist * d.curvature * baseOffset
    const cx = (sx + tx) / 2 + offsetX
    const cy = (sy + ty) / 2 + offsetY
    
    // 二次贝塞尔曲线公式 B(t) = (1-t)2P0 + 2(1-t)tP1 + t2P2, t=0.5
    const midX = 0.25 * sx + 0.5 * cx + 0.25 * tx
    const midY = 0.25 * sy + 0.5 * cy + 0.25 * ty
    
    return { x: midX, y: midY }
  }
  
  const link = linkGroup.selectAll('path')
    .data(edges)
    .enter().append('path')
    .attr('stroke', '#C0C0C0')
    .attr('stroke-width', 1.5)
    .attr('fill', 'none')
    .style('cursor', 'pointer')
    .on('click', (event, d) => {
      event.stopPropagation()
      selectedItem.value = {
        type: 'edge',
        data: d.rawData
      }
      applySelectionStyles()
    })

  // Link labels background (白色背景使文字更清晰)
  const linkLabelBg = linkGroup.selectAll('rect')
    .data(edges)
    .enter().append('rect')
    .attr('fill', 'rgba(255,255,255,0.95)')
    .attr('rx', 3)
    .attr('ry', 3)
    .style('cursor', 'pointer')
    .style('pointer-events', 'all')
    .style('display', showEdgeLabels.value ? 'block' : 'none')
    .on('click', (event, d) => {
      event.stopPropagation()
      selectedItem.value = {
        type: 'edge',
        data: d.rawData
      }
      applySelectionStyles()
    })

  // Link labels
  const linkLabels = linkGroup.selectAll('text')
    .data(edges)
    .enter().append('text')
    .text(d => d.name)
    .attr('font-size', '9px')
    .attr('fill', '#666')
    .attr('text-anchor', 'middle')
    .attr('dominant-baseline', 'middle')
    .style('cursor', 'pointer')
    .style('pointer-events', 'all')
    .style('font-family', 'system-ui, sans-serif')
    .style('display', showEdgeLabels.value ? 'block' : 'none')
    .on('click', (event, d) => {
      event.stopPropagation()
      selectedItem.value = {
        type: 'edge',
        data: d.rawData
      }
      applySelectionStyles()
    })
  
  // 保存引用供外部控制显隐
  linkLabelsRef = linkLabels
  linkLabelBgRef = linkLabelBg

  // Nodes group
  const nodeGroup = g.append('g').attr('class', 'nodes')
  
  // Node circles
  const node = nodeGroup.selectAll('circle')
    .data(nodes)
    .enter().append('circle')
    .attr('r', 10)
    .attr('fill', d => getColor(d.type))
    .attr('stroke', '#fff')
    .attr('stroke-width', 2.5)
    .style('cursor', 'pointer')
    .call(d3.drag()
      .on('start', (event, d) => {
        // 只记录位置，不重启仿真（区分点击和拖拽）
        d.fx = d.x
        d.fy = d.y
        d._dragStartX = event.x
        d._dragStartY = event.y
        d._isDragging = false
      })
      .on('drag', (event, d) => {
        // 检测是否真正开始拖拽（移动超过阈值）
        const dx = event.x - d._dragStartX
        const dy = event.y - d._dragStartY
        const distance = Math.sqrt(dx * dx + dy * dy)
        
        if (!d._isDragging && distance > 3) {
          // 首次检测到真正拖拽，才重启仿真
          d._isDragging = true
          simulation.alphaTarget(0.3).restart()
        }
        
        if (d._isDragging) {
          d.fx = event.x
          d.fy = event.y
        }
      })
      .on('end', (event, d) => {
        // 只有真正拖拽过才让仿真逐渐停止
        if (d._isDragging) {
          simulation.alphaTarget(0)
        }
        d.fx = null
        d.fy = null
        d._isDragging = false
        cacheNodePositions([d])
      })
    )
    .on('click', (event, d) => {
      event.stopPropagation()
      selectedItem.value = {
        type: 'node',
        data: d.rawData,
        entityType: d.type,
        color: getColor(d.type)
      }
      applySelectionStyles()
    })
    .on('mouseenter', (event, d) => {
      const isSelectedNode = selectedItem.value?.type === 'node' && selectedItem.value.data?.uuid === d.rawData.uuid
      const isAnchorNode = expandedAnchorUuid.value === d.rawData.uuid
      if (!isSelectedNode && !isAnchorNode) {
        d3.select(event.target).attr('stroke', '#333').attr('stroke-width', 3)
      }
    })
    .on('mouseleave', (event, d) => {
      const isSelectedNode = selectedItem.value?.type === 'node' && selectedItem.value.data?.uuid === d.rawData.uuid
      const isAnchorNode = expandedAnchorUuid.value === d.rawData.uuid
      if (!isSelectedNode && !isAnchorNode) {
        applySelectionStyles()
      }
    })

  // Node Labels
  const nodeLabels = nodeGroup.selectAll('text')
    .data(nodes)
    .enter().append('text')
    .text(d => d.name.length > 8 ? d.name.substring(0, 8) + '…' : d.name)
    .attr('font-size', '11px')
    .attr('fill', '#333')
    .attr('font-weight', '500')
    .attr('dx', 14)
    .attr('dy', 4)
    .style('pointer-events', 'none')
    .style('font-family', 'system-ui, sans-serif')

  const applySelectionStyles = () => {
    const selectedNodeUuid = selectedItem.value?.type === 'node' ? selectedItem.value.data?.uuid : ''
    const selectedEdgeKey = selectedItem.value?.type === 'edge' ? buildEdgeKey(selectedItem.value.data) : ''
    const anchorUuid = expandedAnchorUuid.value

    node
      .attr('r', d => (anchorUuid && d.id === anchorUuid ? 11.5 : 10))
      .attr('stroke', d => {
        if (selectedNodeUuid && d.id === selectedNodeUuid) return '#E91E63'
        if (anchorUuid && d.id === anchorUuid) return '#F39C12'
        return '#fff'
      })
      .attr('stroke-width', d => {
        if (selectedNodeUuid && d.id === selectedNodeUuid) return 4
        if (anchorUuid && d.id === anchorUuid) return 4
        return 2.5
      })

    nodeLabels
      .attr('fill', d => (anchorUuid && d.id === anchorUuid ? '#0F4C81' : '#333'))
      .attr('font-weight', d => (anchorUuid && d.id === anchorUuid ? '700' : '500'))

    link
      .attr('stroke', d => {
        if (selectedEdgeKey && buildEdgeKey(d.rawData) === selectedEdgeKey) return '#3498db'
        if (selectedNodeUuid && (d.source.id === selectedNodeUuid || d.target.id === selectedNodeUuid)) return '#E91E63'
        if (!selectedNodeUuid && anchorUuid && (d.source.id === anchorUuid || d.target.id === anchorUuid)) return '#F39C12'
        return '#C0C0C0'
      })
      .attr('stroke-width', d => {
        if (selectedEdgeKey && buildEdgeKey(d.rawData) === selectedEdgeKey) return 3
        if (selectedNodeUuid && (d.source.id === selectedNodeUuid || d.target.id === selectedNodeUuid)) return 2.5
        if (!selectedNodeUuid && anchorUuid && (d.source.id === anchorUuid || d.target.id === anchorUuid)) return 2.2
        return 1.5
      })

    linkLabelBg.attr('fill', d => (
      selectedEdgeKey && buildEdgeKey(d.rawData) === selectedEdgeKey
        ? 'rgba(52, 152, 219, 0.1)'
        : 'rgba(255,255,255,0.95)'
    ))
    linkLabels.attr('fill', d => (
      selectedEdgeKey && buildEdgeKey(d.rawData) === selectedEdgeKey
        ? '#3498db'
        : '#666'
    ))
  }

  applySelectionStyles()

  simulation.on('tick', () => {
    // 更新曲线路径
    link.attr('d', d => getLinkPath(d))
    
    // 更新边标签位置（无旋转，水平显示更清晰）
    linkLabels.each(function(d) {
      const mid = getLinkMidpoint(d)
      d3.select(this)
        .attr('x', mid.x)
        .attr('y', mid.y)
        .attr('transform', '') // 移除旋转，保持水平
    })
    
    // 更新边标签背景
    linkLabelBg.each(function(d, i) {
      const mid = getLinkMidpoint(d)
      const textEl = linkLabels.nodes()[i]
      const bbox = textEl.getBBox()
      d3.select(this)
        .attr('x', mid.x - bbox.width / 2 - 4)
        .attr('y', mid.y - bbox.height / 2 - 2)
        .attr('width', bbox.width + 8)
        .attr('height', bbox.height + 4)
        .attr('transform', '') // 移除旋转
    })

    node
      .attr('cx', d => d.x)
      .attr('cy', d => d.y)

    nodeLabels
      .attr('x', d => d.x)
      .attr('y', d => d.y)

    cacheNodePositions(nodes)

    if (pendingAnchorVisibilityUuid) {
      const anchorNode = nodes.find(item => item.id === pendingAnchorVisibilityUuid)
      if (anchorNode) {
        keepNodeInView(anchorNode)
        pendingAnchorVisibilityUuid = ''
      }
    }
  })
  
  // 点击空白处关闭详情面板
  svg.on('click', () => {
    selectedItem.value = null
    applySelectionStyles()
  })
}

watch(() => props.graphData, (newValue) => {
  syncDisplayGraphData(newValue)
})

watch(displayGraphData, () => {
  nextTick(renderGraph)
}, { deep: true })

watch(() => props.graphId, (newGraphId) => {
  if (!newGraphId) {
    resetGraphViewportState({ clearAnchor: true })
    entityOptions.value = []
    selectedEntityUuid.value = ''
    entitySearchInput.value = ''
    controlMessage.value = ''
    return
  }

  resetGraphViewportState({ clearAnchor: true })
  loadEntityOptions()
}, { immediate: true })

watch(entitySearchInput, (newValue) => {
  const trimmedValue = newValue.trim()
  const selectedEntity = entityOptions.value.find(item => item.uuid === selectedEntityUuid.value)

  if (selectedEntity && trimmedValue && trimmedValue !== (selectedEntity.name || selectedEntity.uuid || '')) {
    selectedEntityUuid.value = ''
  }

  if (entitySearchTimer) {
    clearTimeout(entitySearchTimer)
  }

  entitySearchTimer = setTimeout(() => {
    loadEntityOptions(trimmedValue)
  }, ENTITY_SEARCH_DEBOUNCE_MS)
})

// 监听边标签显示开关
watch(showEdgeLabels, (newVal) => {
  if (linkLabelsRef) {
    linkLabelsRef.style('display', newVal ? 'block' : 'none')
  }
  if (linkLabelBgRef) {
    linkLabelBgRef.style('display', newVal ? 'block' : 'none')
  }
})

const handleResize = () => {
  nextTick(renderGraph)
}

onMounted(() => {
  window.addEventListener('resize', handleResize)
  resetGraphViewportState({ clearAnchor: true })
  syncDisplayGraphData(props.graphData)
})

onUnmounted(() => {
  window.removeEventListener('resize', handleResize)
  if (entitySearchTimer) {
    clearTimeout(entitySearchTimer)
  }
  if (currentSimulation) {
    currentSimulation.stop()
  }
})
</script>

<style scoped>
.graph-panel {
  position: relative;
  width: 100%;
  height: 100%;
  background-color: #FAFAFA;
  background-image: radial-gradient(#D0D0D0 1.5px, transparent 1.5px);
  background-size: 24px 24px;
  overflow: hidden;
}

.panel-header {
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  padding: 16px 20px 10px;
  z-index: 10;
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  background: linear-gradient(to bottom, rgba(255,255,255,0.95), rgba(255,255,255,0));
  pointer-events: none;
}

.header-primary {
  pointer-events: auto;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.panel-title {
  font-size: 14px;
  font-weight: 600;
  color: #333;
  pointer-events: auto;
}

.panel-subtitle {
  font-size: 11px;
  color: #666;
  pointer-events: auto;
}

.header-controls {
  pointer-events: auto;
  display: flex;
  align-items: center;
  gap: 12px;
}

.entity-controls {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 10px;
  border: 1px solid rgba(224,224,224,0.9);
  border-radius: 12px;
  background: rgba(255,255,255,0.96);
  box-shadow: 0 6px 18px rgba(0,0,0,0.05);
}

.entity-select,
.entity-search-input {
  height: 34px;
  border: 1px solid #E0E0E0;
  border-radius: 8px;
  background: #FFF;
  color: #333;
  font-size: 12px;
  padding: 0 10px;
  outline: none;
}

.entity-select {
  min-width: 210px;
  max-width: 260px;
}

.entity-search-input {
  width: 220px;
}

.entity-select:focus,
.entity-search-input:focus {
  border-color: #3498db;
  box-shadow: 0 0 0 3px rgba(52,152,219,0.12);
}

.header-tools {
  display: flex;
  gap: 10px;
  align-items: center;
}

.tool-btn {
  height: 32px;
  padding: 0 12px;
  border: 1px solid #E0E0E0;
  background: #FFF;
  border-radius: 6px;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  cursor: pointer;
  color: #666;
  transition: all 0.2s;
  box-shadow: 0 2px 4px rgba(0,0,0,0.02);
  font-size: 13px;
}

.tool-btn:hover {
  background: #F5F5F5;
  color: #000;
  border-color: #CCC;
}

.tool-btn .btn-text {
  font-size: 12px;
}

.tool-btn.compact {
  min-width: 72px;
}

.tool-btn.ghost {
  background: rgba(255,255,255,0.9);
}

.icon-refresh.spinning {
  animation: spin 1s linear infinite;
}

@keyframes spin { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }

.search-status {
  position: absolute;
  top: 82px;
  left: 20px;
  z-index: 10;
  max-width: 420px;
  padding: 7px 12px;
  border-radius: 999px;
  background: rgba(255,255,255,0.95);
  border: 1px solid #EAEAEA;
  box-shadow: 0 4px 12px rgba(0,0,0,0.04);
  font-size: 12px;
  color: #555;
}

.graph-container {
  width: 100%;
  height: 100%;
}

.graph-view, .graph-svg {
  width: 100%;
  height: 100%;
  display: block;
}

.graph-state {
  position: absolute;
  top: 50%;
  left: 50%;
  transform: translate(-50%, -50%);
  text-align: center;
  color: #999;
}

.empty-icon {
  font-size: 48px;
  margin-bottom: 16px;
  opacity: 0.2;
}

/* Entity Types Legend - Bottom Left */
.graph-legend {
  position: absolute;
  bottom: 24px;
  left: 24px;
  background: rgba(255,255,255,0.95);
  padding: 12px 16px;
  border-radius: 8px;
  border: 1px solid #EAEAEA;
  box-shadow: 0 4px 16px rgba(0,0,0,0.06);
  z-index: 10;
}

.legend-title {
  display: block;
  font-size: 11px;
  font-weight: 600;
  color: #E91E63;
  margin-bottom: 10px;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.legend-items {
  display: flex;
  flex-wrap: wrap;
  gap: 10px 16px;
  max-width: 320px;
}

.legend-item {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: #555;
}

.legend-dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  flex-shrink: 0;
}

.legend-label {
  white-space: nowrap;
}

/* Edge Labels Toggle - Top Right */
.edge-labels-toggle {
  position: absolute;
  top: 118px;
  right: 20px;
  display: flex;
  align-items: center;
  gap: 10px;
  background: #FFF;
  padding: 8px 14px;
  border-radius: 20px;
  border: 1px solid #E0E0E0;
  box-shadow: 0 2px 8px rgba(0,0,0,0.04);
  z-index: 10;
}

.toggle-switch {
  position: relative;
  display: inline-block;
  width: 40px;
  height: 22px;
}

.toggle-switch input {
  opacity: 0;
  width: 0;
  height: 0;
}

.slider {
  position: absolute;
  cursor: pointer;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background-color: #E0E0E0;
  border-radius: 22px;
  transition: 0.3s;
}

.slider:before {
  position: absolute;
  content: "";
  height: 16px;
  width: 16px;
  left: 3px;
  bottom: 3px;
  background-color: white;
  border-radius: 50%;
  transition: 0.3s;
}

input:checked + .slider {
  background-color: #7B2D8E;
}

input:checked + .slider:before {
  transform: translateX(18px);
}

.toggle-label {
  font-size: 12px;
  color: #666;
}

/* Detail Panel - Right Side */
.detail-panel {
  position: absolute;
  top: 60px;
  right: 20px;
  width: 320px;
  max-height: calc(100% - 100px);
  background: #FFF;
  border: 1px solid #EAEAEA;
  border-radius: 10px;
  box-shadow: 0 8px 32px rgba(0,0,0,0.1);
  overflow: hidden;
  font-family: 'Noto Sans SC', system-ui, sans-serif;
  font-size: 13px;
  z-index: 20;
  display: flex;
  flex-direction: column;
}

.detail-panel-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 14px 16px;
  background: #FAFAFA;
  border-bottom: 1px solid #EEE;
  flex-shrink: 0;
}

.detail-title {
  font-weight: 600;
  color: #333;
  font-size: 14px;
}

.detail-type-badge {
  padding: 4px 10px;
  border-radius: 12px;
  font-size: 11px;
  font-weight: 500;
  margin-left: auto;
  margin-right: 12px;
}

.detail-close {
  background: none;
  border: none;
  font-size: 20px;
  cursor: pointer;
  color: #999;
  line-height: 1;
  padding: 0;
  transition: color 0.2s;
}

.detail-close:hover {
  color: #333;
}

.detail-content {
  padding: 16px;
  overflow-y: auto;
  flex: 1;
}

.detail-row {
  margin-bottom: 12px;
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}

.detail-actions {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-bottom: 16px;
}

.detail-action-btn {
  border: 1px solid #D0D7DE;
  background: linear-gradient(135deg, #0F4C81 0%, #2F80ED 100%);
  color: #FFF;
  border-radius: 8px;
  padding: 10px 12px;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  transition: opacity 0.2s ease, transform 0.2s ease;
}

.detail-action-btn:hover:not(:disabled) {
  opacity: 0.92;
  transform: translateY(-1px);
}

.detail-action-btn:disabled {
  cursor: not-allowed;
  opacity: 0.55;
}

.detail-action-context {
  font-size: 11px;
  color: #0F4C81;
  font-weight: 600;
}

.detail-action-hint {
  font-size: 11px;
  color: #666;
}

.detail-label {
  color: #888;
  font-size: 12px;
  font-weight: 500;
  min-width: 80px;
}

.detail-value {
  color: #333;
  flex: 1;
  word-break: break-word;
}

.detail-value.uuid-text {
  font-family: 'JetBrains Mono', monospace;
  font-size: 11px;
  color: #666;
}

.detail-value.fact-text {
  line-height: 1.5;
  color: #444;
}

.detail-section {
  margin-top: 16px;
  padding-top: 14px;
  border-top: 1px solid #F0F0F0;
}

.section-title {
  font-size: 12px;
  font-weight: 600;
  color: #666;
  margin-bottom: 10px;
}

.properties-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.property-item {
  display: flex;
  gap: 8px;
}

.property-key {
  color: #888;
  font-weight: 500;
  min-width: 90px;
}

.property-value {
  color: #333;
  flex: 1;
}

.summary-text {
  line-height: 1.6;
  color: #444;
  font-size: 12px;
}

.labels-list {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.label-tag {
  display: inline-block;
  padding: 4px 12px;
  background: #F5F5F5;
  border: 1px solid #E0E0E0;
  border-radius: 16px;
  font-size: 11px;
  color: #555;
}

.episodes-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.episode-tag {
  display: inline-block;
  padding: 6px 10px;
  background: #F8F8F8;
  border: 1px solid #E8E8E8;
  border-radius: 6px;
  font-family: 'JetBrains Mono', monospace;
  font-size: 10px;
  color: #666;
  word-break: break-all;
}

/* Edge relation header */
.edge-relation-header {
  background: #F8F8F8;
  padding: 12px;
  border-radius: 8px;
  margin-bottom: 16px;
  font-size: 13px;
  font-weight: 500;
  color: #333;
  line-height: 1.5;
  word-break: break-word;
}

/* Building hint */
.graph-building-hint {
  position: absolute;
  bottom: 160px; /* Moved up from 80px */
  left: 50%;
  transform: translateX(-50%);
  background: rgba(0, 0, 0, 0.65);
  backdrop-filter: blur(8px);
  color: #fff;
  padding: 10px 20px;
  border-radius: 30px;
  font-size: 13px;
  display: flex;
  align-items: center;
  gap: 10px;
  box-shadow: 0 4px 20px rgba(0, 0, 0, 0.15);
  border: 1px solid rgba(255, 255, 255, 0.1);
  font-weight: 500;
  letter-spacing: 0.5px;
  z-index: 100;
}

.memory-icon-wrapper {
  display: flex;
  align-items: center;
  justify-content: center;
  animation: breathe 2s ease-in-out infinite;
}

.memory-icon {
  width: 18px;
  height: 18px;
  color: #4CAF50;
}

@keyframes breathe {
  0%, 100% { opacity: 0.7; transform: scale(1); filter: drop-shadow(0 0 2px rgba(76, 175, 80, 0.3)); }
  50% { opacity: 1; transform: scale(1.15); filter: drop-shadow(0 0 8px rgba(76, 175, 80, 0.6)); }
}

/* 模拟结束后的提示样式 */
.graph-building-hint.finished-hint {
  background: rgba(0, 0, 0, 0.65);
  border: 1px solid rgba(255, 255, 255, 0.1);
}

.finished-hint .hint-icon-wrapper {
  display: flex;
  align-items: center;
  justify-content: center;
}

.finished-hint .hint-icon {
  width: 18px;
  height: 18px;
  color: #FFF;
}

.finished-hint .hint-text {
  flex: 1;
  white-space: nowrap;
}

.hint-close-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 22px;
  height: 22px;
  background: rgba(255, 255, 255, 0.2);
  border: none;
  border-radius: 50%;
  cursor: pointer;
  color: #FFF;
  transition: all 0.2s;
  margin-left: 8px;
  flex-shrink: 0;
}

.hint-close-btn:hover {
  background: rgba(255, 255, 255, 0.35);
  transform: scale(1.1);
}

/* Loading spinner */
.loading-spinner {
  width: 40px;
  height: 40px;
  border: 3px solid #E0E0E0;
  border-top-color: #7B2D8E;
  border-radius: 50%;
  animation: spin 1s linear infinite;
  margin: 0 auto 16px;
}

/* Self-loop styles */
.self-loop-header {
  display: flex;
  align-items: center;
  gap: 8px;
  background: linear-gradient(135deg, #E8F5E9 0%, #F1F8E9 100%);
  border: 1px solid #C8E6C9;
}

.self-loop-count {
  margin-left: auto;
  font-size: 11px;
  color: #666;
  background: rgba(255,255,255,0.8);
  padding: 2px 8px;
  border-radius: 10px;
}

.self-loop-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.self-loop-item {
  background: #FAFAFA;
  border: 1px solid #EAEAEA;
  border-radius: 8px;
}

.self-loop-item-header {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 12px;
  background: #F5F5F5;
  cursor: pointer;
  transition: background 0.2s;
}

.self-loop-item-header:hover {
  background: #EEEEEE;
}

.self-loop-item.expanded .self-loop-item-header {
  background: #E8E8E8;
}

.self-loop-index {
  font-size: 10px;
  font-weight: 600;
  color: #888;
  background: #E0E0E0;
  padding: 2px 6px;
  border-radius: 4px;
}

.self-loop-name {
  font-size: 12px;
  font-weight: 500;
  color: #333;
  flex: 1;
}

.self-loop-toggle {
  width: 20px;
  height: 20px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 14px;
  font-weight: 600;
  color: #888;
  background: #E0E0E0;
  border-radius: 4px;
  transition: all 0.2s;
}

.self-loop-item.expanded .self-loop-toggle {
  background: #D0D0D0;
  color: #666;
}

.self-loop-item-content {
  padding: 12px;
  border-top: 1px solid #EAEAEA;
}

.self-loop-item-content .detail-row {
  margin-bottom: 8px;
}

.self-loop-item-content .detail-label {
  font-size: 11px;
  min-width: 60px;
}

.self-loop-item-content .detail-value {
  font-size: 12px;
}

.self-loop-episodes {
  margin-top: 8px;
}

.episodes-list.compact {
  flex-direction: row;
  flex-wrap: wrap;
  gap: 4px;
}

.episode-tag.small {
  padding: 3px 6px;
  font-size: 9px;
}

@media (max-width: 1200px) {
  .panel-header {
    gap: 12px;
    flex-direction: column;
    align-items: stretch;
  }

  .header-controls {
    width: 100%;
    flex-direction: column;
    align-items: stretch;
  }

  .entity-controls {
    width: 100%;
    flex-wrap: wrap;
  }

  .entity-select,
  .entity-search-input {
    width: 100%;
    max-width: none;
  }

  .header-tools {
    justify-content: flex-end;
  }

  .search-status {
    top: 126px;
    max-width: calc(100% - 40px);
  }

  .edge-labels-toggle {
    top: 164px;
  }
}

@media (max-width: 768px) {
  .panel-header {
    padding: 14px 14px 10px;
  }

  .search-status {
    left: 14px;
    right: 14px;
    max-width: none;
  }

  .graph-legend {
    left: 14px;
    bottom: 14px;
    max-width: calc(100% - 28px);
  }

  .edge-labels-toggle {
    left: 14px;
    right: auto;
    top: 196px;
  }
}
</style>



