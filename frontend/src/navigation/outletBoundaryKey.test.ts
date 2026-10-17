import { describe, expect, it } from 'vitest';

import { outletBoundaryKey } from './outletBoundaryKey';

describe('outletBoundaryKey', () => {
  it('gives every chat route one key', () => {
    const chat = outletBoundaryKey('/');
    expect(outletBoundaryKey('/c/new')).toBe(chat);
    expect(outletBoundaryKey('/c/abc123')).toBe(chat);
    expect(outletBoundaryKey('/agents/a1/c/new')).toBe(chat);
    expect(outletBoundaryKey('/agents/a1/c/abc123')).toBe(chat);
  });

  it('keys any other page by its path', () => {
    expect(outletBoundaryKey('/settings/tools')).toBe('/settings/tools');
    expect(outletBoundaryKey('/agents/new')).toBe('/agents/new');
    expect(outletBoundaryKey('/agents/edit/a1')).toBe('/agents/edit/a1');
  });
});
