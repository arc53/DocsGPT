import { describe, expect, it } from 'vitest';

import {
  KNOWLEDGE_LINK_PARAMS,
  knowledgeLink,
  readKnowledgeLink,
} from './knowledgeLink';

const params = (url: string) => new URL(url, 'http://x').searchParams;

describe('knowledgeLink', () => {
  it('links a chunk by id, a search and its file', () => {
    const url = knowledgeLink({
      sourceId: 's1',
      chunk: { id: '42', search: 'a'.repeat(120), path: 'legal/msa.pdf' },
    });
    expect(url.startsWith('/settings/knowledge?')).toBe(true);
    const p = params(url);
    expect(p.get('source')).toBe('s1');
    expect(p.get('chunk')).toBe('42');
    expect(p.get('path')).toBe('legal/msa.pdf');
    // The chunk browser matches a substring; the excerpt's start is enough.
    expect(p.get('q')).toHaveLength(80);
  });

  it('never uses `page`, which is the list pagination', () => {
    const url = knowledgeLink({ sourceId: 's1', wikiPage: 'guide/leave.md' });
    expect(params(url).get('page')).toBeNull();
    expect(params(url).get('wikiPage')).toBe('guide/leave.md');
    expect(KNOWLEDGE_LINK_PARAMS).not.toContain('page');
  });

  it('reads back what it writes', () => {
    const link = {
      sourceId: 's1',
      chunk: { id: '42', search: 'late pickup', path: 'a.md' },
      wikiPage: 'w.md',
    };
    expect(readKnowledgeLink(params(knowledgeLink(link)))).toEqual(link);
  });

  it('reads a source with no chunk, and nothing without a source', () => {
    expect(readKnowledgeLink(params('/?source=s1'))).toEqual({
      sourceId: 's1',
    });
    expect(readKnowledgeLink(params('/?page=2&chunk=4'))).toBeNull();
  });
});
