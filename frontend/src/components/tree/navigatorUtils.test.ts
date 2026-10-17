import { describe, expect, it } from 'vitest';

import {
  ancestorIds,
  countLeaves,
  directoryToNavigator,
  filterNavigatorLeaves,
  findNode,
  type NavigatorNode,
} from './navigatorUtils';

const tree: NavigatorNode[] = [
  {
    id: 'briefs',
    kind: 'folder',
    label: 'briefs',
    path: 'briefs',
    children: [
      {
        id: 'briefs/kestrel.docx',
        kind: 'leaf',
        label: 'Kestrel brief',
        path: 'briefs/kestrel.docx',
      },
      {
        id: 'briefs/deep',
        kind: 'folder',
        label: 'deep',
        path: 'briefs/deep',
        children: [
          {
            id: 'briefs/deep/nordhaven.docx',
            kind: 'leaf',
            label: 'nordhaven.docx',
            path: 'briefs/deep/nordhaven.docx',
          },
        ],
      },
    ],
  },
  { id: 'readme.md', kind: 'leaf', label: 'readme.md', path: 'readme.md' },
];

describe('filterNavigatorLeaves', () => {
  it('matches leaves by label or path, case-insensitively, with their folder', () => {
    expect(filterNavigatorLeaves(tree, 'NORD')).toEqual([
      { node: tree[0].children![1].children![0], parentPath: 'briefs/deep' },
    ]);
    expect(filterNavigatorLeaves(tree, 'briefs').map((r) => r.node.id)).toEqual(
      ['briefs/kestrel.docx', 'briefs/deep/nordhaven.docx'],
    );
  });

  it('gives a root leaf an empty parent path and returns nothing for a blank query', () => {
    expect(filterNavigatorLeaves(tree, 'readme')).toEqual([
      { node: tree[1], parentPath: '' },
    ]);
    expect(filterNavigatorLeaves(tree, '   ')).toEqual([]);
  });
});

describe('ancestorIds / findNode / countLeaves', () => {
  it('lists the folders above a node, outermost first', () => {
    expect(ancestorIds(tree, 'briefs/deep/nordhaven.docx')).toEqual([
      'briefs',
      'briefs/deep',
    ]);
    expect(ancestorIds(tree, 'readme.md')).toEqual([]);
    expect(ancestorIds(tree, 'missing')).toEqual([]);
  });

  it('finds a node anywhere in the tree', () => {
    expect(findNode(tree, 'briefs/deep')?.label).toBe('deep');
    expect(findNode(tree, 'nope')).toBeUndefined();
  });

  it('counts leaves under a list of nodes', () => {
    expect(countLeaves(tree)).toBe(3);
    expect(countLeaves(tree[0].children!)).toBe(2);
  });
});

describe('directoryToNavigator', () => {
  it('builds folders first, then files, with display names and leaf counts', () => {
    const nodes = directoryToNavigator({
      'z.md': { type: 'text/markdown', display_name: 'Zed notes' },
      docs: {
        'b.pdf': { type: 'application/pdf' },
        'a.pdf': { type: 'application/pdf' },
      } as never,
    });
    expect(nodes.map((n) => [n.id, n.kind, n.label, n.count])).toEqual([
      ['docs', 'folder', 'docs', 2],
      ['z.md', 'leaf', 'Zed notes', undefined],
    ]);
    expect(nodes[0].children!.map((n) => n.id)).toEqual([
      'docs/a.pdf',
      'docs/b.pdf',
    ]);
  });

  it('tolerates a structure stored as a JSON string', () => {
    const nodes = directoryToNavigator(
      JSON.stringify({ 'a.txt': { type: 'text/plain' } }) as never,
    );
    expect(nodes).toHaveLength(1);
    expect(nodes[0].path).toBe('a.txt');
  });
});
