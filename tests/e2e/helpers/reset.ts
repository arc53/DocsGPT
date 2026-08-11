/**
 * Per-test TRUNCATE — preserves `alembic_version`, wipes every other table.
 */

import { readFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import { dirname, resolve } from 'node:path';
import { pg } from './db.js';

const HERE = dirname(fileURLToPath(import.meta.url));
const TRUNCATE_SQL_PATH = resolve(HERE, '..', '..', '..', 'scripts', 'e2e', 'truncate.sql');

let cached: string | null = null;

async function loadTruncateSql(): Promise<string> {
  if (cached === null) {
    cached = await readFile(TRUNCATE_SQL_PATH, 'utf8');
  }
  return cached;
}

/**
 * Run `scripts/e2e/truncate.sql` against the e2e DB. Call from `beforeEach` to
 * guarantee per-test isolation. Cheaper than template-cloning — that's the
 * between-suites path handled by `up.sh` / `reset_db.sh`.
 */
export async function resetDb(): Promise<void> {
  const sql = await loadTruncateSql();
  await pg.query(sql);
}
