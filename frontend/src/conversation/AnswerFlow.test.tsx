import { configureStore } from '@reduxjs/toolkit';
import i18n from 'i18next';
import { renderToStaticMarkup } from 'react-dom/server';
import { I18nextProvider, initReactI18next } from 'react-i18next';
import { Provider } from 'react-redux';
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
  suppressStatusLine?: boolean;
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
  it('shows the webhook link a monitor made as its link card, with Reveal secret when signed', () => {
    const store = configureStore({
      reducer: { preference: () => ({ token: null }) },
    });
    const call = search({
      tool_name: 'monitor',
      action_name: 'monitor_create',
      result: JSON.stringify({
        monitor_id: 'm-1',
        url: 'https://docs.example.com/api/triggers/trg_abc',
        signature: 'github',
        secret:
          'hidden from you; the user reveals it on the link card in this chat',
      }),
    });
    const html = renderToStaticMarkup(
      <Provider store={store}>
        <I18nextProvider i18n={testI18n}>
          <AnswerFlow
            toolCalls={[call]}
            renderApproval={() => null}
            renderWikiWrite={() => null}
          />
        </I18nextProvider>
      </Provider>,
    );
    expect(html).toContain('Webhook link');
    expect(html).toContain('https://docs.example.com/api/triggers/trg_abc');
    expect(html).toContain('Reveal secret');
  });

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
    expect(html.split('slide-in-from-bottom-1.5').length - 1).toBe(1);
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

  it('draws the reasoning icon muted, like the Sources and Tools rows', () => {
    const html = render({ thought: 'my reasoning' });
    expect(html).toMatch(/class="[^"]*lucide-cloud[^"]*text-muted-foreground/);
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
    expect(html).not.toContain('slide-in-from-bottom-1.5');
  });
});

describe('AnswerFlow activity indicator', () => {
  const thoughtThenCall: AnswerSegment[] = [
    { kind: 'thought', text: 'reasoning here' },
    { kind: 'tool', call_id: 'c1' },
  ];

  it('shows the status line once every step has settled', () => {
    const html = render({
      thought: 'reasoning here',
      toolCalls: [search()],
      segments: thoughtThenCall,
      isStreaming: true,
    });
    expect(html).toContain('Thinking…');
  });

  it('leaves the status line out while a call is still running', () => {
    const html = render({
      thought: 'reasoning here',
      toolCalls: [search({ status: 'pending' })],
      segments: thoughtThenCall,
      isStreaming: true,
    });
    expect(html).not.toContain('Thinking…');
    expect(html).toContain('Searching the web');
  });

  it('leaves the status line out while reasoning is the live step', () => {
    const html = render({
      thought: 'reasoning here',
      segments: [{ kind: 'thought', text: 'reasoning here' }],
      isStreaming: true,
    });
    expect(html).not.toContain('Thinking…');
    expect(html).toContain('shimmer-text');
  });

  it('says it is generating once answer text has started', () => {
    const html = render({
      message: 'the answer',
      thought: 'reasoning here',
      toolCalls: [search()],
      segments: thoughtThenCall,
      isStreaming: true,
    });
    expect(html).toContain('Generating…');
  });

  it('stays quiet when the answer is no longer streaming', () => {
    const html = render({
      thought: 'reasoning here',
      toolCalls: [search()],
      segments: thoughtThenCall,
    });
    expect(html).not.toContain('Thinking…');
  });

  it('defers to a run that already shows its own progress', () => {
    const html = render({
      toolCalls: [search()],
      segments: [{ kind: 'tool', call_id: 'c1' }],
      isStreaming: true,
      suppressStatusLine: true,
    });
    expect(html).not.toContain('Thinking…');
  });

  it('treats a call handed to the client as still running', () => {
    const html = render({
      toolCalls: [search({ status: 'requires_client_execution' })],
      segments: [{ kind: 'tool', call_id: 'c1' }],
      isStreaming: true,
    });
    expect(html).not.toContain('Thinking…');
    expect(html).toContain('Searching the web');
  });
});

describe('AnswerFlow step groups', () => {
  const todo = (id: string, overrides: Partial<ToolCallsType> = {}) =>
    search({
      call_id: id,
      tool_name: 'todo_list',
      action_name: 'todo_create',
      arguments: { title: `Task ${id}` },
      ...overrides,
    });
  const calls = [
    todo('a'),
    todo('b', {
      tool_name: 'cryptoprice',
      action_name: 'cryptoprice_get',
      arguments: { symbol: 'BTC', currency: 'EUR' },
      status: 'error',
    }),
    todo('c'),
  ];
  const run: AnswerSegment[] = [
    { kind: 'text', text: 'Now step 2:' },
    { kind: 'tool', call_id: 'a' },
    { kind: 'text', text: 'The price API returned 401, trying again:' },
    { kind: 'tool', call_id: 'b' },
    { kind: 'tool', call_id: 'c' },
    { kind: 'text', text: 'All done.' },
  ];
  const message =
    'Now step 2:The price API returned 401, trying again:All done.';

  it('folds three steps into one closed row with the failure count', () => {
    const html = render({ message, toolCalls: calls, segments: run });
    // The Sources row's shape: the label, then the count in its own span.
    expect(html).toMatch(/>Tools<\/span><span[^>]*>3<\/span>/);
    expect(html).toContain('1 failed');
    expect(html).toContain('aria-expanded="false"');
    // The rows stay mounted inside the closed Collapsible, inert.
    expect(html).toContain('inert');
    expect(html).toContain('Added todo “Task a”');
    expect(html).toContain('Checked the BTC price in EUR');
  });

  it('keeps the answer text where it was written around the group', () => {
    const html = render({ message, toolCalls: calls, segments: run });
    expect(html.indexOf('Now step 2:')).toBeLessThan(html.indexOf('>Tools<'));
    expect(html.indexOf('>Tools<')).toBeLessThan(html.indexOf('All done.'));
    // Narration between calls sits in the group, not in an answer bubble.
    expect(html.split('slide-in-from-bottom-1.5').length - 1).toBe(2);
    expect(html).toContain('The price API returned 401, trying again:');
  });

  it('opens a live window while the group is the end of a streaming answer', () => {
    const live = render({
      message: 'Now step 2:The price API returned 401, trying again:',
      toolCalls: [...calls.slice(0, 2), todo('c', { status: 'pending' })],
      segments: run.slice(0, 5),
      isStreaming: true,
    });
    expect(live).toContain('aria-expanded="true"');
    expect(live).toContain('h-21');
    expect(live).toContain('Adding todo “Task c”…');

    const settled = render({
      message,
      toolCalls: calls,
      segments: run,
      isStreaming: true,
    });
    expect(settled).not.toContain('h-21');
    expect(settled).toContain('aria-expanded="false"');
  });

  it('shows the result of a call that failed in-band', () => {
    const html = render({
      toolCalls: [todo('b', { status: 'error', result: { status_code: 401 } })],
      segments: [{ kind: 'tool', call_id: 'b' }],
    });
    expect(html).toContain('failed');
  });
});
