import conversationService from '../api/services/conversationService';
import { Doc } from '../models/misc';
import { Answer, FEEDBACK, RetrievalPayload } from './conversationModels';
import { ToolCallsType } from './types';

export function handleFetchAnswer(
  question: string,
  signal: AbortSignal,
  token: string | null,
  selectedDocs: Doc[],
  conversationId: string | null,
  promptId: string | null,
  chunks: string,
  agentId?: string,
  attachments?: string[],
  save_conversation = true,
  modelId?: string,
  imageBase64?: string,
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
    isNoneDoc: selectedDocs.length === 0,
    agent_id: agentId,
    save_conversation: save_conversation,
  };

  if (modelId) {
    payload.model_id = modelId;
  }

  if (imageBase64) {
    payload.image_base64 = imageBase64; 
  }

  if (attachments && attachments.length > 0) {
    payload.attachments = attachments;
  }

  if (selectedDocs.length > 0) {
    if (selectedDocs.length > 1) {
      payload.active_docs = selectedDocs.map((doc) => doc.id!);
      payload.retriever = selectedDocs[0]?.retriever as string;
    } else if (selectedDocs.length === 1 && 'id' in selectedDocs[0]) {
      payload.active_docs = selectedDocs[0].id as string;
      payload.retriever = selectedDocs[0].retriever as string;
    }
  }
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
  selectedDocs: Doc[],
  conversationId: string | null,
  promptId: string | null,
  chunks: string,
  onEvent: (event: MessageEvent) => void,
  indx?: number,
  agentId?: string,
  attachments?: string[],
  save_conversation = true,
  modelId?: string,
  imageBase64?: string,
): Promise<Answer> {
  const payload: RetrievalPayload = {
    question: question,
    conversation_id: conversationId,
    prompt_id: promptId,
    chunks: chunks,
    isNoneDoc: selectedDocs.length === 0,
    index: indx,
    agent_id: agentId,
    save_conversation: save_conversation,
  };

  if (modelId) {
    payload.model_id = modelId;
  }

  if (imageBase64) {
    payload.image_base64 = imageBase64;
  }

  if (attachments && attachments.length > 0) {
    payload.attachments = attachments;
  }

  if (selectedDocs.length > 0) {
    if (selectedDocs.length > 1) {
      payload.active_docs = selectedDocs.map((doc) => doc.id!);
      payload.retriever = selectedDocs[0]?.retriever as string;
    } else if (selectedDocs.length === 1 && 'id' in selectedDocs[0]) {
      payload.active_docs = selectedDocs[0].id as string;
      payload.retriever = selectedDocs[0].retriever as string;
    }
  }

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

export function handleSubmitToolActions(
  conversationId: string,
  toolActions: {
    call_id: string;
    decision?: 'approved' | 'denied';
    comment?: string;
    result?: Record<string, any>;
  }[],
  token: string | null,
  signal: AbortSignal,
  onEvent: (event: MessageEvent) => void,
): Promise<Answer> {
  const payload = {
    conversation_id: conversationId,
    tool_actions: toolActions,
  };

  return new Promise<Answer>((resolve, reject) => {
    conversationService
      .answerStream(payload, token, signal)
      .then((response) => {
        if (!response.body) throw Error('No response body');

        let buffer = '';
        const reader = response.body.getReader();
        const decoder = new TextDecoder('utf-8');

        const processStream = ({
          done,
          value,
        }: ReadableStreamReadResult<Uint8Array>) => {
          if (done) return;

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
        console.error('Tool actions submission failed:', error);
        reject(error);
      });
  });
}

/**
 * Stream a chat completion via the /v1/chat/completions endpoint.
 *
 * Translates the standard streaming format (choices[0].delta) back into
 * the internal DocsGPT event shape so the existing Redux reducers can
 * consume the events without any changes.
 */
export function handleV1ChatCompletionStreaming(
  question: string,
  signal: AbortSignal,
  agentApiKey: string,
  history: { prompt: string; response: string }[],
  onEvent: (event: MessageEvent) => void,
  tools?: any[],
  attachments?: string[],
): Promise<Answer> {
  // Build messages array from history + current question
  const messages: any[] = [];
  for (const h of history) {
    messages.push({ role: 'user', content: h.prompt });
    messages.push({ role: 'assistant', content: h.response });
  }
  messages.push({ role: 'user', content: question });

  const payload: any = {
    messages,
    stream: true,
  };
  if (tools && tools.length > 0) {
    payload.tools = tools;
  }
  if (attachments && attachments.length > 0) {
    payload.docsgpt = { attachments };
  }

  return new Promise<Answer>((resolve, reject) => {
    conversationService
      .chatCompletions(payload, agentApiKey, signal)
      .then((response) => {
        if (!response.body) throw Error('No response body');

        let buffer = '';
        const reader = response.body.getReader();
        const decoder = new TextDecoder('utf-8');

        const processStream = ({
          done,
          value,
        }: ReadableStreamReadResult<Uint8Array>) => {
          if (done) return;

          const chunk = decoder.decode(value);
          buffer += chunk;

          const events = buffer.split('\n\n');
          buffer = events.pop() ?? '';

          for (const event of events) {
            if (!event.trim().startsWith('data:')) continue;

            const dataLine = event
              .split('\n')
              .map((line: string) => line.replace(/^data:\s?/, ''))
              .join('');

            const trimmed = dataLine.trim();

            // Handle [DONE] sentinel
            if (trimmed === '[DONE]') {
              onEvent(
                new MessageEvent('message', {
                  data: JSON.stringify({ type: 'end' }),
                }),
              );
              continue;
            }

            try {
              const parsed = JSON.parse(trimmed);
              // Translate standard format to DocsGPT internal events
              const translated = translateV1ChunkToInternalEvents(parsed);
              for (const evt of translated) {
                onEvent(
                  new MessageEvent('message', {
                    data: JSON.stringify(evt),
                  }),
                );
              }
            } catch {
              // Skip unparseable chunks
            }
          }

          reader.read().then(processStream).catch(reject);
        };

        reader.read().then(processStream).catch(reject);
      })
      .catch((error) => {
        console.error('V1 chat completion stream failed:', error);
        reject(error);
      });
  });
}

/**
 * Translate a single v1 streaming chunk to internal DocsGPT event(s).
 *
 * Standard format: {"choices": [{"delta": {"content": "chunk"}, ...}]}
 * Extension format: {"docsgpt": {"type": "source", ...}}
 */
function translateV1ChunkToInternalEvents(
  chunk: any,
): { type: string; [key: string]: any }[] {
  const events: { type: string; [key: string]: any }[] = [];

  // DocsGPT extension chunks
  if (chunk.docsgpt) {
    const ext = chunk.docsgpt;
    if (ext.type === 'source') {
      events.push({ type: 'source', source: ext.sources });
    } else if (ext.type === 'tool_call') {
      events.push({ type: 'tool_call', data: ext.data });
    } else if (ext.type === 'tool_calls_pending') {
      events.push({
        type: 'tool_calls_pending',
        data: { pending_tool_calls: ext.pending_tool_calls },
      });
    } else if (ext.type === 'id') {
      events.push({ type: 'id', id: ext.conversation_id });
    }
    return events;
  }

  // Error chunks
  if (chunk.error) {
    events.push({ type: 'error', error: chunk.error.message || 'Error' });
    return events;
  }

  // Standard choices chunks
  const choice = chunk.choices?.[0];
  if (!choice) return events;

  const delta = choice.delta || {};
  const finishReason = choice.finish_reason;

  if (delta.content) {
    events.push({ type: 'answer', answer: delta.content });
  }

  if (delta.reasoning_content) {
    events.push({ type: 'thought', thought: delta.reasoning_content });
  }

  if (delta.tool_calls) {
    for (const tc of delta.tool_calls) {
      let parsedArgs: Record<string, any> = {};
      if (tc.function?.arguments) {
        try {
          parsedArgs = JSON.parse(tc.function.arguments);
        } catch {
          // Arguments may arrive as fragments during streaming;
          // keep the raw string so downstream can accumulate it.
          parsedArgs = { _raw: tc.function.arguments };
        }
      }
      events.push({
        type: 'tool_call',
        data: {
          call_id: tc.id,
          action_name: tc.function?.name || '',
          tool_name: tc.function?.name || '',
          arguments: parsedArgs,
          status: 'requires_client_execution',
        },
      });
    }
  }

  if (finishReason === 'stop') {
    events.push({ type: 'end' });
  } else if (finishReason === 'tool_calls') {
    events.push({
      type: 'tool_calls_pending',
      data: { pending_tool_calls: [] },
    });
  }

  return events;
}

export function handleSearch(
  question: string,
  token: string | null,
  selectedDocs: Doc[],
  conversation_id: string | null,
  chunks: string,
) {
  const payload: RetrievalPayload = {
    question: question,
    conversation_id: conversation_id,
    chunks: chunks,
    isNoneDoc: selectedDocs.length === 0,
  };
  if (selectedDocs.length > 0) {
    if (selectedDocs.length > 1) {
      payload.active_docs = selectedDocs.map((doc) => doc.id!);
      payload.retriever = selectedDocs[0]?.retriever as string;
    } else if (selectedDocs.length === 1 && 'id' in selectedDocs[0]) {
      payload.active_docs = selectedDocs[0].id as string;
      payload.retriever = selectedDocs[0].retriever as string;
    }
  }
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
  imageBase64: string | undefined,
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
      image_base64: imageBase64,
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

            onEvent(messageEvent);
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
  imageBase64?: string,
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
    image_base64: imageBase64, 
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