/**
 * Phase 3 helper — upload / task_status polling primitives for Tier-B specs.
 *
 * These helpers wrap the two patterns that recur across B1/B3/B4/B5:
 *
 *   - POST /api/upload (multipart) and poll /api/task_status until terminal.
 *   - POST /api/remote (multipart form with JSON-string `data`) same pattern.
 *   - INSERT a fixture `sources` row directly, optionally pinned to a known
 *     UUID so it matches an on-disk faiss index (required for chunks tests).
 *
 * Known dev-stack caveat: the `ingest` worker saves the faiss index under a
 * worker-generated UUID, but the downstream `/api/upload_index` path calls
 * `SourcesRepository.create()` which mints its OWN UUID — so the DB row's
 * id doesn't match the faiss directory name. This doesn't affect the upload
 * happy-path (the `sources` row still exists), but it does mean that chunks
 * endpoints keyed on the DB id can't find the vectorstore. The
 * `findNewestIndexDir` helper below lets specs reconcile the two by reading
 * the filesystem, and `seedSourceWithId` lets them pin a sources row to
 * that directory UUID.
 */

import { readFile, readdir, stat } from 'node:fs/promises';
import { dirname, resolve as pathResolve } from 'node:path';
import { fileURLToPath } from 'node:url';

import type { APIRequestContext } from '@playwright/test';
import * as playwright from '@playwright/test';

import { pg } from './db.js';

const API_URL = process.env.API_URL ?? 'http://127.0.0.1:7099';

/**
 * Build an APIRequestContext with Bearer token but NO default Content-Type
 * header, so Playwright's multipart boundary on `post({ multipart })` is the
 * only Content-Type that reaches Flask. Mirrors the pattern in
 * `helpers/agents.ts::multipartAuthedRequest` — duplicated here so specs
 * can import from a single upload-focused module.
 */
export async function multipartContext(
  token: string,
): Promise<APIRequestContext> {
  return playwright.request.newContext({
    baseURL: API_URL,
    extraHTTPHeaders: {
      Authorization: `Bearer ${token}`,
    },
  });
}

/**
 * Shape of a /api/task_status response envelope. `result` may be a
 * task-specific dict, a progress dict, or an error string depending on
 * state — callers inspect `status` first.
 */
export interface TaskStatusBody {
  status: 'PENDING' | 'PROGRESS' | 'SUCCESS' | 'FAILURE' | string;
  // Celery meta — free-form, but our worker uses dict OR str for errors
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  result?: any;
}

/**
 * Poll /api/task_status until it reaches a terminal state (SUCCESS / FAILURE)
 * or the timeout elapses. Returns the final body. Throws on timeout.
 *
 * `timeoutMs` defaults to 45s to accommodate the first-time model-load on a
 * cold Celery worker (the SimpleDirectoryReader loads docling PDF pipeline
 * lazily). Subsequent invocations finish in ~1s.
 */
export async function waitForTask(
  api: APIRequestContext,
  taskId: string,
  timeoutMs: number = 45_000,
): Promise<TaskStatusBody> {
  const deadline = Date.now() + timeoutMs;
  let last: TaskStatusBody | null = null;
  while (Date.now() < deadline) {
    const res = await api.get(`/api/task_status?task_id=${taskId}`);
    if (res.status() === 200) {
      last = (await res.json()) as TaskStatusBody;
      if (last.status === 'SUCCESS' || last.status === 'FAILURE') {
        return last;
      }
    }
    await new Promise((r) => setTimeout(r, 500));
  }
  throw new Error(
    `waitForTask: ${taskId} did not terminate within ${timeoutMs}ms. Last status: ${
      last?.status ?? '<none>'
    }`,
  );
}

/**
 * POST /api/upload a single file as multipart. Returns the task_id.
 * `user` and `name` are required form fields per the backend route; the
 * `user` value is what the backend logs / derives the upload dir from, but
 * the authoritative owner is still the JWT `sub`.
 */
export async function postUpload(
  api: APIRequestContext,
  filePath: string,
  opts: { user: string; name: string; mimeType?: string; filename?: string },
): Promise<string> {
  const buffer = await readFile(filePath);
  const fallbackName = filePath.split('/').pop() ?? 'upload.bin';
  const displayName = opts.filename ?? fallbackName;
  const res = await api.post('/api/upload', {
    multipart: {
      user: opts.user,
      name: opts.name,
      file: {
        name: displayName,
        mimeType: opts.mimeType ?? 'application/octet-stream',
        buffer,
      },
    },
  });
  if (res.status() !== 200) {
    throw new Error(
      `POST /api/upload failed ${res.status()}: ${await res.text()}`,
    );
  }
  const body = (await res.json()) as { success: boolean; task_id: string };
  if (!body.success || !body.task_id) {
    throw new Error(`/api/upload returned unexpected body: ${JSON.stringify(body)}`);
  }
  return body.task_id;
}

/**
 * POST /api/remote with a form-encoded payload. `data` is JSON-encoded
 * because the backend parses `data['data']` with `json.loads` for the
 * url/crawler/github/reddit/s3 branches.
 */
export async function postRemote(
  api: APIRequestContext,
  opts: {
    user: string;
    name: string;
    source: string;
    data: Record<string, unknown>;
  },
): Promise<string> {
  const res = await api.post('/api/remote', {
    multipart: {
      user: opts.user,
      name: opts.name,
      source: opts.source,
      data: JSON.stringify(opts.data),
    },
  });
  if (res.status() !== 200) {
    throw new Error(
      `POST /api/remote failed ${res.status()}: ${await res.text()}`,
    );
  }
  const body = (await res.json()) as { success: boolean; task_id: string };
  if (!body.success || !body.task_id) {
    throw new Error(`/api/remote returned unexpected body: ${JSON.stringify(body)}`);
  }
  return body.task_id;
}

/**
 * Seed a `sources` row and return its PG-assigned id. Mirrors
 * `helpers/agents.ts::insertFixtureSource` but exposes every column a
 * Tier-B spec might realistically need to assert on (file_path,
 * file_name_map, remote_data, type, directory_structure).
 */
export async function seedSource(
  userId: string,
  opts: {
    name: string;
    type?: string;
    retriever?: string;
    filePath?: string;
    fileNameMap?: Record<string, string>;
    remoteData?: Record<string, unknown>;
    directoryStructure?: Record<string, unknown>;
    syncFrequency?: string;
  },
): Promise<string> {
  const { rows } = await pg.query<{ id: string }>(
    `INSERT INTO sources (
       user_id, name, date, retriever, type, file_path,
       file_name_map, remote_data, directory_structure, sync_frequency
     )
     VALUES (
       $1, $2, now(), $3, $4, $5,
       CAST($6 AS jsonb), CAST($7 AS jsonb), CAST($8 AS jsonb), $9
     )
     RETURNING id::text AS id`,
    [
      userId,
      opts.name,
      opts.retriever ?? 'classic',
      opts.type ?? 'local',
      opts.filePath ?? null,
      opts.fileNameMap ? JSON.stringify(opts.fileNameMap) : null,
      opts.remoteData ? JSON.stringify(opts.remoteData) : null,
      opts.directoryStructure ? JSON.stringify(opts.directoryStructure) : null,
      opts.syncFrequency ?? null,
    ],
  );
  const id = rows[0]?.id;
  if (!id) {
    throw new Error('seedSource: INSERT returned no id');
  }
  return id;
}

/**
 * Same as `seedSource` but pins the row to a caller-provided UUID. Used by
 * chunks specs to align the DB id with an existing `indexes/<uuid>/`
 * directory written by a prior /api/upload call.
 */
export async function seedSourceWithId(
  sourceId: string,
  userId: string,
  opts: { name: string; type?: string; retriever?: string; filePath?: string },
): Promise<void> {
  await pg.query(
    `INSERT INTO sources (id, user_id, name, date, retriever, type, file_path)
     VALUES (CAST($1 AS uuid), $2, $3, now(), $4, $5, $6)`,
    [
      sourceId,
      userId,
      opts.name,
      opts.retriever ?? 'classic',
      opts.type ?? 'local',
      opts.filePath ?? null,
    ],
  );
}

/**
 * Return the `indexes/<uuid>` directory with the newest `index.faiss`
 * mtime. Used by chunks specs after an /api/upload to locate the freshly
 * minted faiss dir (see module-level caveat about DB-id ↔ faiss-dir-id
 * mismatch).
 *
 * The `indexes/` directory is resolved against the repository root
 * (LocalStorage.base_dir = repo root by default — see
 * `application/storage/local.py:19-21`). Returns null if no recent entry
 * matches the `minMtimeMs` floor.
 */
export async function findNewestIndexDir(
  minMtimeMs: number = 0,
): Promise<string | null> {
  // tests/e2e/helpers/uploads.ts → ../../../ → repo root. Use
  // `fileURLToPath` so that path segments containing spaces (e.g. under a
  // Dropbox folder) don't come back URL-encoded as `%20`.
  const here = dirname(fileURLToPath(import.meta.url));
  const repoRoot = pathResolve(here, '..', '..', '..');
  const indexesRoot = pathResolve(repoRoot, 'indexes');
  let entries: string[];
  try {
    entries = await readdir(indexesRoot);
  } catch {
    return null;
  }
  let best: { id: string; mtimeMs: number } | null = null;
  for (const entry of entries) {
    const faissPath = pathResolve(indexesRoot, entry, 'index.faiss');
    try {
      const s = await stat(faissPath);
      if (s.mtimeMs < minMtimeMs) continue;
      if (!best || s.mtimeMs > best.mtimeMs) {
        best = { id: entry, mtimeMs: s.mtimeMs };
      }
    } catch {
      // missing index.faiss — skip
    }
  }
  return best?.id ?? null;
}
