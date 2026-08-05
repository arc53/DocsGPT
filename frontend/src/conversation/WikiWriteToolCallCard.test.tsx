import i18n from 'i18next';
import { renderToStaticMarkup } from 'react-dom/server';
import { I18nextProvider, initReactI18next } from 'react-i18next';
import { beforeAll, describe, expect, it } from 'vitest';

import en from '../locale/en.json';
import AnswerFlow from './AnswerFlow';
import { WikiWriteToolCallCard } from './ConversationBubble';
import { ToolCallsType } from './types';

const testI18n = i18n.createInstance();

beforeAll(async () => {
  await testI18n.use(initReactI18next).init({
    lng: 'en',
    fallbackLng: 'en',
    resources: { en: { translation: en } },
  });
});

const render = (toolCall: ToolCallsType): string =>
  renderToStaticMarkup(
    <I18nextProvider i18n={testI18n}>
      <WikiWriteToolCallCard toolCall={toolCall} />
    </I18nextProvider>,
  );

describe('WikiWriteToolCallCard', () => {
  it('renders the edited-wiki treatment with the page path', () => {
    const html = render({
      tool_name: 'wiki',
      action_name: 'wiki_str_replace',
      call_id: 'c1',
      arguments: { path: '/policy.md', old_str: 'a', new_str: 'b' },
      status: 'completed',
    });
    expect(html).toContain('✏️');
    expect(html).toContain('Edited wiki page');
    expect(html).toContain('/policy.md');
  });

  it('uses the new path for a rename', () => {
    const html = render({
      tool_name: 'wiki',
      action_name: 'wiki_rename',
      call_id: 'c2',
      arguments: { old_path: '/a.md', new_path: '/b.md' },
      status: 'completed',
    });
    expect(html).toContain('Renamed wiki page');
    expect(html).toContain('/b.md');
  });

  it('still renders the action without a path when none is in the payload', () => {
    const html = render({
      tool_name: 'wiki',
      action_name: 'wiki_create',
      call_id: 'c3',
      arguments: {},
      status: 'completed',
    });
    expect(html).toContain('Created wiki page');
    expect(html).not.toContain('<code');
  });
});

describe('tool call placement in the answer flow', () => {
  const renderToolCalls = (toolCalls: ToolCallsType[]): string =>
    renderToStaticMarkup(
      <I18nextProvider i18n={testI18n}>
        <AnswerFlow
          toolCalls={toolCalls}
          renderApproval={() => null}
          renderWikiWrite={(toolCall) => (
            <WikiWriteToolCallCard toolCall={toolCall} />
          )}
        />
      </I18nextProvider>,
    );

  const wikiWrite: ToolCallsType = {
    tool_name: 'wiki',
    action_name: 'wiki_str_replace',
    call_id: 'w1',
    arguments: { path: '/policy.md', old_str: 'a', new_str: 'b' },
    status: 'completed',
  };

  const otherCall: ToolCallsType = {
    tool_name: 'memory',
    action_name: 'memory_search',
    call_id: 'm1',
    arguments: { query: 'secret-arg' },
    status: 'completed',
  };

  it('shows wiki write cards inline and keeps other call arguments collapsed', () => {
    const html = renderToolCalls([wikiWrite, otherCall]);
    expect(html).toContain('Edited wiki page');
    expect(html).toContain('/policy.md');
    expect(html).not.toContain('secret-arg');
  });

  it('renders each wiki write card exactly once', () => {
    const html = renderToolCalls([wikiWrite]);
    const occurrences = html.split('Edited wiki page').length - 1;
    expect(occurrences).toBe(1);
  });
});
