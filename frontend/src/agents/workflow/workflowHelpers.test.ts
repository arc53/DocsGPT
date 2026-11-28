import { describe, expect, it } from 'vitest';

import { aiDecisionErrors, findFreePosition } from './workflowHelpers';

const box = (id: string, x: number, y: number, width = 200, height = 60) => ({
  id,
  position: { x, y },
  width,
  height,
});

describe('findFreePosition', () => {
  it('keeps the wanted spot when nothing is there', () => {
    expect(findFreePosition([box('a', 0, 0)], { x: 400, y: 0 })).toEqual({
      x: 400,
      y: 0,
    });
  });

  it('moves down past a node that covers the spot', () => {
    const spot = findFreePosition([box('a', 380, 0)], { x: 400, y: 0 });
    expect(spot.x).toBe(400);
    expect(spot.y).toBeGreaterThanOrEqual(60 + 24);
  });

  it('keeps moving down past a column of nodes', () => {
    const nodes = [box('a', 400, 0), box('b', 400, 84), box('c', 400, 168)];
    const spot = findFreePosition(nodes, { x: 400, y: 0 });
    expect(spot.y).toBeGreaterThanOrEqual(168 + 60 + 24);
  });

  it('uses a default size for nodes React Flow has not measured yet', () => {
    const spot = findFreePosition([{ id: 'a', position: { x: 400, y: 0 } }], {
      x: 450,
      y: 10,
    });
    expect(spot.y).toBeGreaterThan(10);
  });
});

describe('aiDecisionErrors', () => {
  const t = ((key: string) => key) as unknown as Parameters<
    typeof aiDecisionErrors
  >[0];
  const branch = (name: string, i: number) => ({
    name,
    expression: '',
    sourceHandle: `case_${i}`,
  });

  it('accepts distinct names and a confidence from 0 to 1', () => {
    expect(
      aiDecisionErrors(
        t,
        'Route',
        [branch('Billing', 0), branch('Support', 1)],
        0.6,
      ),
    ).toEqual([]);
  });

  it('rejects other, a repeated name, too many branches and a bad confidence', () => {
    const many = Array.from({ length: 16 }, (_, i) => branch(`b${i}`, i));
    expect(
      aiDecisionErrors(
        t,
        'Route',
        [branch('Other', 0), branch('Billing', 1), branch('billing', 2)],
        2,
      ),
    ).toEqual([
      'agents.workflow.validation.aiReservedName',
      'agents.workflow.validation.aiDuplicateName',
      'agents.workflow.validation.aiMinConfidence',
    ]);
    expect(aiDecisionErrors(t, 'Route', many)).toEqual([
      'agents.workflow.validation.aiTooManyBranches',
    ]);
  });
});
