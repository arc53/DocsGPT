export interface GraphRAGSummary {
  nodes: number;
  edges: number;
  chunksProcessed: number;
  skippedOverCap: number;
  failedChunks: number;
}

export type GraphRAGStart =
  | { status: 'enabled' }
  | { status: 'task'; taskId: string }
  | { status: 'forbidden' }
  | { status: 'conflict'; message?: string }
  | { status: 'error'; message?: string };

export type GraphRAGPoll =
  | { status: 'pending' }
  | { status: 'done'; summary: GraphRAGSummary }
  | { status: 'failed'; message?: string };

interface GraphRAGService {
  enableGraphRAG: (sourceId: string, token: string | null) => Promise<Response>;
  getTaskStatus: (taskId: string, token: string | null) => Promise<Response>;
}

export async function startGraphRAG(
  service: Pick<GraphRAGService, 'enableGraphRAG'>,
  sourceId: string,
  token: string | null,
): Promise<GraphRAGStart> {
  let response: Response;
  try {
    response = await service.enableGraphRAG(sourceId, token);
  } catch {
    return { status: 'error' };
  }
  const data = await response.json().catch(() => ({}));
  if (response.ok && data?.success) {
    if (data.task_id) return { status: 'task', taskId: data.task_id };
    return { status: 'enabled' };
  }
  if (response.status === 403) return { status: 'forbidden' };
  if (response.status === 409)
    return { status: 'conflict', message: data?.message };
  return { status: 'error', message: data?.message };
}

function parseSummary(result: unknown): GraphRAGSummary {
  const r = (result || {}) as Record<string, unknown>;
  return {
    nodes: Number(r.nodes) || 0,
    edges: Number(r.edges) || 0,
    chunksProcessed: Number(r.chunks_processed) || 0,
    skippedOverCap: Number(r.skipped_over_cap) || 0,
    failedChunks: Number(r.failed_chunks) || 0,
  };
}

export function interpretTaskStatus(
  status: string | undefined,
  result: unknown,
): GraphRAGPoll {
  if (status === 'SUCCESS')
    return { status: 'done', summary: parseSummary(result) };
  if (status === 'FAILURE') {
    const message =
      typeof result === 'string'
        ? result
        : ((result as Record<string, unknown>)?.message as string | undefined);
    return { status: 'failed', message };
  }
  return { status: 'pending' };
}

export async function pollTaskOnce(
  service: Pick<GraphRAGService, 'getTaskStatus'>,
  taskId: string,
  token: string | null,
): Promise<GraphRAGPoll> {
  let response: Response;
  try {
    response = await service.getTaskStatus(taskId, token);
  } catch {
    return { status: 'pending' };
  }
  if (!response.ok) return { status: 'pending' };
  const data = await response.json().catch(() => ({}));
  return interpretTaskStatus(data?.status, data?.result);
}
