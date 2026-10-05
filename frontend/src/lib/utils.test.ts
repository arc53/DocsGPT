import { describe, expect, it } from 'vitest';

import { buttonVariants } from '@/components/ui/button';
import { inputVariants } from '@/components/ui/input';
import { textareaVariants } from '@/components/ui/textarea';

import { fieldFrame, focusRing, invalidState } from './utils';

describe('shared ui class constants', () => {
  it('focusRing is the DESIGN.md keyboard ring', () => {
    expect(focusRing).toBe('focus-visible:ring-3 focus-visible:ring-ring/50');
  });

  it('invalidState is the aria-invalid triple', () => {
    expect(invalidState.split(' ')).toEqual([
      'aria-invalid:ring-destructive/20',
      'dark:aria-invalid:ring-destructive/40',
      'aria-invalid:border-destructive',
    ]);
  });

  it.each([
    ['Button', buttonVariants()],
    ['Input', inputVariants()],
    ['Textarea', textareaVariants()],
  ])('%s is built from the shared constants', (_name, classes) => {
    const list = classes.split(' ');
    for (const c of [...focusRing.split(' '), ...invalidState.split(' ')]) {
      expect(list).toContain(c);
    }
  });

  it('fieldFrame carries the field border, shadow and transition', () => {
    const list = inputVariants().split(' ');
    for (const c of fieldFrame.split(' ')) expect(list).toContain(c);
    expect(fieldFrame).toContain('shadow-xs');
    expect(fieldFrame).toContain('transition-[color,box-shadow]');
  });
});
