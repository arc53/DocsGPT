export interface GraphTokenEstimate {
  chunks: number;
  lo: number;
  hi: number;
}

const DEFAULT_CHUNK_MAX_TOKENS = 1250;
const TOKENS_PER_CHUNK_LO = 2500;
const TOKENS_PER_CHUNK_HI = 4000;

/**
 * Estimate the token cost of GraphRAG extraction before it runs. Extraction
 * makes ~1 LLM call per chunk; measured calls land at ~2.5k–4k tokens each
 * (roughly half input, half output), so the range scales with the chunk count.
 */
export function estimateGraphTokens(
  sourceTokens: number,
  chunkMaxTokens: number = DEFAULT_CHUNK_MAX_TOKENS,
): GraphTokenEstimate {
  const tokens = Number.isFinite(sourceTokens) ? Math.max(0, sourceTokens) : 0;
  const perChunk =
    Number.isFinite(chunkMaxTokens) && chunkMaxTokens > 0
      ? chunkMaxTokens
      : DEFAULT_CHUNK_MAX_TOKENS;
  const chunks = Math.max(1, Math.ceil(tokens / perChunk));
  return {
    chunks,
    lo: TOKENS_PER_CHUNK_LO * chunks,
    hi: TOKENS_PER_CHUNK_HI * chunks,
  };
}

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
  // Transient (network throw / non-2xx). Distinct from 'pending' so a caller
  // can bound consecutive errors instead of polling a dead backend forever.
  | { status: 'error' }
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
    return { status: 'error' };
  }
  if (!response.ok) return { status: 'error' };
  const data = await response.json().catch(() => ({}));
  return interpretTaskStatus(data?.status, data?.result);
}
