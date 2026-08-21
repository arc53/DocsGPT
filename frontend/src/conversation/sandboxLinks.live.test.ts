/**
 * Regression test built from a real two-turn conversation.
 *
 * Payloads captured verbatim from `GET /api/get_single_conversation` against a
 * live run: turn 1's `run_code` wrote a CSV and a PNG (refs A1/A2), turn 2 wrote
 * a JSON summary (ref A3). Refs are numbered per *conversation*, so turn 2's
 * only artifact is A3 — indexing a turn's artifact list by the ref number picks
 * the wrong file, or none.
 */
import { describe, expect, it } from 'vitest';

import { resolveSandboxLink, type SandboxArtifact } from './sandboxLinks';

// Exactly as they arrive on the wire.
const turn1: SandboxArtifact[] = [
  {
    id: '7c342ac8-20d3-4658-9f6a-0ac88f665037',
    label: 'monthly_sales.csv',
    ref: 'A1',
    toolName: 'code_executor',
  },
  {
    id: '5b9bea99-38ac-4102-a838-09cac7a42f1a',
    label: 'monthly_sales_bar_chart.png',
    ref: 'A2',
    toolName: 'code_executor',
  },
];

const turn2: SandboxArtifact[] = [
  {
    id: '4daf594b-46a4-4edb-a5c2-562b6457fdea',
    label: 'monthly_sales_summary.json',
    ref: 'A3',
    toolName: 'code_executor',
  },
];

describe('conversation-scoped refs against real turn payloads', () => {
  it('resolves turn 2s ref A3 to turn 2s file', () => {
    expect(resolveSandboxLink('artifact:A3', turn2)).toEqual({
      kind: 'artifact',
      artifact: turn2[0],
    });
  });

  // The bug: A1 is turn 1's CSV. Positional resolution made it index 0 of
  // turn 2's list — the JSON summary — and opened the wrong file silently.
  it('does not hand turn 1s ref to turn 2s file', () => {
    expect(resolveSandboxLink('artifact:A1', turn2)).toEqual({ kind: 'plain' });
    expect(resolveSandboxLink('sandbox:/artifact/A2', turn2)).toEqual({
      kind: 'plain',
    });
  });

  it('still resolves both of turn 1s files on turn 1', () => {
    expect(resolveSandboxLink('sandbox:/artifact/A1', turn1)).toEqual({
      kind: 'artifact',
      artifact: turn1[0],
    });
    expect(resolveSandboxLink('artifact:A2', turn1)).toEqual({
      kind: 'artifact',
      artifact: turn1[1],
    });
  });

  // Now that `artifacts` survives persistence, the filename forms work too.
  it('recovers the fabricated path forms by filename', () => {
    expect(
      resolveSandboxLink(
        'sandbox:/mnt/data/monthly_sales_bar_chart.png',
        turn1,
      ),
    ).toEqual({ kind: 'artifact', artifact: turn1[1] });
    expect(resolveSandboxLink('sandbox:/tmp/monthly_sales.csv', turn1)).toEqual(
      { kind: 'artifact', artifact: turn1[0] },
    );
  });

  it('resolves the uuid form for the second file, not just the first', () => {
    expect(
      resolveSandboxLink(
        'sandbox:/artifact/5b9bea99-38ac-4102-a838-09cac7a42f1a',
        turn1,
      ),
    ).toEqual({ kind: 'artifact', artifact: turn1[1] });
  });
});
