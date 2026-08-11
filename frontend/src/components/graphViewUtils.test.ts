import { describe, expect, it } from 'vitest';

import {
  GraphNode,
  GraphOverview,
  collideRadius,
  maxDegree,
  nodeAtPoint,
  nodeLabelEl,
  nodeRadius,
  toForceGraphData,
} from './graphViewUtils';

describe('toForceGraphData', () => {
  it('keeps nodes and maps edges to links', () => {
    const overview: GraphOverview = {
      nodes: [
        { id: 'a', name: 'A', degree: 2 },
        { id: 'b', name: 'B', degree: 1 },
      ],
      edges: [{ source: 'a', target: 'b', type: 'rel', weight: 1 }],
    };
    const data = toForceGraphData(overview);
    expect(data.nodes).toHaveLength(2);
    expect(data.links).toEqual([
      { source: 'a', target: 'b', type: 'rel', weight: 1 },
    ]);
  });

  it('drops edges that reference nodes outside the bounded set', () => {
    const overview: GraphOverview = {
      nodes: [{ id: 'a', name: 'A', degree: 1 }],
      edges: [{ source: 'a', target: 'ghost' }],
    };
    const data = toForceGraphData(overview);
    expect(data.links).toEqual([]);
  });

  it('handles an empty graph', () => {
    const data = toForceGraphData({ nodes: [], edges: [] });
    expect(data).toEqual({ nodes: [], links: [] });
  });
});

describe('maxDegree', () => {
  it('returns the highest degree', () => {
    expect(
      maxDegree([
        { id: 'a', name: 'A', degree: 3 },
        { id: 'b', name: 'B', degree: 7 },
      ]),
    ).toBe(7);
  });

  it('returns 0 for an empty list', () => {
    expect(maxDegree([])).toBe(0);
  });
});

describe('nodeLabelEl', () => {
  it('renders an untrusted name as text, not live HTML', () => {
    const payload = '<img src=x onerror=alert(1)>';
    const el = nodeLabelEl(payload);
    expect(el.textContent).toBe(payload);
    expect(el.querySelector('img')).toBeNull();
    expect(el.innerHTML).not.toContain('<img');
  });

  it('handles a missing name', () => {
    expect(nodeLabelEl('').textContent).toBe('');
  });
});

describe('nodeRadius', () => {
  it('returns the minimum radius when there is no spread', () => {
    expect(nodeRadius(0, 0)).toBe(3);
  });

  it('scales monotonically with degree', () => {
    const low = nodeRadius(1, 10);
    const high = nodeRadius(9, 10);
    expect(high).toBeGreaterThan(low);
    expect(nodeRadius(10, 10)).toBeCloseTo(12);
  });
});

describe('collideRadius', () => {
  it('pads beyond the visual radius so centres stay apart', () => {
    const visual = nodeRadius(3, 57);
    expect(collideRadius(visual)).toBeGreaterThan(visual);
  });
});

describe('nodeAtPoint', () => {
  const node = (
    id: string,
    x: number | null,
    y: number | null,
    degree = 1,
  ): GraphNode => ({ id, name: id, degree, x, y }) as GraphNode;

  it('returns the node when the point is inside its hit radius', () => {
    const nodes = [node('a', 0, 0)];
    const hit = nodeAtPoint(nodes, 2, 0, 1, 4);
    expect(hit?.id).toBe('a');
  });

  it('returns null when the point is outside the hit radius', () => {
    const nodes = [node('a', 0, 0)];
    expect(nodeAtPoint(nodes, 100, 100, 1, 4)).toBeNull();
  });

  it('resolves overlaps to the node with the nearest centre', () => {
    const nodes = [node('far', 5, 0), node('near', 1, 0)];
    const hit = nodeAtPoint(nodes, 1.2, 0, 1, 6);
    expect(hit?.id).toBe('near');
  });

  it('skips nodes with null coordinates', () => {
    const nodes = [node('ghost', null, null), node('real', 0, 0)];
    const hit = nodeAtPoint(nodes, 0, 0, 1, 4);
    expect(hit?.id).toBe('real');
  });

  it('respects the slop allowance', () => {
    const nodes = [node('a', 0, 0)]; // radius 3 at degree/max 1/1 => 12
    const r = nodeRadius(1, 1);
    expect(nodeAtPoint(nodes, r + 1, 0, 1, 2)?.id).toBe('a');
    expect(nodeAtPoint(nodes, r + 3, 0, 1, 2)).toBeNull();
  });
});
