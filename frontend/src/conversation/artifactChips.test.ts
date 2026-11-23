/**
 * A ``run_code`` that wrote several files must render one chip per file.
 *
 * ``ConversationBubble`` derives chips from ``toolCall.artifacts`` and falls
 * back to the single ``toolCall.artifact_id``. The persistence projection used
 * to drop ``artifacts``, so the fallback was the only path on reload: three
 * files became one chip labelled with the tool's name. The payload below is
 * captured verbatim from ``GET /api/get_single_conversation``.
 *
 * This exercises ``deriveArtifactChips`` itself — the function the component
 * calls. An earlier version of this file reimplemented the derivation locally,
 * so dropping ``artifacts`` from the component left the suite green.
 */
import { describe, expect, it } from 'vitest';

import {
  conversationArtifactChips,
  deriveArtifactChips,
} from './artifactChips';
import type { ToolCallsType } from './types';

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
    expect(deriveArtifactChips(reloadedTurn)).toEqual([
      {
        id: '7c342ac8-20d3-4658-9f6a-0ac88f665037',
        ref: 'A1',
        label: 'monthly_sales.csv',
        filename: 'monthly_sales.csv',
        toolName: 'code_executor',
        callId: 'c1',
      },
      {
        id: '5b9bea99-38ac-4102-a838-09cac7a42f1a',
        ref: 'A2',
        label: 'monthly_sales_bar_chart.png',
        filename: 'monthly_sales_bar_chart.png',
        toolName: 'code_executor',
        callId: 'c1',
      },
    ]);
  });

  // What reload produced before the projection fix: `artifacts` stripped, so
  // the chart had no way into the UI and the one chip carried the tool's name.
  it('the stripped payload loses the second file entirely', () => {
    const stripped = [
      { ...reloadedTurn[0], artifacts: undefined },
    ] as unknown as ToolCallsType[];
    const chips = deriveArtifactChips(stripped);
    expect(chips).toHaveLength(1);
    expect(chips[0].label).toBe('Code Executor');
  });

  it('skips calls that have not completed', () => {
    const running = [
      { ...reloadedTurn[0], status: 'pending' },
    ] as unknown as ToolCallsType[];
    expect(deriveArtifactChips(running)).toEqual([]);
  });

  it('falls back to the tool label, then to Artifact', () => {
    const unnamed = [
      {
        tool_name: 'artifact_generator',
        call_id: 'c2',
        status: 'completed',
        artifacts: [{ id: 'x1' }],
      },
      {
        tool_name: undefined,
        call_id: 'c3',
        status: 'completed',
        artifacts: [{ id: 'x2' }],
      },
    ] as unknown as ToolCallsType[];
    expect(deriveArtifactChips(unnamed).map((chip) => chip.label)).toEqual([
      'Artifact',
      'Artifact',
    ]);
  });

  // Re-saving a file adds a version to the same artifact, so one turn can report
  // the same id from several calls. One chip per artifact, not per save: two
  // chips with one id also collide as React keys.
  it('renders one chip per artifact when calls re-save it', () => {
    const resaved = [
      {
        tool_name: 'code_executor',
        call_id: 'c1',
        status: 'completed',
        artifacts: [
          { id: 'doc', filename: 'review.docx', ref: 'A1' },
          { id: 'csv', filename: 'data.csv', ref: 'A2' },
        ],
      },
      {
        tool_name: 'code_executor',
        call_id: 'c2',
        status: 'completed',
        artifacts: [{ id: 'doc', filename: 'review.docx', ref: 'A1' }],
      },
    ] as unknown as ToolCallsType[];
    const chips = deriveArtifactChips(resaved);
    expect(chips.map((chip) => chip.id)).toEqual(['doc', 'csv']);
    // The latest call's report wins: it describes the version the chip opens.
    expect(chips[0]).toMatchObject({
      label: 'review.docx',
      ref: 'A1',
      callId: 'c2',
    });
  });
});

// A background job's files go on the reply that reports it
// (``metadata.job_artifacts``) and stay on the turn that started the job.
describe('a finished job reported by a later reply', () => {
  const launching = [
    {
      tool_name: 'code_executor',
      call_id: 'c1',
      status: 'completed',
      job_id: 'j1',
      artifacts: [{ id: 'chart', filename: 'chart.png', ref: 'A1' }],
    },
  ] as unknown as ToolCallsType[];
  const reported = [
    {
      id: 'chart',
      filename: 'chart.png',
      ref: 'A1',
      tool_name: 'code_executor',
      job_id: 'j1',
    },
    { id: 'report', ref: 'A2', tool_name: 'artifact_generator', job_id: 'j1' },
  ];

  it("shows the job's files on the reply", () => {
    expect(deriveArtifactChips(undefined, reported)).toEqual([
      {
        id: 'chart',
        ref: 'A1',
        label: 'chart.png',
        filename: 'chart.png',
        toolName: 'code_executor',
        callId: 'j1',
      },
      {
        id: 'report',
        ref: 'A2',
        label: 'Artifact',
        filename: undefined,
        toolName: 'artifact_generator',
        callId: 'j1',
      },
    ]);
  });

  it('lists a file on both turns once in the conversation', () => {
    const chips = conversationArtifactChips([
      { tool_calls: launching },
      { job_artifacts: reported },
    ]);
    expect(chips.map((chip) => chip.id)).toEqual(['chart', 'report']);
    // Where it first appeared: the call that wrote it.
    expect(chips[0].callId).toBe('c1');
  });
});
