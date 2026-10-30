import { describe, expect, it } from 'vitest';

import { isLogLabel, logsDrilldownPath } from './logsLinks';

describe('logsDrilldownPath', () => {
  it("lands on the agent's Logs section with the filters in the URL", () => {
    expect(
      logsDrilldownPath({
        agentId: 'a1',
        conversationId: 'c 1',
        messageId: 'm1',
      }),
    ).toBe('/agents/manage/logs/a1?conversation=c+1&message=m1#logs');
    expect(logsDrilldownPath({ agentId: 'a1', label: 'docs_gap' })).toBe(
      '/agents/manage/logs/a1?label=docs_gap#logs',
    );
  });

  it("opens the account's Logs without an agent", () => {
    expect(logsDrilldownPath({ label: 'tag:a1b2c3d4' })).toBe(
      '/settings/logs?label=tag%3Aa1b2c3d4',
    );
    expect(logsDrilldownPath({})).toBe('/settings/logs');
  });
});

describe('isLogLabel', () => {
  it('accepts the filter labels, tag ids and topic names, nothing else', () => {
    expect(isLogLabel('docs_gap')).toBe(true);
    expect(isLogLabel('negative_reaction')).toBe(true);
    expect(isLogLabel('tag:a1b2c3d4')).toBe(true);
    expect(isLogLabel('tag:short')).toBe(false);
    expect(isLogLabel('topic:deploying')).toBe(true);
    expect(isLogLabel('topic:Pricing question')).toBe(true);
    expect(isLogLabel('topic: ')).toBe(false);
    expect(isLogLabel(`topic:${'n'.repeat(61)}`)).toBe(false);
    expect(isLogLabel('sentiment')).toBe(false);
    expect(isLogLabel(null)).toBe(false);
  });

  // The server counts a topic name in code points once stripped (Python's
  // `len(name.strip())`), so an emoji is one and padding doesn't count.
  it('measures a topic name as the server does: code points, stripped', () => {
    expect(isLogLabel(`topic:${'🚚'.repeat(60)}`)).toBe(true);
    expect(isLogLabel(`topic:${'🚚'.repeat(61)}`)).toBe(false);
    expect(isLogLabel(`topic:  ${'n'.repeat(60)}  `)).toBe(true);
    expect(isLogLabel(`topic: ${'n'.repeat(61)} `)).toBe(false);
    // Python's whitespace, not JavaScript's: it strips the separator
    // controls (U+001C to U+001F) and U+0085, and keeps U+FEFF.
    expect(isLogLabel('topic:\u001f\u0085')).toBe(false);
    expect(isLogLabel('topic:\ufeff')).toBe(true);
  });
});
