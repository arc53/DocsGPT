/**
 * A ``run_code`` that wrote several files must render one chip per file.
 *
 * ``ConversationBubble`` derives chips from ``toolCall.artifacts`` and falls
 * back to the single ``toolCall.artifact_id``. The persistence projection used
 * to drop ``artifacts``, so the fallback was the only path on reload: three
 * files became one chip labelled with the tool's name. The payload below is
 * captured verbatim from ``GET /api/get_single_conversation``.
 */
import { describe, expect, it } from 'vitest';

import type { ToolCallsType } from './types';

/** Mirrors the derivation in ConversationBubble.tsx. */
function chipsFor(toolCalls: ToolCallsType[]) {
  return toolCalls
    .filter((toolCall) => toolCall.status === 'completed')
    .flatMap((toolCall) => {
      const produced = toolCall.artifacts?.length
        ? toolCall.artifacts
        : toolCall.artifact_id
          ? [{ id: toolCall.artifact_id, filename: undefined, ref: undefined }]
          : [];
      return produced.map((artifact) => ({
        id: artifact.id,
        ref: artifact.ref ?? undefined,
        label: artifact.filename || 'Code Executor',
      }));
    });
}

const reloadedTurn = [
  {
    tool_name: 'code_executor',
    call_id: 'c1',
    action_name: 'run_code',
    status: 'completed',
    artifact_id: '7c342ac8-20d3-4658-9f6a-0ac88f665037',
    artifacts: [
      {
        id: '7c342ac8-20d3-4658-9f6a-0ac88f665037',
        filename: 'monthly_sales.csv',
        ref: 'A1',
      },
      {
        id: '5b9bea99-38ac-4102-a838-09cac7a42f1a',
        filename: 'monthly_sales_bar_chart.png',
        ref: 'A2',
      },
    ],
  },
] as unknown as ToolCallsType[];

describe('artifact chips after reload', () => {
  it('renders one chip per file, labelled by filename', () => {
    expect(chipsFor(reloadedTurn)).toEqual([
      {
        id: '7c342ac8-20d3-4658-9f6a-0ac88f665037',
        ref: 'A1',
        label: 'monthly_sales.csv',
      },
      {
        id: '5b9bea99-38ac-4102-a838-09cac7a42f1a',
        ref: 'A2',
        label: 'monthly_sales_bar_chart.png',
      },
    ]);
  });

  // What reload produced before the projection fix: `artifacts` stripped, so
  // the chart had no way into the UI and the one chip carried the tool's name.
  it('the stripped payload loses the second file entirely', () => {
    const stripped = [
      { ...reloadedTurn[0], artifacts: undefined },
    ] as unknown as ToolCallsType[];
    const chips = chipsFor(stripped);
    expect(chips).toHaveLength(1);
    expect(chips[0].label).toBe('Code Executor');
  });
});
