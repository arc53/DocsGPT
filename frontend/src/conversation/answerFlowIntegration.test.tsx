import i18n from 'i18next';
import { renderToStaticMarkup } from 'react-dom/server';
import { I18nextProvider, initReactI18next } from 'react-i18next';
import { beforeAll, describe, expect, it } from 'vitest';

import en from '../locale/en.json';
import AnswerFlow from './AnswerFlow';
import reducer, {
  addQuery,
  setStatus,
  updateStreamingQuery,
  updateThought,
  updateToolCall,
} from './conversationSlice';
import { ToolCallsType } from './types';

const testI18n = i18n.createInstance();

beforeAll(async () => {
  await testI18n.use(initReactI18next).init({
    lng: 'en',
    fallbackLng: 'en',
    resources: { en: { translation: en } },
  });
});

const searchCall = (status: ToolCallsType['status']): ToolCallsType => ({
  tool_name: 'brave',
  action_name: 'brave_web_search',
  call_id: 'c1',
  arguments: { query: 'docsgpt' },
  status,
  ...(status === 'completed' ? { result: { hits: 1 } } : {}),
});

// Covers the seam the unit tests leave open: that the stream reducers produce
// exactly the shape AnswerFlow renders from.
describe('stream reducers feeding the answer flow', () => {
  it('records steps in arrival order and renders them above one answer bubble', () => {
    const at = { index: 0, conversationId: null };
    let state = reducer(undefined, addQuery({ prompt: 'hi' }));
    state = reducer(state, setStatus('loading'));
    state = reducer(
      state,
      updateThought({ ...at, query: { thought: 'I should search.' } }),
    );
    // The same call arrives twice, pending then completed.
    state = reducer(
      state,
      updateToolCall({ ...at, tool_call: searchCall('pending') }),
    );
    state = reducer(
      state,
      updateToolCall({ ...at, tool_call: searchCall('completed') }),
    );
    state = reducer(
      state,
      updateStreamingQuery({ ...at, query: { response: 'Docs' } }),
    );
    state = reducer(
      state,
      updateStreamingQuery({ ...at, query: { response: 'GPT rocks.' } }),
    );

    const query = state.queries[0];
    expect(query.segments).toEqual([
      { kind: 'thought', text: 'I should search.' },
      { kind: 'tool', call_id: 'c1' },
    ]);
    expect(query.response).toBe('DocsGPT rocks.');
    expect(query.tool_calls).toHaveLength(1);
    expect(query.tool_calls?.[0].status).toBe('completed');

    const html = renderToStaticMarkup(
      <I18nextProvider i18n={testI18n}>
        <AnswerFlow
          message={query.response}
          thought={query.thought}
          toolCalls={query.tool_calls}
          segments={query.segments}
          renderApproval={() => null}
          renderWikiWrite={() => null}
        />
      </I18nextProvider>,
    );

    expect(html.split('fade-in-bubble').length - 1).toBe(1);
    expect(html.indexOf('I should search.')).toBeLessThan(
      html.indexOf('Searched the web'),
    );
    expect(html.indexOf('Searched the web')).toBeLessThan(
      html.indexOf('DocsGPT rocks.'),
    );
  });
});
