import { beforeEach, describe, expect, it, vi } from 'vitest';

const service = vi.hoisted(() => ({ answerStream: vi.fn() }));
vi.mock('../api/services/conversationService', () => ({ default: service }));

import {
  handleFetchAnswerSteaming,
  handleSubmitToolActions,
} from './conversationHandlers';

// A stream that ends at once, as the server ends a finished turn.
const ended = () =>
  new Response(`data: ${JSON.stringify({ type: 'end' })}\n\n`, {
    headers: { 'Content-Type': 'text/event-stream' },
  });

describe('stream requests ask for question cards', () => {
  beforeEach(() => {
    service.answerStream.mockReset().mockImplementation(async () => ended());
  });

  it('on a new turn', async () => {
    await handleFetchAnswerSteaming(
      'write the deck',
      new AbortController().signal,
      'tok',
      [],
      'conv-1',
      null,
      '2',
      () => {},
    );
    expect(service.answerStream.mock.calls[0][0]).toMatchObject({
      question: 'write the deck',
      questions: 'cards',
    });
  });

  it('on a resume, answers included', async () => {
    await handleSubmitToolActions(
      'conv-1',
      [{ call_id: 'ask-1', answer: 'Which quarter? → Q3' }],
      'tok',
      new AbortController().signal,
      () => {},
    );
    expect(service.answerStream.mock.calls[0][0]).toEqual({
      conversation_id: 'conv-1',
      tool_actions: [{ call_id: 'ask-1', answer: 'Which quarter? → Q3' }],
      questions: 'cards',
    });
  });
});
