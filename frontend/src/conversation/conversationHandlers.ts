import conversationService from '../api/services/conversationService';
import { Doc } from '../models/misc';
import { Answer, FEEDBACK, RetrievalPayload } from './conversationModels';
import { ToolCallsType } from './types';

export function handleFetchAnswer(
  question: string,
  signal: AbortSignal,
  token: string | null,
  selectedDocs: Doc | null,
  conversationId: string | null,
  promptId: string | null,
  chunks: string,
  token_limit: number,
  agentId?: string,
  attachments?: string[],
  save_conversation = true,
): Promise<
  | {
      result: any;
      answer: any;
      thought: any;
      sources: any;
      toolCalls: ToolCallsType[];
      conversationId: any;
      query: string;
    }
  | {
      result: any;
      answer: any;
      thought: any;
      sources: any;
      toolCalls: ToolCallsType[];
      query: string;
      conversationId: any;
      title: any;
    }
> {
  const payload: RetrievalPayload = {
    question: question,
    conversation_id: conversationId,
    prompt_id: promptId,
    chunks: chunks,
    token_limit: token_limit,
    isNoneDoc: selectedDocs === null,
    agent_id: agentId,
    save_conversation: save_conversation,
  };

  // Add attachments to payload if they exist
  if (attachments && attachments.length > 0) {
    payload.attachments = attachments;
  }

  if (selectedDocs && 'id' in selectedDocs) {
    payload.active_docs = selectedDocs.id as string;
  }
  payload.retriever = selectedDocs?.retriever as string;
  return conversationService
    .answer(payload, token, signal)
    .then((response) => {
      if (response.ok) {
        return response.json();
      } else {
        return Promise.reject(new Error(response.statusText));
      }
    })
    .then((data) => {
      const result = data.answer;
      return {
        answer: result,
        query: question,
        result,
        thought: data.thought,
        sources: data.sources,
        toolCalls: data.tool_calls,
        conversationId: data.conversation_id,
        title: data.title || null,
      };
    });
}

export function handleFetchAnswerSteaming(
  question: string,
  signal: AbortSignal,
  token: string | null,
  selectedDocs: Doc | null,
  conversationId: string | null,
  promptId: string | null,
  chunks: string,
  token_limit: number,
  onEvent: (event: MessageEvent) => void,
  indx?: number,
  agentId?: string,
  attachments?: string[],
  save_conversation = true,
): Promise<Answer> {
  const payload: RetrievalPayload = {
    question: question,
    conversation_id: conversationId,
    prompt_id: promptId,
    chunks: chunks,
    token_limit: token_limit,
    isNoneDoc: selectedDocs === null,
    index: indx,
    agent_id: agentId,
    save_conversation: save_conversation,
  };

  // Add attachments to payload if they exist
  if (attachments && attachments.length > 0) {
    payload.attachments = attachments;
  }

  if (selectedDocs && 'id' in selectedDocs) {
    payload.active_docs = selectedDocs.id as string;
  }
  payload.retriever = selectedDocs?.retriever as string;

  return new Promise<Answer>((resolve, reject) => {
    conversationService
      .answerStream(payload, token, signal)
      .then((response) => {
        if (!response.body) throw Error('No response body');

        let buffer = '';
        const reader = response.body.getReader();
        const decoder = new TextDecoder('utf-8');
        let counterrr = 0;
        const processStream = ({
          done,
          value,
        }: ReadableStreamReadResult<Uint8Array>) => {
          if (done) return;

          counterrr += 1;

          const chunk = decoder.decode(value);
          buffer += chunk;

          const events = buffer.split('\n\n');
          buffer = events.pop() ?? '';

          for (const event of events) {
            if (event.trim().startsWith('data:')) {
              const dataLine: string = event
                .split('\n')
                .map((line: string) => line.replace(/^data:\s?/, ''))
                .join('');

              const messageEvent = new MessageEvent('message', {
                data: dataLine.trim(),
              });

              onEvent(messageEvent);
            }
          }

          reader.read().then(processStream).catch(reject);
        };

        reader.read().then(processStream).catch(reject);
      })
      .catch((error) => {
        console.error('Connection failed:', error);
        reject(error);
      });
  });
}

export function handleSearch(
  question: string,
  token: string | null,
  selectedDocs: Doc | null,
  conversation_id: string | null,
  chunks: string,
  token_limit: number,
) {
  const payload: RetrievalPayload = {
    question: question,
    conversation_id: conversation_id,
    chunks: chunks,
    token_limit: token_limit,
    isNoneDoc: selectedDocs === null,
  };
  if (selectedDocs && 'id' in selectedDocs)
    payload.active_docs = selectedDocs.id as string;
  payload.retriever = selectedDocs?.retriever as string;
  return conversationService
    .search(payload, token)
    .then((response) => response.json())
    .then((data) => {
      return data;
    })
    .catch((err) => console.log(err));
}

export function handleSearchViaApiKey(
  question: string,
  api_key: string,
  history: Array<any> = [],
) {
  history = history.map((item) => {
    return {
      prompt: item.prompt,
      response: item.response,
      tool_calls: item.tool_calls,
    };
  });
  return conversationService
    .search(
      {
        question: question,
        history: JSON.stringify(history),
        api_key: api_key,
      },
      null,
    )
    .then((response) => response.json())
    .then((data) => {
      return data;
    })
    .catch((err) => console.log(err));
}

export function handleSendFeedback(
  prompt: string,
  response: string,
  feedback: FEEDBACK,
  conversation_id: string,
  prompt_index: number,
  token: string | null,
) {
  return conversationService
    .feedback(
      {
        question: prompt,
        answer: response,
        feedback: feedback,
        conversation_id: conversation_id,
        question_index: prompt_index,
      },
      token,
    )
    .then((response) => {
      if (response.ok) {
        return Promise.resolve();
      } else {
        return Promise.reject();
      }
    });
}

export function handleFetchSharedAnswerStreaming(
  question: string,
  signal: AbortSignal,
  apiKey: string,
  history: Array<any> = [],
  attachments: string[] = [],
  onEvent: (event: MessageEvent) => void,
): Promise<Answer> {
  history = history.map((item) => {
    return {
      prompt: item.prompt,
      response: item.response,
      tool_calls: item.tool_calls,
    };
  });

  return new Promise<Answer>((resolve, reject) => {
    const payload = {
      question: question,
      history: JSON.stringify(history),
      api_key: apiKey,
      save_conversation: false,
      attachments: attachments.length > 0 ? attachments : undefined,
    };
    conversationService
      .answerStream(payload, null, signal)
      .then((response) => {
        if (!response.body) throw Error('No response body');

        const reader = response.body.getReader();
        const decoder = new TextDecoder('utf-8');
        let counterrr = 0;
        const processStream = ({
          done,
          value,
        }: ReadableStreamReadResult<Uint8Array>) => {
          if (done) {
            console.log(counterrr);
            return;
          }

          counterrr += 1;

          const chunk = decoder.decode(value);

          const lines = chunk.split('\n');

          for (let line of lines) {
            if (line.trim() == '') {
              continue;
            }
            if (line.startsWith('data:')) {
              line = line.substring(5);
            }

            const messageEvent: MessageEvent = new MessageEvent('message', {
              data: line,
            });

            onEvent(messageEvent); // handle each message
          }

          reader.read().then(processStream).catch(reject);
        };

        reader.read().then(processStream).catch(reject);
      })
      .catch((error) => {
        console.error('Connection failed:', error);
        reject(error);
      });
  });
}

export function handleFetchSharedAnswer(
  question: string,
  signal: AbortSignal,
  apiKey: string,
  attachments?: string[],
): Promise<
  | {
      result: any;
      answer: any;
      sources: any;
      query: string;
    }
  | {
      result: any;
      answer: any;
      sources: any;
      query: string;
      title: any;
    }
> {
  const payload = {
    question: question,
    api_key: apiKey,
    attachments:
      attachments && attachments.length > 0 ? attachments : undefined,
  };

  return conversationService
    .answer(payload, null, signal)
    .then((response) => {
      if (response.ok) {
        return response.json();
      } else {
        return Promise.reject(new Error(response.statusText));
      }
    })
    .then((data) => {
      const result = data.answer;
      return {
        answer: result,
        query: question,
        result,
        sources: data.sources,
        toolCalls: data.tool_calls,
      };
    });
}
