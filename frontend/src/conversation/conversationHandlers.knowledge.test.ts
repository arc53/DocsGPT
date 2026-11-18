import { describe, expect, it, vi } from 'vitest';

const service = vi.hoisted(() => ({ answer: vi.fn() }));
vi.mock('../api/services/conversationService', () => ({ default: service }));

import type { Doc } from '../models/misc';
import {
  applySelectedKnowledge,
  handleFetchAnswer,
} from './conversationHandlers';
import type { RetrievalPayload } from './conversationModels';

const doc = (id: string): Doc =>
  ({ id, name: id, date: '', model: '', retriever: 'classic' }) as Doc;
const base = (): RetrievalPayload => ({
  question: 'q',
  conversation_id: null,
  chunks: '2',
  isNoneDoc: false,
});

describe('applySelectedKnowledge', () => {
  it('sends one source as an id and several as a list', () => {
    const one = base();
    applySelectedKnowledge(one, [doc('a')]);
    expect(one.active_docs).toBe('a');
    const two = base();
    applySelectedKnowledge(two, [doc('a'), doc('b')]);
    expect(two.active_docs).toEqual(['a', 'b']);
    expect(two.active_folders).toBeUndefined();
  });

  it('sends picked folders as active_folders, with or without sources', () => {
    const payload = base();
    applySelectedKnowledge(payload, [], ['carriers']);
    expect(payload.active_folders).toEqual(['carriers']);
    expect(payload.active_docs).toBeUndefined();
  });
});

describe('handleFetchAnswer with folders', () => {
  it('asks for retrieval when only a folder is picked', async () => {
    service.answer.mockResolvedValue({
      ok: true,
      json: async () => ({ answer: 'x' }),
    });
    await handleFetchAnswer(
      'q',
      new AbortController().signal,
      null,
      [],
      null,
      null,
      '2',
      undefined,
      undefined,
      true,
      undefined,
      undefined,
      ['carriers'],
    );
    const payload = service.answer.mock.calls[0][0] as RetrievalPayload;
    expect(payload.isNoneDoc).toBe(false);
    expect(payload.active_folders).toEqual(['carriers']);
  });
});
