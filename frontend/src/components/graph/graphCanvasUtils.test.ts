import { describe, expect, it } from 'vitest';

import { foldGraphTypes } from '../graphViewUtils';
import {
  OTHER_GROUP_KEY,
  buildAdjacency,
  chunkFileName,
  chunkFilePath,
  chunkHeading,
  endpointId,
  focusSet,
  labelBoxesOverlap,
  legendGroupOf,
  linkTouches,
  overviewRelationships,
  pickLabels,
  relationshipLabelText,
  seriesDotClass,
  topHubIds,
} from './graphCanvasUtils';

const nodes = Array.from({ length: 14 }, (_, i) => ({
  id: `n${i}`,
  name: `Node ${i}`,
  degree: 14 - i,
}));

describe('topHubIds', () => {
  it('keeps the ten busiest nodes', () => {
    const hubs = topHubIds(nodes);
    expect(hubs.size).toBe(10);
    expect(hubs.has('n0')).toBe(true);
    expect(hubs.has('n9')).toBe(true);
    expect(hubs.has('n10')).toBe(false);
  });
});

describe('buildAdjacency', () => {
  it('links both ends and reads node objects from a running simulation', () => {
    const adjacency = buildAdjacency([
      { source: 'a', target: 'b' },
      {
        source: { id: 'b' } as unknown as string,
        target: { id: 'c' } as unknown as string,
      },
      { source: 'a', target: 'a' },
    ]);
    expect([...(adjacency.get('b') ?? [])].sort()).toEqual(['a', 'c']);
    expect([...(adjacency.get('a') ?? [])]).toEqual(['b']);
  });

  it('reads either end shape', () => {
    expect(endpointId('x')).toBe('x');
    expect(endpointId({ id: 'y' })).toBe('y');
    expect(endpointId(null)).toBe('');
  });
});

describe('focusSet (dimming)', () => {
  const adjacency = buildAdjacency([
    { source: 'a', target: 'b' },
    { source: 'a', target: 'c' },
    { source: 'c', target: 'd' },
  ]);
  const loaded = new Set(['a', 'b', 'c', 'd']);

  it('is the selection and its neighbours', () => {
    expect([...(focusSet('a', adjacency, loaded) ?? [])].sort()).toEqual([
      'a',
      'b',
      'c',
    ]);
  });

  it('is null with no selection, or one outside the loaded overview', () => {
    expect(focusSet(null, adjacency, loaded)).toBeNull();
    expect(focusSet('zz', adjacency, loaded)).toBeNull();
  });

  it('keeps an isolated selection on its own', () => {
    expect([...(focusSet('e', new Map(), new Set(['e'])) ?? [])]).toEqual([
      'e',
    ]);
  });
});

describe('linkTouches', () => {
  it('matches either end', () => {
    expect(linkTouches({ source: 'a', target: 'b' }, 'b')).toBe(true);
    expect(linkTouches({ source: 'a', target: 'b' }, 'c')).toBe(false);
    expect(linkTouches({ source: 'a', target: 'b' }, null)).toBe(false);
  });
});

describe('relationshipLabelText', () => {
  it('falls back when there are no labels', () => {
    expect(relationshipLabelText([], 'related to')).toBe('related to');
  });

  it('joins two labels', () => {
    expect(relationshipLabelText(['manages', 'owns'], 'x')).toBe(
      'manages · owns',
    );
  });

  it('counts the rest after two', () => {
    expect(relationshipLabelText(['a', 'b', 'c', 'd'], 'x')).toBe('a · b · +2');
  });
});

describe('chunkFileName', () => {
  it('takes the last segment of the source path', () => {
    expect(chunkFileName({ source: 'inputs/u/Carrier_profile.docx' })).toBe(
      'Carrier_profile.docx',
    );
  });

  it('falls back to the title, then nothing', () => {
    expect(chunkFileName({ title: 'Notes.md' })).toBe('Notes.md');
    expect(chunkFileName(undefined)).toBe('');
  });

  it("names a web page by its tree path, not the URL's last segment", () => {
    expect(
      chunkFileName({
        source: 'https://docs.example.com/guides/setup?x=1',
        file_path: 'guides/setup.md',
        title: 'Setup',
      }),
    ).toBe('setup.md');
  });

  it('never splits a title', () => {
    expect(
      chunkFileName({ source: 'https://example.com/a/b', title: 'A / B' }),
    ).toBe('A / B');
  });
});

describe('chunkFilePath', () => {
  it('prefers file_path, then key', () => {
    expect(
      chunkFilePath({
        file_path: 'guides/setup.md',
        key: 'other.md',
        source: 'https://x.dev/guides/setup',
      }),
    ).toBe('guides/setup.md');
    expect(
      chunkFilePath({ key: 'docs/a.md', source: 'inputs/u/docs/a.md' }),
    ).toBe('docs/a.md');
  });

  it('uses a local source path but never a URL', () => {
    expect(chunkFilePath({ source: 'inputs/u/Brief.docx' })).toBe(
      'inputs/u/Brief.docx',
    );
    expect(
      chunkFilePath({ source: 'https://x.dev/page', title: 'Page title' }),
    ).toBe('Page title');
    expect(chunkFilePath({ source: 'https://x.dev/page' })).toBe('');
  });
});

describe('legend groups and dots', () => {
  const fold = foldGraphTypes([
    { type: 'Person' },
    { type: 'Person' },
    { type: 'Port' },
    { type: 'Lane' },
    { type: 'Company' },
    { type: 'Event' },
    { type: null },
  ]);

  it('maps a type to its fold group, the rest to Other', () => {
    expect(legendGroupOf(fold, 'PERSON')).toBe('person');
    expect(legendGroupOf(fold, null)).toBe(OTHER_GROUP_KEY);
  });

  it('uses a static class per series', () => {
    expect(seriesDotClass(0)).toBe('bg-chart-1');
    expect(seriesDotClass(3)).toBe('bg-chart-4');
    expect(seriesDotClass(null)).toBe('bg-muted-foreground');
  });
});

describe('overviewRelationships', () => {
  const overviewNodes = [
    { id: 'n', name: 'Nordhaven', type: 'Company', degree: 9 },
    { id: 'a', name: 'Anneke', type: 'Person', degree: 5 },
    { id: 'b', name: 'Bram', type: 'Person', degree: 3 },
  ];
  it('joins each link touching the node to its neighbour, both directions', () => {
    const rels = overviewRelationships(
      'n',
      [
        { source: 'a', target: 'n', type: 'manages' },
        // A simulation link: node objects at the ends.
        {
          source: { id: 'n' } as never,
          target: { id: 'b' } as never,
          type: null,
        },
        { source: 'a', target: 'b', type: 'knows' },
        { source: 'n', target: 'missing', type: 'x' },
      ],
      overviewNodes,
    );
    expect(rels).toEqual([
      {
        id: 'a',
        name: 'Anneke',
        type: 'Person',
        degree: 5,
        edge_type: 'manages',
        direction: 'in',
      },
      {
        id: 'b',
        name: 'Bram',
        type: 'Person',
        degree: 3,
        edge_type: null,
        direction: 'out',
      },
    ]);
  });
});

describe('label collision', () => {
  const box = (id: string, x: number, y: number, always = false) => ({
    id,
    x,
    y,
    width: 40,
    height: 10,
    always,
  });

  it('tests intersection of centred boxes', () => {
    expect(labelBoxesOverlap(box('a', 0, 0), box('b', 39, 9))).toBe(true);
    expect(labelBoxesOverlap(box('a', 0, 0), box('b', 40, 0))).toBe(false);
    expect(labelBoxesOverlap(box('a', 0, 0), box('b', 0, 10))).toBe(false);
    expect(labelBoxesOverlap(box('a', 0, 0), box('b', 0, 11), 2)).toBe(true);
  });

  it('keeps labels in priority order and skips the ones they cover', () => {
    const picked = pickLabels([
      box('selected', 0, 0, true),
      box('hovered', 10, 2, true),
      box('hub', 20, 5),
      box('clear', 100, 0),
      box('under-clear', 110, 4),
    ]);
    expect([...picked]).toEqual(['selected', 'hovered', 'clear']);
  });
});

describe('chunkHeading', () => {
  it('reads a first-line markdown heading, else nothing', () => {
    expect(chunkHeading('# Account brief — Nordhaven\nBody')).toBe(
      'Account brief — Nordhaven',
    );
    expect(chunkHeading('\n  ### Rates ##\ntext')).toBe('Rates');
    expect(chunkHeading('Plain text\n# Later')).toBeNull();
    expect(chunkHeading('#hashtag')).toBeNull();
    expect(chunkHeading('')).toBeNull();
  });
});
