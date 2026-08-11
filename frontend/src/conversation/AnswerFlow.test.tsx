import i18n from 'i18next';
import { renderToStaticMarkup } from 'react-dom/server';
import { I18nextProvider, initReactI18next } from 'react-i18next';
import { beforeAll, describe, expect, it } from 'vitest';

import en from '../locale/en.json';
import { AnswerSegment } from './answerSegments';
import AnswerFlow from './AnswerFlow';
import { ToolCallsType } from './types';

const testI18n = i18n.createInstance();

beforeAll(async () => {
  await testI18n.use(initReactI18next).init({
    lng: 'en',
    fallbackLng: 'en',
    resources: { en: { translation: en } },
  });
});

const search = (overrides: Partial<ToolCallsType> = {}): ToolCallsType => ({
  tool_name: 'brave',
  action_name: 'brave_web_search',
  call_id: 'c1',
  arguments: { query: 'docsgpt setup' },
  status: 'completed',
  ...overrides,
});

const render = (props: {
  message?: string;
  thought?: string;
  toolCalls?: ToolCallsType[];
  segments?: AnswerSegment[];
  isStreaming?: boolean;
}): string =>
  renderToStaticMarkup(
    <I18nextProvider i18n={testI18n}>
      <AnswerFlow
        {...props}
        renderApproval={() => <div>APPROVAL_BAR</div>}
        renderWikiWrite={() => <div>WIKI_CARD</div>}
      />
    </I18nextProvider>,
  );

describe('AnswerFlow', () => {
  it('renders the same markup whether the steps arrived live or were fetched', () => {
    const live = render({
      message: 'part one part two',
      thought: 'reasoning here',
      toolCalls: [search()],
      // Live ordering interleaved the tool call with the answer text.
      segments: [
        { kind: 'thought', text: 'reasoning here' },
        { kind: 'tool', call_id: 'c1' },
      ],
    });
    const fetched = render({
      message: 'part one part two',
      thought: 'reasoning here',
      toolCalls: [search()],
    });
    expect(live).toBe(fetched);
  });

  it('keeps the answer in a single bubble with the steps above it', () => {
    const html = render({
      message: 'part one part two',
      toolCalls: [search()],
      segments: [{ kind: 'tool', call_id: 'c1' }],
    });
    expect(html.split('fade-in-bubble').length - 1).toBe(1);
    expect(html.indexOf('Searched the web')).toBeLessThan(
      html.indexOf('part one part two'),
    );
  });

  it('labels a running call in present tense and a finished one in past tense', () => {
    expect(
      render({
        toolCalls: [search({ status: 'pending' })],
        segments: [{ kind: 'tool', call_id: 'c1' }],
        isStreaming: true,
      }),
    ).toContain('Searching the web');
    expect(
      render({
        toolCalls: [search()],
        segments: [{ kind: 'tool', call_id: 'c1' }],
      }),
    ).toContain('Searched the web');
  });

  it('keeps tool arguments and results hidden until expanded', () => {
    const html = render({
      toolCalls: [search({ result: { secret: 'RESULT_BODY' } })],
      segments: [{ kind: 'tool', call_id: 'c1' }],
    });
    expect(html).not.toContain('RESULT_BODY');
  });

  it('routes a call awaiting approval to the approval bar, not a chip', () => {
    const html = render({
      toolCalls: [search({ status: 'awaiting_approval' })],
      segments: [{ kind: 'tool', call_id: 'c1' }],
    });
    expect(html).toContain('APPROVAL_BAR');
    expect(html).not.toContain('Searched the web');
  });

  it('puts reasoning before tool calls for a reloaded conversation', () => {
    const html = render({
      message: 'the answer',
      thought: 'my reasoning',
      toolCalls: [search()],
    });
    expect(html.indexOf('my reasoning')).toBeLessThan(
      html.indexOf('Searched the web'),
    );
    expect(html.indexOf('Searched the web')).toBeLessThan(
      html.indexOf('the answer'),
    );
  });

  it('ignores a step whose call is missing from tool_calls', () => {
    const html = render({
      toolCalls: [],
      segments: [{ kind: 'tool', call_id: 'gone' }],
    });
    expect(html).not.toContain('Searched');
  });

  it('renders steps with no answer text yet', () => {
    const html = render({
      toolCalls: [search({ status: 'pending' })],
      segments: [{ kind: 'tool', call_id: 'c1' }],
      isStreaming: true,
    });
    expect(html).toContain('Searching the web');
    expect(html).not.toContain('fade-in-bubble');
  });
});
