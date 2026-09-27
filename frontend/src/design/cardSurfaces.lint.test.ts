// @vitest-environment node
import tsParser from '@typescript-eslint/parser';
import { Linter } from 'eslint';

import { cardSurfaceSelectors } from '../../eslint/card-surfaces.js';

const linter = new Linter({ configType: 'flat' });

function lint(code: string): string[] {
  return linter
    .verify(
      code,
      [
        {
          files: ['**/*.tsx'],
          languageOptions: {
            parser: tsParser,
            parserOptions: { ecmaFeatures: { jsx: true } },
          },
          rules: { 'no-restricted-syntax': ['error', ...cardSurfaceSelectors] },
        },
      ],
      'fixture.tsx',
    )
    .map((m) => m.message);
}

describe('card surface lint: no fill on a fill', () => {
  it('rejects bg-muted on an element inside a filled tile, in cn() too', () => {
    expect(
      lint(
        `<Card variant="filled"><div className="bg-muted px-4">x</div></Card>`,
      ),
    ).toHaveLength(1);
    expect(
      lint(
        `<Card variant="filled"><div className={cn('hover:bg-muted/60', a && 'p-2')}>x</div></Card>`,
      ),
    ).toHaveLength(1);
  });

  it('rejects a filled Card nested in a filled Card', () => {
    expect(
      lint(
        `<Card variant="filled"><Card variant="filled" padding="sm">x</Card></Card>`,
      ),
    ).toHaveLength(1);
  });

  it('rejects a Skeleton without surface="muted" on a filled tile', () => {
    expect(
      lint(`<Card variant="filled"><Skeleton className="h-4" /></Card>`),
    ).toHaveLength(1);
    expect(
      lint(
        `<Card variant="filled"><Skeleton surface="muted" className="h-4" /></Card>`,
      ),
    ).toHaveLength(0);
  });

  it('allows the neutral Badge and muted Avatar tints on a filled tile', () => {
    expect(
      lint(`<Card variant="filled">
        <Badge variant="neutral">Member</Badge>
        <Avatar variant="muted">M</Avatar>
      </Card>`),
    ).toHaveLength(0);
  });

  it('allows the same children on panels and allows muted-foreground', () => {
    expect(
      lint(`<Card variant="subtle">
        <Badge variant="neutral">2</Badge>
        <Avatar variant="muted">M</Avatar>
        <div className="bg-muted">well</div>
        <Card variant="filled" padding="sm"><pre className="text-muted-foreground">x</pre></Card>
      </Card>`),
    ).toHaveLength(0);
    expect(
      lint(
        `<Card variant="filled"><p className="text-muted-foreground bg-muted-foreground/20">x</p></Card>`,
      ),
    ).toHaveLength(0);
  });
});
