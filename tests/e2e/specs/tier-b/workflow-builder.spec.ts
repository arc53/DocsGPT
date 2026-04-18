/**
 * Phase 3 Tier-B · workflow builder (nodes / edges / versioning)
 *
 * Covers B13: `POST /api/workflows`, `GET /api/workflows/:id`,
 * `PUT /api/workflows/:id`, `DELETE /api/workflows/:id`, and the
 * validate_workflow_structure negative cases that live in
 * application/api/user/workflows/routes.py (missing start, duplicate case
 * handles, condition without else).
 *
 * Contract quirks discovered while writing this spec:
 *   - The create route returns HTTP 200 with body
 *     `{"data":{"id":"<uuid>"},"message":201,"success":true}` — i.e.
 *     `success_response({"id": ...}, 201)` maps the second positional
 *     arg to `message`, not the HTTP status (see
 *     application/api/user/utils.py:39-48). The route uses the shape
 *     "success + data.id" — we assert on those, not on 201.
 *   - The PUT route DELETES other graph versions after writing the new
 *     one (WorkflowNodesRepository.delete_other_versions). The brief
 *     said "prior version retained until pruned" — the current
 *     implementation prunes immediately inside the same transaction, so
 *     we assert only the post-PUT invariants: (a) `current_graph_version`
 *     bumped, (b) only the new version's nodes/edges survive.
 *   - On validation failure the response is 400 with
 *     `{"success":false,"error":"Workflow validation failed","errors":[...]}`.
 */

import * as playwright from '@playwright/test';
const { expect, test } = playwright;

import { authedRequest } from '../../helpers/api.js';
import { newUserContext } from '../../helpers/auth.js';
import { pg } from '../../helpers/db.js';
import { resetDb } from '../../helpers/reset.js';

interface WorkflowCreateOk {
  success: true;
  data: { id: string };
  message?: number | string;
}

interface WorkflowCreateErr {
  success: false;
  error: string;
  errors?: string[];
}

interface WorkflowGetOk {
  success: true;
  data: {
    workflow: { id: string; name: string; description: string | null };
    nodes: Array<{ id: string; type: string; title?: string }>;
    edges: Array<{ id: string; source: string; target: string; sourceHandle?: string }>;
  };
}

/**
 * Minimal valid graph: start → end, one edge. The validator at
 * routes.py:201 requires exactly one start + at least one end + a
 * start-outgoing edge.
 */
function basicGraph() {
  return {
    nodes: [
      { id: 'start-1', type: 'start', title: 'Start' },
      { id: 'end-1', type: 'end', title: 'End' },
    ],
    edges: [{ id: 'e-1', source: 'start-1', target: 'end-1' }],
  };
}

/** Count rows in workflow_nodes / workflow_edges for a workflow. */
async function countGraph(workflowId: string): Promise<{ nodes: number; edges: number }> {
  const { rows: nodeRows } = await pg.query<{ n: string }>(
    `SELECT count(*)::text AS n FROM workflow_nodes WHERE workflow_id = CAST($1 AS uuid)`,
    [workflowId],
  );
  const { rows: edgeRows } = await pg.query<{ n: string }>(
    `SELECT count(*)::text AS n FROM workflow_edges WHERE workflow_id = CAST($1 AS uuid)`,
    [workflowId],
  );
  return {
    nodes: Number(nodeRows[0]?.n ?? 0),
    edges: Number(edgeRows[0]?.n ?? 0),
  };
}

async function fetchWorkflow(workflowId: string): Promise<{
  id: string;
  user_id: string;
  name: string;
  current_graph_version: number;
} | null> {
  const { rows } = await pg.query<{
    id: string;
    user_id: string;
    name: string;
    current_graph_version: number;
  }>(
    `SELECT id::text AS id, user_id, name, current_graph_version
       FROM workflows WHERE id = CAST($1 AS uuid)`,
    [workflowId],
  );
  return rows[0] ?? null;
}

test.describe('tier-b · workflow builder', () => {
  test.beforeEach(async () => {
    await resetDb();
  });

  test('create: POST /api/workflows writes workflows, workflow_nodes, and workflow_edges rows', async ({
    browser,
  }) => {
    const { context, sub, token } = await newUserContext(browser);
    const api = await authedRequest(playwright, token);
    try {
      const { nodes, edges } = basicGraph();
      const res = await api.post('/api/workflows', {
        data: { name: 'my wf', description: 'd', nodes, edges },
      });
      expect(
        res.status(),
        `POST /api/workflows expected 200, got ${res.status()} ${await res.text()}`,
      ).toBe(200);
      const body = (await res.json()) as WorkflowCreateOk;
      expect(body.success).toBe(true);
      const workflowId = body.data.id;
      expect(workflowId).toMatch(
        /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i,
      );

      // DB: one workflows row + 2 nodes + 1 edge.
      const row = await fetchWorkflow(workflowId);
      expect(row).not.toBeNull();
      expect(row!.user_id).toBe(sub);
      expect(row!.name).toBe('my wf');
      expect(row!.current_graph_version).toBe(1);

      const counts = await countGraph(workflowId);
      expect(counts.nodes).toBe(2);
      expect(counts.edges).toBe(1);
    } finally {
      await api.dispose();
      await context.close();
    }
  });

  test('fetch: GET /api/workflows/:id returns the graph in the expected shape', async ({
    browser,
  }) => {
    const { context, token } = await newUserContext(browser);
    const api = await authedRequest(playwright, token);
    try {
      const { nodes, edges } = basicGraph();
      const createRes = await api.post('/api/workflows', {
        data: { name: 'fetchable', nodes, edges },
      });
      const { data: { id: workflowId } } = (await createRes.json()) as WorkflowCreateOk;

      const getRes = await api.get(`/api/workflows/${workflowId}`);
      expect(
        getRes.status(),
        `GET /api/workflows/:id expected 200, got ${getRes.status()} ${await getRes.text()}`,
      ).toBe(200);
      const body = (await getRes.json()) as WorkflowGetOk;
      expect(body.success).toBe(true);
      expect(body.data.workflow.id).toBe(workflowId);
      expect(body.data.workflow.name).toBe('fetchable');

      const nodeIds = body.data.nodes.map((n) => n.id).sort();
      expect(nodeIds).toEqual(['end-1', 'start-1']);
      expect(body.data.edges).toHaveLength(1);
      expect(body.data.edges[0]).toMatchObject({
        id: 'e-1',
        source: 'start-1',
        target: 'end-1',
      });
    } finally {
      await api.dispose();
      await context.close();
    }
  });

  test('update: PUT /api/workflows/:id bumps current_graph_version and replaces the graph', async ({
    browser,
  }) => {
    const { context, token } = await newUserContext(browser);
    const api = await authedRequest(playwright, token);
    try {
      const v1 = basicGraph();
      const createRes = await api.post('/api/workflows', {
        data: { name: 'v1', nodes: v1.nodes, edges: v1.edges },
      });
      const { data: { id: workflowId } } = (await createRes.json()) as WorkflowCreateOk;
      expect((await fetchWorkflow(workflowId))!.current_graph_version).toBe(1);

      // v2: add an intermediate node so row counts change.
      const v2Nodes = [
        { id: 'start-1', type: 'start', title: 'Start' },
        { id: 'mid-1', type: 'end', title: 'Mid-end' },
        { id: 'end-1', type: 'end', title: 'End' },
      ];
      const v2Edges = [
        { id: 'e-a', source: 'start-1', target: 'mid-1' },
        { id: 'e-b', source: 'start-1', target: 'end-1' },
      ];
      const putRes = await api.put(`/api/workflows/${workflowId}`, {
        data: { name: 'v2', description: 'updated', nodes: v2Nodes, edges: v2Edges },
      });
      expect(
        putRes.status(),
        `PUT expected 200, got ${putRes.status()} ${await putRes.text()}`,
      ).toBe(200);

      // workflows row: name + current_graph_version updated.
      const row = await fetchWorkflow(workflowId);
      expect(row!.name).toBe('v2');
      expect(row!.current_graph_version).toBe(2);

      // Node/edge counts now reflect v2 (prior version is pruned by the
      // `delete_other_versions` sweep that runs after the new write).
      const counts = await countGraph(workflowId);
      expect(counts.nodes).toBe(3);
      expect(counts.edges).toBe(2);

      // Fetch shows v2's node ids.
      const getRes = await api.get(`/api/workflows/${workflowId}`);
      const body = (await getRes.json()) as WorkflowGetOk;
      expect(body.data.nodes.map((n) => n.id).sort()).toEqual([
        'end-1',
        'mid-1',
        'start-1',
      ]);
    } finally {
      await api.dispose();
      await context.close();
    }
  });

  test('negative: workflow without a start node returns 400', async ({ browser }) => {
    const { context, token } = await newUserContext(browser);
    const api = await authedRequest(playwright, token);
    try {
      const res = await api.post('/api/workflows', {
        data: {
          name: 'no start',
          nodes: [{ id: 'end-1', type: 'end' }],
          edges: [],
        },
      });
      expect(res.status()).toBe(400);
      const body = (await res.json()) as WorkflowCreateErr;
      expect(body.success).toBe(false);
      expect(body.error).toBe('Workflow validation failed');
      expect(body.errors ?? []).toEqual(
        expect.arrayContaining([
          expect.stringContaining('exactly one start node'),
        ]),
      );

      // No rows created.
      const { rows } = await pg.query<{ n: string }>(
        `SELECT count(*)::text AS n FROM workflows`,
      );
      expect(Number(rows[0]!.n)).toBe(0);
    } finally {
      await api.dispose();
      await context.close();
    }
  });

  test('negative: condition node without an else branch returns 400', async ({
    browser,
  }) => {
    const { context, token } = await newUserContext(browser);
    const api = await authedRequest(playwright, token);
    try {
      const nodes = [
        { id: 's', type: 'start' },
        {
          id: 'c',
          type: 'condition',
          data: { cases: [{ sourceHandle: 'a', expression: 'x > 0' }] },
        },
        { id: 'e', type: 'end' },
      ];
      const edges = [
        { id: 'e1', source: 's', target: 'c' },
        { id: 'e2', source: 'c', target: 'e', sourceHandle: 'a' },
      ];

      const res = await api.post('/api/workflows', {
        data: { name: 'no else', nodes, edges },
      });
      expect(res.status()).toBe(400);
      const body = (await res.json()) as WorkflowCreateErr;
      expect(body.errors ?? []).toEqual(
        expect.arrayContaining([expect.stringContaining("'else' branch")]),
      );
    } finally {
      await api.dispose();
      await context.close();
    }
  });

  test('negative: duplicate condition-case handles return 400', async ({
    browser,
  }) => {
    const { context, token } = await newUserContext(browser);
    const api = await authedRequest(playwright, token);
    try {
      const nodes = [
        { id: 's', type: 'start' },
        {
          id: 'c',
          type: 'condition',
          data: {
            cases: [
              { sourceHandle: 'dup', expression: 'x > 0' },
              { sourceHandle: 'dup', expression: 'y > 0' },
            ],
          },
        },
        { id: 'e', type: 'end' },
      ];
      const edges = [
        { id: 'e1', source: 's', target: 'c' },
        { id: 'e2', source: 'c', target: 'e', sourceHandle: 'dup' },
        { id: 'e3', source: 'c', target: 'e', sourceHandle: 'else' },
      ];

      const res = await api.post('/api/workflows', {
        data: { name: 'dup handles', nodes, edges },
      });
      expect(res.status()).toBe(400);
      const body = (await res.json()) as WorkflowCreateErr;
      expect(body.errors ?? []).toEqual(
        expect.arrayContaining([
          expect.stringContaining("duplicate case handle 'dup'"),
        ]),
      );
    } finally {
      await api.dispose();
      await context.close();
    }
  });

  test('delete: DELETE /api/workflows/:id cascades nodes and edges', async ({
    browser,
  }) => {
    const { context, token } = await newUserContext(browser);
    const api = await authedRequest(playwright, token);
    try {
      const { nodes, edges } = basicGraph();
      const createRes = await api.post('/api/workflows', {
        data: { name: 'to delete', nodes, edges },
      });
      const { data: { id: workflowId } } = (await createRes.json()) as WorkflowCreateOk;

      expect((await countGraph(workflowId)).nodes).toBe(2);
      expect((await countGraph(workflowId)).edges).toBe(1);

      const delRes = await api.delete(`/api/workflows/${workflowId}`);
      expect(
        delRes.status(),
        `DELETE expected 200, got ${delRes.status()} ${await delRes.text()}`,
      ).toBe(200);

      // workflows row is gone.
      expect(await fetchWorkflow(workflowId)).toBeNull();

      // ON DELETE CASCADE scrubbed child rows (see 0001_initial.py:507, 527).
      const counts = await countGraph(workflowId);
      expect(counts.nodes).toBe(0);
      expect(counts.edges).toBe(0);
    } finally {
      await api.dispose();
      await context.close();
    }
  });
});
