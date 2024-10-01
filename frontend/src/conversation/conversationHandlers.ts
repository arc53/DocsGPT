import conversationService from '../api/services/conversationService';
import { Doc } from '../models/misc';
import { Answer, FEEDBACK, RetrievalPayload } from './conversationModels';

export function handleFetchAnswer(
  question: string,
  signal: AbortSignal,
  selectedDocs: Doc | null,
  history: Array<any> = [],
  conversationId: string | null,
  promptId: string | null,
  chunks: string,
  token_limit: number,
): Promise<
  | {
      result: any;
      answer: any;
      sources: any;
      conversationId: any;
      query: string;
    }
  | {
      result: any;
      answer: any;
      sources: any;
      query: string;
      conversationId: any;
      title: any;
    }
> {
  history = history.map((item) => {
    return { prompt: item.prompt, response: item.response };
  });
  const payload: RetrievalPayload = {
    question: question,
    history: JSON.stringify(history),
    conversation_id: conversationId,
    prompt_id: promptId,
    chunks: chunks,
    token_limit: token_limit,
  };
  if (selectedDocs && 'id' in selectedDocs)
    payload.active_docs = selectedDocs.id as string;
  payload.retriever = selectedDocs?.retriever as string;
  return conversationService
    .answer(payload, signal)
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
        conversationId: data.conversation_id,
      };
    });
}

export function handleFetchAnswerSteaming(
  question: string,
  signal: AbortSignal,
  selectedDocs: Doc | null,
  history: Array<any> = [],
  conversationId: string | null,
  promptId: string | null,
  chunks: string,
  token_limit: number,
  onEvent: (event: MessageEvent) => void,
): Promise<Answer> {
  history = history.map((item) => {
    return { prompt: item.prompt, response: item.response };
  });
  const payload: RetrievalPayload = {
    question: question,
    history: JSON.stringify(history),
    conversation_id: conversationId,
    prompt_id: promptId,
    chunks: chunks,
    token_limit: token_limit,
  };
  if (selectedDocs && 'id' in selectedDocs)
    payload.active_docs = selectedDocs.id as string;
  payload.retriever = selectedDocs?.retriever as string;

  return new Promise<Answer>((resolve, reject) => {
    conversationService
      .answerStream(
        {
          question: question,
          active_docs: selectedDocs?.id as string,
          history: JSON.stringify(history),
          conversation_id: conversationId,
          prompt_id: promptId,
          chunks: chunks,
          token_limit: token_limit,
          isNoneDoc: selectedDocs === null,
        },
        signal,
      )
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
  selectedDocs: Doc | null,
  conversation_id: string | null,
  history: Array<any> = [],
  chunks: string,
  token_limit: number,
) {
  history = history.map((item) => {
    return { prompt: item.prompt, response: item.response };
  });
  const payload: RetrievalPayload = {
    question: question,
    history: JSON.stringify(history),
    conversation_id: conversation_id,
    chunks: chunks,
    token_limit: token_limit,
  };
  if (selectedDocs && 'id' in selectedDocs)
    payload.active_docs = selectedDocs.id as string;
  payload.retriever = selectedDocs?.retriever as string;
  return conversationService
    .search({
      question: question,
      active_docs: selectedDocs?.id as string,
      conversation_id,
      history,
      chunks: chunks,
      token_limit: token_limit,
      isNoneDoc: selectedDocs === null,
    })
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
    return { prompt: item.prompt, response: item.response };
  });
  return conversationService
    .search({
      question: question,
      history: JSON.stringify(history),
      api_key: api_key,
    })
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
) {
  return conversationService
    .feedback({
      question: prompt,
      answer: response,
      feedback: feedback,
    })
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
    return { prompt: item.prompt, response: item.response };
  });

  return new Promise<Answer>((resolve, reject) => {
    const payload = {
      question: question,
      history: JSON.stringify(history),
      api_key: apiKey,
    };
    conversationService
      .answerStream(payload, signal)
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
      };
    });
}
