import service, { requestWithRetry } from './index'

/**
 * 鐢熸垚鏈綋锛堜笂浼犳枃妗ｅ拰妯℃嫙闇€姹傦級
 * @param {Object} data - 鍖呭惈files, simulation_requirement, project_name绛?
 * @returns {Promise}
 */
export function generateOntology(formData) {
  return requestWithRetry(() => 
    service({
      url: '/api/graph/ontology/generate',
      method: 'post',
      data: formData,
      headers: {
        'Content-Type': 'multipart/form-data'
      }
    })
  )
}

/**
 * 鏋勫缓鍥捐氨
 * @param {Object} data - 鍖呭惈project_id, graph_name绛?
 * @returns {Promise}
 */
export function buildGraph(data) {
  return requestWithRetry(() =>
    service({
      url: '/api/graph/build',
      method: 'post',
      data
    })
  )
}

/**
 * 鏌ヨ浠诲姟鐘舵€?
 * @param {String} taskId - 浠诲姟ID
 * @returns {Promise}
 */
export function getTaskStatus(taskId) {
  return service({
    url: `/api/graph/task/${taskId}`,
    method: 'get'
  })
}

/**
 * 鑾峰彇鍥捐氨鏁版嵁
 * @param {String} graphId - 鍥捐氨ID
 * @param {Object} params - 鏌ヨ鍙傛暟
 * @returns {Promise}
 */
export function getGraphData(graphId, params = {}) {
  return service({
    url: `/api/graph/data/${graphId}`,
    method: 'get',
    params
  })
}

/**
 * 鑾峰彇鍥捐氨瀹炰綋鍊欓€? * @param {String} graphId - 鍥捐氨ID
 * @param {Object} params - 鏌ヨ鍙傛暟
 * @returns {Promise}
 */
export function getGraphEntities(graphId, params = {}) {
  return service({
    url: `/api/graph/entities/${graphId}`,
    method: 'get',
    params
  })
}

/**
 * 鑾峰彇瀹炰綋鑱氱劍瀛愬浘
 * @param {String} graphId - 鍥捐氨ID
 * @param {Object} params - 鏌ヨ鍙傛暟
 * @returns {Promise}
 */
export function getFocusedGraphData(graphId, params = {}) {
  return service({
    url: `/api/graph/data/${graphId}/focus`,
    method: 'get',
    params
  })
}

export function getExpandedGraphData(graphId, params = {}) {
  return service({
    url: `/api/graph/data/${graphId}/expand`,
    method: 'get',
    params
  })
}

/**
 * 鑾峰彇椤圭洰淇℃伅
 * @param {String} projectId - 椤圭洰ID
 * @returns {Promise}
 */
export function getProject(projectId) {
  return service({
    url: `/api/graph/project/${projectId}`,
    method: 'get'
  })
}


