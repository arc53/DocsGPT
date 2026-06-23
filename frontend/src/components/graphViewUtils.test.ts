import { describe, expect, it } from 'vitest';

import {
  GraphOverview,
  collideRadius,
  maxDegree,
  nodeLabelEl,
  nodeRadius,
  pointerAreaRadius,
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

describe('pointerAreaRadius', () => {
  it('enforces a forgiving minimum hit target for small nodes', () => {
    const smallest = nodeRadius(0, 0);
    expect(pointerAreaRadius(smallest)).toBe(9);
  });

  it('always pads beyond the visual radius for larger nodes', () => {
    const largest = nodeRadius(10, 10);
    expect(pointerAreaRadius(largest)).toBeGreaterThan(largest);
    expect(pointerAreaRadius(largest)).toBeCloseTo(14);
  });
});

describe('collideRadius', () => {
  it('keeps centres farther apart than any node could be picked', () => {
    // The picking guarantee: with forceCollide(collideRadius), two centres
    // are >= 2*collideRadius apart, which must exceed the largest pick disc
    // so a centre is never covered by a neighbour's pick disc.
    const smallVisual = nodeRadius(0, 0);
    const largeVisual = nodeRadius(10, 10);
    const minCentreSpacing = 2 * collideRadius(smallVisual);
    expect(minCentreSpacing).toBeGreaterThan(pointerAreaRadius(largeVisual));
  });

  it('always exceeds the pick disc for the same node', () => {
    const visual = nodeRadius(3, 57);
    expect(collideRadius(visual)).toBeGreaterThan(pointerAreaRadius(visual));
  });
});
