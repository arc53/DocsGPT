export interface SkippedFile {
  file: string;
  reason: string;
}

export interface ConvertSummary {
  pagesCreated: number;
  skipped: SkippedFile[];
}

export type ConvertStart =
  | { status: 'enabled' }
  | { status: 'task'; taskId: string }
  | { status: 'forbidden' }
  | { status: 'conflict'; message?: string }
  | { status: 'error'; message?: string };

export type ConvertPoll =
  | { status: 'pending' }
  | { status: 'done'; summary: ConvertSummary }
  | { status: 'failed'; message?: string };

interface ConvertService {
  convertToWiki: (sourceId: string, token: string | null) => Promise<Response>;
  getTaskStatus: (taskId: string, token: string | null) => Promise<Response>;
}

export async function startWikiConversion(
  service: Pick<ConvertService, 'convertToWiki'>,
  sourceId: string,
  token: string | null,
): Promise<ConvertStart> {
  let response: Response;
  try {
    response = await service.convertToWiki(sourceId, token);
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

function parseSummary(result: unknown): ConvertSummary {
  const r = (result || {}) as Record<string, unknown>;
  const skipped = Array.isArray(r.skipped) ? (r.skipped as SkippedFile[]) : [];
  return {
    pagesCreated: Number(r.pages_created) || 0,
    skipped,
  };
}

export function interpretTaskStatus(
  status: string | undefined,
  result: unknown,
): ConvertPoll {
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
  service: Pick<ConvertService, 'getTaskStatus'>,
  taskId: string,
  token: string | null,
): Promise<ConvertPoll> {
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
