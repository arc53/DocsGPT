import type { Node } from 'reactflow';

import type { ResourceState } from '../types';
import {
  nodeResourceIds,
  stoppedNodeResources,
  withoutNodeResource,
} from './nodeResources';

const agentNode = (id: string, config: Record<string, unknown>): Node => ({
  id,
  type: 'agent',
  position: { x: 0, y: 0 },
  data: { title: id, config },
});

const nodes: Node[] = [
  { id: 'start', type: 'start', position: { x: 0, y: 0 }, data: {} },
  agentNode('a1', { tools: ['T1', 't2'], sources: ['s1'] }),
  agentNode('a2', { tools: ['t1'], sources: [] }),
];

const state = (over: Partial<ResourceState>): ResourceState => ({
  key: 'tool:t1',
  type: 'tool',
  id: 't1',
  state: 'stopped',
  reason: 'deleted',
  ...over,
});

describe('nodeResources', () => {
  it('collects every agent node tool and source, lowercased', () => {
    const ids = nodeResourceIds(nodes);
    expect([...ids.tool].sort()).toEqual(['t1', 't2']);
    expect([...ids.source]).toEqual(['s1']);
  });

  it('keeps only stopped items still on the canvas', () => {
    const states = [
      state({}),
      state({ key: 'tool:t2', id: 't2', state: 'active', reason: null }),
      state({ key: 'source:gone', type: 'source', id: 'gone' }),
    ];
    expect(
      stoppedNodeResources(states, nodeResourceIds(nodes)).map((s) => s.key),
    ).toEqual(['tool:t1']);
  });

  it('takes a tool off every agent node and leaves the rest alone', () => {
    const next = withoutNodeResource(nodes, { type: 'tool', id: 't1' });
    expect(next[1].data.config.tools).toEqual(['t2']);
    expect(next[2].data.config.tools).toEqual([]);
    expect(next[0]).toBe(nodes[0]);
    expect(next[1].data.config.sources).toEqual(['s1']);
    expect(nodeResourceIds(next).tool.has('t1')).toBe(false);
  });

  it('leaves nodes untouched for a prompt', () => {
    expect(withoutNodeResource(nodes, { type: 'prompt', id: 'p' })).toBe(nodes);
  });
});
