import conversationService from '../api/services/conversationService';
import { Doc } from '../models/misc';
import { Answer, FEEDBACK, RetrievalPayload } from './conversationModels';
import { ToolCallsType } from './types';

export function handleFetchAnswer(
  question: string,
  signal: AbortSignal,
  token: string | null,
  selectedDocs: Doc | null,
  history: Array<any> = [],
  conversationId: string | null,
  promptId: string | null,
  proxyId: string | null,
  chunks: string,
  token_limit: number,
): Promise<
  | {
      result: any;
      answer: any;
      sources: any;
      toolCalls: ToolCallsType[];
      conversationId: any;
      query: string;
    }
  | {
      result: any;
      answer: any;
      sources: any;
      toolCalls: ToolCallsType[];
      query: string;
      conversationId: any;
      title: any;
    }
> {
  history = history.map((item) => {
    return {
      prompt: item.prompt,
      response: item.response,
      tool_calls: item.tool_calls,
    };
  });
  const payload: RetrievalPayload = {
    question: question,
    history: JSON.stringify(history),
    conversation_id: conversationId,
    prompt_id: promptId,
    proxy_id: proxyId,
    chunks: chunks,
    token_limit: token_limit,
    isNoneDoc: selectedDocs === null,
  };
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
        sources: data.sources,
        toolCalls: data.tool_calls,
        conversationId: data.conversation_id,
      };
    });
}

export function handleFetchAnswerSteaming(
  question: string,
  signal: AbortSignal,
  token: string | null,
  selectedDocs: Doc | null,
  history: Array<any> = [],
  conversationId: string | null,
  promptId: string | null,
  proxyId: string | null,
  chunks: string,
  token_limit: number,
  onEvent: (event: MessageEvent) => void,
  indx?: number,
): Promise<Answer> {
  history = history.map((item) => {
    return {
      prompt: item.prompt,
      response: item.response,
      tool_calls: item.tool_calls,
    };
  });
  const payload: RetrievalPayload = {
    question: question,
    history: JSON.stringify(history),
    conversation_id: conversationId,
    prompt_id: promptId,
    proxy_id: proxyId,
    chunks: chunks,
    token_limit: token_limit,
    isNoneDoc: selectedDocs === null,
    index: indx,
  };
  if (selectedDocs && 'id' in selectedDocs) {
    payload.active_docs = selectedDocs.id as string;
  }
  payload.retriever = selectedDocs?.retriever as string;

  return new Promise<Answer>((resolve, reject) => {
    conversationService
      .answerStream(payload, token, signal)
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

export function handleSearch(
  question: string,
  token: string | null,
  selectedDocs: Doc | null,
  conversation_id: string | null,
  history: Array<any> = [],
  chunks: string,
  token_limit: number,
) {
  history = history.map((item) => {
    return {
      prompt: item.prompt,
      response: item.response,
      tool_calls: item.tool_calls,
    };
  });
  const payload: RetrievalPayload = {
    question: question,
    history: JSON.stringify(history),
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

export function handleFetchSharedAnswerStreaming( //for shared conversations
  question: string,
  signal: AbortSignal,
  apiKey: string,
  history: Array<any> = [],
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
  return conversationService
    .answer(
      {
        question: question,
        api_key: apiKey,
      },
      null,
      signal,
    )
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
