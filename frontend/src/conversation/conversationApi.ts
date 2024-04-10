import { Answer, FEEDBACK } from './conversationModels';
import { Doc } from '../preferences/preferenceApi';

const apiHost = import.meta.env.VITE_API_HOST || 'https://docsapi.arc53.com';

function getDocPath(selectedDocs: Doc | null): string {
  let docPath = 'default';

  if (selectedDocs) {
    let namePath = selectedDocs.name;
    if (selectedDocs.language === namePath) {
      namePath = '.project';
    }
    if (selectedDocs.location === 'local') {
      docPath = 'local' + '/' + selectedDocs.name + '/';
    } else if (selectedDocs.location === 'remote') {
      docPath =
        selectedDocs.language +
        '/' +
        namePath +
        '/' +
        selectedDocs.version +
        '/' +
        selectedDocs.model +
        '/';
    } else if (selectedDocs.location === 'custom') {
      docPath = selectedDocs.docLink;
    }
  }

  return docPath;
}
export function fetchAnswerApi(
  question: string,
  signal: AbortSignal,
  selectedDocs: Doc | null,
  history: Array<any> = [],
  conversationId: string | null,
  promptId: string | null,
  chunks: string,
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
  const docPath = getDocPath(selectedDocs);
  //in history array remove all keys except prompt and response
  history = history.map((item) => {
    return { prompt: item.prompt, response: item.response };
  });

  return fetch(apiHost + '/api/answer', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      question: question,
      history: history,
      active_docs: docPath,
      conversation_id: conversationId,
      prompt_id: promptId,
      chunks: chunks,
    }),
    signal,
  })
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

export function fetchAnswerSteaming(
  question: string,
  signal: AbortSignal,
  selectedDocs: Doc | null,
  history: Array<any> = [],
  conversationId: string | null,
  promptId: string | null,
  chunks: string,
  onEvent: (event: MessageEvent) => void,
): Promise<Answer> {
  const docPath = getDocPath(selectedDocs);

  history = history.map((item) => {
    return { prompt: item.prompt, response: item.response };
  });

  return new Promise<Answer>((resolve, reject) => {
    const body = {
      question: question,
      active_docs: docPath,
      history: JSON.stringify(history),
      conversation_id: conversationId,
      prompt_id: promptId,
      chunks: chunks,
    };
    fetch(apiHost + '/stream', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(body),
      signal,
    })
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
export function searchEndpoint(
  question: string,
  selectedDocs: Doc | null,
  conversation_id: string | null,
  history: Array<any> = [],
  chunks: string,
) {
  const docPath = getDocPath(selectedDocs);

  const body = {
    question: question,
    active_docs: docPath,
    conversation_id,
    history,
    chunks: chunks,
  };
  return fetch(`${apiHost}/api/search`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(body),
  })
    .then((response) => response.json())
    .then((data) => {
      return data;
    })
    .catch((err) => console.log(err));
}
export function sendFeedback(
  prompt: string,
  response: string,
  feedback: FEEDBACK,
) {
  return fetch(`${apiHost}/api/feedback`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      question: prompt,
      answer: response,
      feedback: feedback,
    }),
  }).then((response) => {
    if (response.ok) {
      return Promise.resolve();
    } else {
      return Promise.reject();
    }
  });
}
