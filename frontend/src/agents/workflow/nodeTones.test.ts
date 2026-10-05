import { describe, expect, it } from 'vitest';

import { NODE_TONES, nodeToneClass, TONE_CLASSES } from './nodeTones';

describe('nodeTones', () => {
  it('maps every node type to one tone', () => {
    expect(NODE_TONES).toEqual({
      start: 'success',
      agent: 'primary',
      end: 'success',
      note: 'warning',
      state: 'info',
      condition: 'warning',
      code: 'info',
    });
  });

  it('never paints End red', () => {
    expect(nodeToneClass('end')).not.toMatch(/destructive/);
    expect(nodeToneClass('end')).toBe('bg-success/10 text-success');
  });

  it('uses the brand soft fill for primary, not bg-primary/10', () => {
    expect(TONE_CLASSES.primary).toBe('bg-secondary text-secondary-foreground');
    expect(nodeToneClass('agent')).toBe(TONE_CLASSES.primary);
  });

  it('gives status tones their /10 fill and text', () => {
    expect(TONE_CLASSES.info).toBe('bg-info/10 text-info');
    expect(TONE_CLASSES.warning).toBe('bg-warning/10 text-warning');
  });

  it('falls back to a neutral tint for an unknown type', () => {
    expect(nodeToneClass('mystery')).toBe(
      'bg-muted-foreground/15 text-muted-foreground',
    );
  });
});
