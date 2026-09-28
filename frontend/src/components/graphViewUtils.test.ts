import { afterEach, describe, expect, it } from 'vitest';

import {
  GraphNode,
  GraphOverview,
  collideRadius,
  escapeDeselects,
  foldGraphTypes,
  graphTypeKey,
  groupRelationships,
  maxDegree,
  nodeAtPoint,
  nodeRadius,
  normalizeEdgeLabel,
  otherTypesList,
  readGraphPalette,
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

describe('readGraphPalette', () => {
  const tokens = [
    '--chart-1',
    '--chart-2',
    '--chart-3',
    '--chart-4',
    '--muted-foreground',
    '--primary',
    '--foreground',
    '--border',
    '--background',
    '--font-sans',
  ];
  afterEach(() =>
    tokens.forEach((name) => document.body.style.removeProperty(name)),
  );

  it('maps the type series, Other, links, labels, halo and font onto the theme tokens', () => {
    document.body.style.setProperty('--chart-1', '#8855f1');
    document.body.style.setProperty('--chart-2', '#60a5fa');
    document.body.style.setProperty('--chart-3', '#22c55e');
    document.body.style.setProperty('--chart-4', '#facc15');
    document.body.style.setProperty('--muted-foreground', '#a1a1a1');
    document.body.style.setProperty('--primary', '#8855f1');
    document.body.style.setProperty('--foreground', '#fafafa');
    document.body.style.setProperty('--border', '#44454c');
    document.body.style.setProperty('--background', '#222327');
    document.body.style.setProperty('--font-sans', 'Inter, sans-serif');
    expect(readGraphPalette()).toEqual({
      series: ['#8855f1', '#60a5fa', '#22c55e', '#facc15'],
      other: '#a1a1a1',
      primary: '#8855f1',
      hoverStroke: '#fafafa',
      link: '#44454c',
      label: '#fafafa',
      halo: '#222327',
      font: 'Inter, sans-serif',
    });
  });

  it('falls back to the light tokens, with grey (not chart-5 red) for Other', () => {
    expect(readGraphPalette()).toEqual({
      series: ['#7d54d1', '#2563eb', '#079455', '#ca8a04'],
      other: '#737373',
      primary: '#7d54d1',
      hoverStroke: '#171717',
      link: '#d9d9d9',
      label: '#171717',
      halo: '#ffffff',
      font: 'sans-serif',
    });
  });
});

describe('graphTypeKey', () => {
  it('lower-cases and drops everything but letters and digits', () => {
    expect(graphTypeKey('Service Lane')).toBe('servicelane');
    expect(graphTypeKey('ServiceLane')).toBe('servicelane');
    expect(graphTypeKey('PORT')).toBe('port');
    expect(graphTypeKey(null)).toBe('');
    expect(graphTypeKey(undefined)).toBe('');
  });
});

describe('foldGraphTypes', () => {
  const nodes = [
    ...Array.from({ length: 5 }, () => ({ type: 'Person' })),
    { type: 'PERSON' },
    ...Array.from({ length: 4 }, () => ({ type: 'Organization' })),
    ...Array.from({ length: 3 }, () => ({ type: 'Location' })),
    ...Array.from({ length: 2 }, () => ({ type: 'Service Lane' })),
    { type: 'ServiceLane' },
    { type: 'Port' },
    { type: null },
  ];

  it('keeps the four largest keys as series and folds the rest into Other', () => {
    const folded = foldGraphTypes(nodes);
    expect(
      folded.groups.map((g) => [g.key, g.label, g.count, g.series]),
    ).toEqual([
      ['person', 'Person', 6, 0],
      ['organization', 'Organization', 4, 1],
      ['location', 'Location', 3, 2],
      ['servicelane', 'Service Lane', 3, 3],
    ]);
    expect(folded.other).toEqual({ count: 2, labels: ['Port'] });
    expect(folded.seriesOf('SERVICELANE')).toBe(3);
    expect(folded.seriesOf('Port')).toBeNull();
    expect(folded.seriesOf(null)).toBeNull();
    expect(folded.labelOf('PERSON')).toBe('Person');
    expect(folded.labelOf('port')).toBe('Port');
  });

  it('has no Other when every type fits', () => {
    const folded = foldGraphTypes([{ type: 'A' }, { type: 'b' }]);
    expect(folded.groups).toHaveLength(2);
    expect(folded.other).toEqual({ count: 0, labels: [] });
  });
});

describe('normalizeEdgeLabel', () => {
  it('lower-cases, turns underscores into spaces and trims', () => {
    expect(normalizeEdgeLabel('PREFERRED_CARRIER_FOR')).toBe(
      'preferred carrier for',
    );
    expect(normalizeEdgeLabel('  serves  ')).toBe('serves');
    expect(normalizeEdgeLabel(null)).toBe('');
  });
});

describe('groupRelationships', () => {
  it('makes one row per neighbour with distinct labels, busiest neighbour first', () => {
    const rows = groupRelationships([
      {
        id: 'm',
        name: 'Meridian',
        type: 'Org',
        degree: 119,
        edge_type: 'carrier_for',
      },
      {
        id: 'a',
        name: 'Anneke',
        type: 'Person',
        degree: 40,
        edge_type: 'MANAGES',
      },
      {
        id: 'm',
        name: 'Meridian',
        type: 'Org',
        degree: 119,
        edge_type: 'CARRIER_FOR',
      },
      {
        id: 'm',
        name: 'Meridian',
        type: 'Org',
        degree: 119,
        edge_type: 'serves',
      },
      {
        id: 'd',
        name: 'Duisport',
        type: 'Location',
        degree: 9,
        edge_type: null,
      },
    ]);
    expect(rows.map((r) => [r.id, r.labels])).toEqual([
      ['m', ['carrier for', 'serves']],
      ['a', ['manages']],
      ['d', []],
    ]);
  });
});

describe('escapeDeselects', () => {
  const press = (target: EventTarget, init: KeyboardEventInit = {}) => {
    let result: boolean | undefined;
    const listener = (event: Event) => {
      result = escapeDeselects(event as KeyboardEvent);
    };
    document.addEventListener('keydown', listener);
    target.dispatchEvent(
      new KeyboardEvent('keydown', {
        key: 'Escape',
        bubbles: true,
        cancelable: true,
        ...init,
      }),
    );
    document.removeEventListener('keydown', listener);
    return result;
  };

  afterEach(() => {
    document.body.innerHTML = '';
  });

  it('deselects on Escape outside a field', () => {
    const div = document.body.appendChild(document.createElement('div'));
    expect(press(div)).toBe(true);
    expect(press(document.body, { key: 'Enter' })).toBe(false);
  });

  it('leaves Escape to a field being typed in', () => {
    for (const tag of ['input', 'textarea', 'select']) {
      const field = document.body.appendChild(document.createElement(tag));
      expect(press(field)).toBe(false);
    }
    const editable = document.body.appendChild(document.createElement('div'));
    editable.contentEditable = 'true';
    // jsdom does not derive isContentEditable from the attribute.
    Object.defineProperty(editable, 'isContentEditable', { value: true });
    expect(press(editable)).toBe(false);
  });

  it('leaves an Escape something else already handled', () => {
    const div = document.body.appendChild(document.createElement('div'));
    div.addEventListener('keydown', (event) => event.preventDefault());
    expect(press(div)).toBe(false);
  });
});

describe('otherTypesList', () => {
  const more = (count: number) => `${count} more`;
  const labels = ['Vessel', 'Port', 'Terminal', 'Broker', 'Law', 'Insurer'];

  it('joins the folded types as a list in the app language', () => {
    expect(otherTypesList(['Vessel', 'Port'], more, 'en')).toBe(
      'Vessel and Port',
    );
    expect(otherTypesList(labels, more, 'en')).toBe(
      'Vessel, Port, Terminal, Broker, Law, and Insurer',
    );
  });

  it('names the rest past six as its last item', () => {
    const nine = [...labels, 'Carrier', 'Forwarder', 'Shipper'];
    expect(otherTypesList(nine, more, 'en')).toBe(
      'Vessel, Port, Terminal, Broker, Law, Insurer, and 3 more',
    );
    expect(otherTypesList(nine, (n) => `${n} weitere`, 'de')).toBe(
      'Vessel, Port, Terminal, Broker, Law, Insurer und 3 weitere',
    );
  });

  it('maps the app codes Intl does not know', () => {
    expect(otherTypesList(['A', 'B'], more, 'jp')).toBe(
      new Intl.ListFormat('ja', { type: 'conjunction' }).format(['A', 'B']),
    );
  });
});
