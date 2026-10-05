import { describe, expect, it } from 'vitest';

import { getMethodBadgeVariant } from './httpMethodColors';

describe('getMethodBadgeVariant', () => {
  it('maps each HTTP method to a Badge variant by meaning', () => {
    expect(getMethodBadgeVariant('GET')).toBe('success');
    expect(getMethodBadgeVariant('POST')).toBe('info');
    expect(getMethodBadgeVariant('PUT')).toBe('warning');
    expect(getMethodBadgeVariant('DELETE')).toBe('destructive');
    expect(getMethodBadgeVariant('PATCH')).toBe('default');
    expect(getMethodBadgeVariant('HEAD')).toBe('neutral');
    expect(getMethodBadgeVariant('OPTIONS')).toBe('neutral');
  });

  it('ignores case', () => {
    expect(getMethodBadgeVariant('get')).toBe('success');
    expect(getMethodBadgeVariant('Delete')).toBe('destructive');
  });

  it('falls back to neutral for an unknown method', () => {
    expect(getMethodBadgeVariant('TRACE')).toBe('neutral');
  });
});
