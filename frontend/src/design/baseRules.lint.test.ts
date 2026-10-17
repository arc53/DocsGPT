// @vitest-environment node
import tsParser from '@typescript-eslint/parser';
import { Linter } from 'eslint';

// The viewport-height and focus-return selectors live inline in
// eslint.config.js (baseSyntaxRules), so the test reads them from the real
// config: the `no-restricted-syntax` entry of the block that sets it.
type FlatBlock = { rules?: Record<string, unknown> };

const loadSelectors = async (): Promise<unknown[]> => {
  const url = new URL('../../eslint.config.js', import.meta.url).href;
  const { default: config } = (await import(/* @vite-ignore */ url)) as {
    default: FlatBlock[];
  };
  const block = config.find((b) => b.rules?.['no-restricted-syntax']);
  const [, ...selectors] = block!.rules!['no-restricted-syntax'] as unknown[];
  return selectors;
};

// This file is itself linted by the rules under test, so the fixtures spell
// the banned units as %vh / %screen and fx() puts them back.
const fx = (code: string) =>
  code.replaceAll('%vh', 'vh').replaceAll('%screen', 'screen');

const linter = new Linter({ configType: 'flat' });
let selectors: unknown[] = [];

beforeAll(async () => {
  selectors = await loadSelectors();
});

const lint = (code: string): string[] =>
  linter
    .verify(
      fx(code),
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
          rules: { 'no-restricted-syntax': ['error', ...selectors] },
        },
      ],
      'fixture.tsx',
    )
    .map((m) => m.message);

describe('viewport-height and focus-return lint', () => {
  it.each([
    ['vh height', `<div className="h-[90%vh]" />`, /vh is the toolbar-hidden/],
    ['vh max-height', `<div className="max-h-[80%vh] p-4" />`, /vh is/],
    [
      'vh in a template literal',
      'const c = `max-h-[70%vh] ${open ? "flex" : ""}`;',
      /vh is/,
    ],
    [
      'vh in cn()',
      `<div className={cn('min-h-[50%vh]', a && 'x')} />`,
      /vh is/,
    ],
    ['screen height', `<div className="h-%screen" />`, /screen heights/],
    [
      'min screen height',
      `<main className="flex min-h-%screen" />`,
      /screen heights/,
    ],
    [
      'md: max screen height',
      `<div className="md:max-h-%screen" />`,
      /screen heights/,
    ],
    [
      'screen height in a template literal',
      'const c = `h-%screen ${x}`;',
      /screen heights/,
    ],
    [
      'hand-rolled onCloseAutoFocus',
      `<SheetContent onCloseAutoFocus={(e) => e.preventDefault()} />`,
      /Don't hand-roll onCloseAutoFocus/,
    ],
  ])('rejects %s', (_name, code, message) => {
    const messages = lint(code);
    expect(messages.length).toBeGreaterThan(0);
    expect(messages.some((m) => message.test(m))).toBe(true);
  });

  it.each([
    ['dvh and svh', `<div className="h-dvh max-h-[85dvh] min-h-[60svh]" />`],
    ['max-h-sheet', `<div className="max-h-sheet" />`],
    ['w-screen (vw is unaffected)', `<div className="w-screen" />`],
    ['a word ending in vh-like text', `const unit = 'dvh';`],
    [
      'onOpenAutoFocus',
      `<SheetContent onOpenAutoFocus={(e) => e.preventDefault()} />`,
    ],
  ])('allows %s', (_name, code) => {
    const messages = lint(code).filter((m) =>
      /vh is|screen heights|onCloseAutoFocus/.test(m),
    );
    expect(messages).toEqual([]);
  });
});
