/**
 * Phase 1 helper — see e2e-plan.md §P1-B.
 * Thin pg wrapper + typed row helpers for DB assertions in specs.
 */

import pgPkg from 'pg';

const { Pool } = pgPkg;

const DEFAULT_URI =
  process.env.POSTGRES_URI ??
  'postgresql://docsgpt:docsgpt@127.0.0.1:5432/docsgpt_e2e';

// Cap at 2: specs run serially (workers: 1) so one live + one spare is plenty,
// and we must not starve Flask's own pool on the shared Postgres instance.
const pool = new Pool({ connectionString: DEFAULT_URI, max: 2 });

/**
 * Thin wrapper over the pg pool. Always parameterized — callers pass `$1, $2, …`
 * in `sql` and the values in `params`. No string interpolation anywhere.
 */
export const pg = {
  async query<T = Record<string, unknown>>(
    sql: string,
    params?: unknown[],
  ): Promise<{ rows: T[] }> {
    const res = params === undefined
      ? await pool.query(sql)
      : await pool.query(sql, params as unknown[]);
    return { rows: res.rows as T[] };
  },
  async close(): Promise<void> {
    await pool.end();
  },
};

const SAFE_IDENT = /^[a-z_][a-z_0-9]*$/;

function assertSafeTable(table: string): void {
  if (!SAFE_IDENT.test(table)) {
    throw new Error(
      `countRows: refusing unsafe table identifier ${JSON.stringify(table)}`,
    );
  }
}

/**
 * Return the row count for a table, optionally filtered by a parameterized
 * WHERE clause (caller supplies `sql` like `"user_id = $1"` and matching
 * `params`). `table` is whitelisted against `/^[a-z_][a-z_0-9]*$/`.
 */
export async function countRows(
  table: string,
  where?: { sql: string; params?: unknown[] },
): Promise<number> {
  assertSafeTable(table);
  const whereClause = where?.sql ? ` WHERE ${where.sql}` : '';
  const { rows } = await pg.query<{ n: string }>(
    `SELECT count(*)::text AS n FROM ${table}${whereClause}`,
    where?.params,
  );
  return Number(rows[0]?.n ?? 0);
}

/**
 * Shape of a row in `public.users` (Alembic 0001_initial). `agent_preferences`
 * is JSONB — pg returns it as a parsed JS value.
 */
export interface UserRow {
  id: string;
  user_id: string;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  agent_preferences: any;
}

/**
 * Look up a user row by the external `user_id` (JWT `sub`). Returns null if
 * `ensure_user_doc` hasn't fired yet — useful for asserting first-touch upsert
 * behavior.
 */
export async function getUserRow(userId: string): Promise<UserRow | null> {
  const { rows } = await pg.query<UserRow>(
    'SELECT id, user_id, agent_preferences FROM users WHERE user_id = $1',
    [userId],
  );
  return rows[0] ?? null;
}
