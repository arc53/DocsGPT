// @vitest-environment node
import tsParser from '@typescript-eslint/parser';
import { Linter } from 'eslint';

import {
  everywhereSelectors,
  pageSelectors,
} from '../../eslint/design-rules.js';

const linter = new Linter({ configType: 'flat' });

const lint = (code: string): number =>
  linter.verify(
    code,
    [
      {
        files: ['**/*.tsx'],
        languageOptions: {
          parser: tsParser,
          parserOptions: {
            ecmaFeatures: { jsx: true },
            sourceType: 'module',
          },
        },
        rules: {
          'no-restricted-syntax': [
            'error',
            ...everywhereSelectors,
            ...pageSelectors,
          ],
        },
      },
    ],
    'fixture.tsx',
  ).length;

describe('design rules lint', () => {
  it.each([
    ['break-all', `<p className="break-all" />`],
    ['bare rounded', `<div className="bg-muted rounded px-2" />`],
    ['bare rounded in cn()', `<div className={cn('p-2 rounded', a && 'x')} />`],
    ['custom breakpoint', `<div className="min-[500px]:flex" />`],
    ['media breakpoint', `<div className="[@media(hover:hover)]:block" />`],
    ['off-scale z', `<div className="absolute z-30" />`],
    ['arbitrary z', `<div className="z-[60]" />`],
    ['focus ring-2', `<div className="focus-within:ring-2" />`],
    ['md: focus ring-2', `<div className="md:focus-visible:ring-2" />`],
    ['dark: focus ring-2', `<div className="dark:focus-visible:ring-2" />`],
    ['peer focus ring-2', `<div className="peer-focus-visible:ring-2" />`],
    ['lucide loader', `import { Loader2 } from 'lucide-react';`],
    ['transition-all', `<div className="transition-all duration-200" />`],
    ['hover scale', `<div className="hover:scale-105" />`],
    ['md:hover scale', `<div className="md:hover:scale-105" />`],
    ['group-hover scale', `<div className="group-hover:scale-105" />`],
    ['bg-primary/10', `const tone = 'bg-primary/10 text-primary';`],
    ['native checkbox', `<input type="checkbox" />`],
    ['title on Button', `<Button title="Delete" />`],
    ['raw table', `<table><tbody /></table>`],
    ['link-styled a', `<a className="text-primary underline" href="#">x</a>`],
    ['hover: underline a', `<a className="hover:underline" href="#">x</a>`],
    [
      'dark: text-primary a',
      `<a className={\`dark:text-primary \${x}\`} href="#">x</a>`,
    ],
    ['drawer width', `<SheetContent side="right" className="sm:max-w-xl" />`],
    ['drawer w-', `<SheetContent className="w-80 p-0" />`],
  ])('rejects %s', (_name, code) => {
    expect(lint(code)).toBeGreaterThan(0);
  });

  it.each([
    [
      'rounded scale steps',
      `<div className="rounded-md rounded-t-2xl rounded-full" />`,
    ],
    [
      'layer z values',
      `<div className="z-10 lg:z-20 z-50 z-200 z-0 z-auto -z-10" />`,
    ],
    ['size and max-w', `<div className="size-4 max-w-[520px] min-h-dvh" />`],
    ['selection ring-2', `<div className="ring-2 ring-primary" />`],
    ['hover:scale-x underline wipe', `<span className="hover:scale-x-100" />`],
    ['md:hover:scale-x wipe', `<span className="md:hover:scale-x-100" />`],
    ['no-underline a', `<a className="no-underline" href="#">x</a>`],
    ['underline-offset a', `<a className="underline-offset-2" href="#">x</a>`],
    ['transition-colors', `<div className="transition-colors" />`],
    [
      'other lucide icons',
      `import { Loader as L } from './local'; import { Plus } from 'lucide-react';`,
    ],
    ['a without link styling', `<a className="flex items-center" href="#" />`],
    ['IconButton label', `<IconButton label="Delete" />`],
    ['secondary fill', `<span className="bg-secondary bg-primary/90" />`],
    [
      'drawer size and layout',
      `<SheetContent size="wide" className="min-w-0 p-0" />`,
    ],
  ])('allows %s', (_name, code) => {
    expect(lint(code)).toBe(0);
  });
});
