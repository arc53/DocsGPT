// @vitest-environment node
import tsParser from '@typescript-eslint/parser';
import { Linter } from 'eslint';

// The no-restyle contracts live in eslint.config.js, so the test reads the
// rule entry (and the shadcn plugin) from the real config.
type FlatBlock = {
  plugins?: Record<string, unknown>;
  rules?: Record<string, unknown>;
};

let ruleEntry: unknown;
let shadcn: unknown;

beforeAll(async () => {
  const url = new URL('../../eslint.config.js', import.meta.url).href;
  const { default: config } = (await import(/* @vite-ignore */ url)) as {
    default: FlatBlock[];
  };
  const block = config.find((b) =>
    Array.isArray(b.rules?.['shadcn/no-restyle']),
  );
  ruleEntry = block!.rules!['shadcn/no-restyle'];
  shadcn = block!.plugins!.shadcn;
});

const linter = new Linter({ configType: 'flat' });

const lint = (code: string): string[] =>
  linter
    .verify(
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
          plugins: { shadcn: shadcn as never },
          rules: { 'shadcn/no-restyle': ruleEntry as Linter.RuleEntry },
        },
      ],
      'src/fixture.tsx',
    )
    .map((m) => m.message);

describe('no-restyle contracts', () => {
  it.each([
    [
      'font-mono on a scope chip',
      `<Badge variant="neutral" className="font-mono">x</Badge>`,
    ],
    [
      'tabular-nums on a stat chip',
      `<Badge variant="neutral" className="tabular-nums">x</Badge>`,
    ],
  ])('allows %s on Badge', (_name, code) => {
    expect(lint(code)).toEqual([]);
  });

  it('lists the Badge variants in its message', () => {
    const [message] = lint(`<Badge className="font-bold">x</Badge>`);
    expect(message).toContain(
      'use a variant (default, neutral, success, warning, destructive, info, outline)',
    );
    expect(message).not.toContain('()');
  });

  it.each([
    [
      'Input',
      'use size (default, sm), shape (default, pill) and variant (default, bare, filled)',
    ],
    [
      'SelectTrigger',
      'use size (sm, field), variant (default) and shape (default, pill)',
    ],
    [
      'Card',
      'use variant (outline, filled, subtle), tone (destructive), padding (none, sm, default, lg) and interactive (true, within)',
    ],
    [
      'Avatar',
      'use size (xs, sm, default, lg, xl), shape (circle, square) and variant (primary, muted, icon)',
    ],
    ['Alert', 'use Alert variant (success, warning, info, destructive)'],
  ])('lists the current %s props', (component, expected) => {
    const [message] = lint(`<${component} className="font-bold" />`);
    expect(message).toContain(expected);
  });
});
