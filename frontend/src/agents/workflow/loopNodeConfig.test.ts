import type { Edge, Node } from 'reactflow';
import { describe, expect, it } from 'vitest';

import {
  containerData,
  findLoopAt,
  isValidItemsPath,
  isValidItemVariable,
  loopProblems,
  parentsFirst,
  readContainerData,
  sameContainer,
  toLoopPosition,
} from './loopNodeConfig';

const loop = (config: Record<string, unknown> = {}): Node => ({
  id: 'each',
  type: 'loop',
  position: { x: 100, y: 50 },
  style: { width: 400, height: 200 },
  data: { title: 'Each', config: { items: 'extracted.items', ...config } },
});

const child = (id: string, type = 'agent'): Node => ({
  id,
  type,
  position: { x: 20, y: 80 },
  parentNode: 'each',
  extent: 'parent',
  data: { title: id },
});

const edge = (source: string, target: string): Edge => ({
  id: `${source}-${target}`,
  source,
  target,
});

describe('loop paths and variables', () => {
  it('accepts dotted state paths only', () => {
    expect(isValidItemsPath('extracted.items')).toBe(true);
    expect(isValidItemsPath('rows.0')).toBe(true);
    expect(isValidItemsPath('a b')).toBe(false);
    expect(isValidItemsPath('')).toBe(false);
  });

  it('refuses reserved names and non-identifiers as the item variable', () => {
    expect(isValidItemVariable('person')).toBe(true);
    expect(isValidItemVariable('query')).toBe(false);
    expect(isValidItemVariable('1x')).toBe(false);
  });
});

describe('placing nodes in a loop', () => {
  it('finds the loop under a point and converts the point to its body', () => {
    const nodes = [loop()];
    expect(findLoopAt(nodes, { x: 150, y: 100 })?.id).toBe('each');
    expect(findLoopAt(nodes, { x: 600, y: 100 })).toBeUndefined();
    expect(toLoopPosition(nodes[0], { x: 150, y: 100 })).toEqual({
      x: 50,
      y: 50,
    });
  });

  it('keeps edges on one side of a loop boundary', () => {
    const nodes = [
      { id: 'top', type: 'agent', position: { x: 0, y: 0 }, data: {} },
      loop(),
      child('a'),
      child('b'),
    ];
    expect(sameContainer(nodes, 'a', 'b')).toBe(true);
    expect(sameContainer(nodes, 'top', 'each')).toBe(true);
    expect(sameContainer(nodes, 'top', 'a')).toBe(false);
  });
});

describe('saving and loading a loop', () => {
  it('round-trips the parent and the size through the saved data', () => {
    const saved: Record<string, unknown> = {
      prompt: 'x',
      ...containerData(child('a')),
    };
    expect(saved.parent_id).toBe('each');
    const { data, canvas } = readContainerData(saved);
    expect(data).toEqual({ prompt: 'x' });
    expect(canvas).toEqual({ parentNode: 'each', extent: 'parent' });

    const loopSaved = { items: 'x', ...containerData(loop()) };
    expect(readContainerData(loopSaved).canvas.style).toEqual({
      width: 400,
      height: 200,
    });
  });

  it('puts loops before the nodes inside them', () => {
    const ordered = parentsFirst([child('a'), loop()]);
    expect(ordered.map((n) => n.id)).toEqual(['each', 'a']);
  });
});

describe('loopProblems', () => {
  it('passes a loop with one first node', () => {
    const nodes = [loop(), child('a'), child('b')];
    expect(loopProblems(nodes[0], nodes, [edge('a', 'b')])).toEqual([]);
  });

  it('flags a missing list, an empty body and two first nodes', () => {
    const empty = loop({ items: '' });
    expect(loopProblems(empty, [empty], [])).toEqual([
      'agents.workflow.validation.loopItems',
      'agents.workflow.validation.loopEmpty',
    ]);
    const nodes = [loop(), child('a'), child('b'), child('n', 'note')];
    expect(loopProblems(nodes[0], nodes, [])).toEqual([
      'agents.workflow.validation.loopEntry',
    ]);
  });
});
