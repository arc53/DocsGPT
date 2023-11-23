import { Answer, FEEDBACK } from './conversationModels';
import { Doc } from '../preferences/preferenceApi';

const apiHost = import.meta.env.VITE_API_HOST || 'https://docsapi.arc53.com';

export function fetchAnswerApi(
  question: string,
  apiKey: string,
  selectedDocs: Doc,
  history: Array<any> = [],
  conversationId: string | null,
  promptId: string | null,
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
  let namePath = selectedDocs.name;
  if (selectedDocs.language === namePath) {
    namePath = '.project';
  }

  let docPath = 'default';
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
  }
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
      api_key: apiKey,
      embeddings_key: apiKey,
      history: history,
      active_docs: docPath,
      conversation_id: conversationId,
      prompt_id: promptId,
    }),
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
  apiKey: string,
  selectedDocs: Doc,
  history: Array<any> = [],
  conversationId: string | null,
  promptId: string | null,
  onEvent: (event: MessageEvent) => void,
): Promise<Answer> {
  let namePath = selectedDocs.name;
  if (selectedDocs.language === namePath) {
    namePath = '.project';
  }

  let docPath = 'default';
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
  }

  history = history.map((item) => {
    return { prompt: item.prompt, response: item.response };
  });

  return new Promise<Answer>((resolve, reject) => {
    const body = {
      question: question,
      api_key: apiKey,
      embeddings_key: apiKey,
      active_docs: docPath,
      history: JSON.stringify(history),
      conversation_id: conversationId,
      prompt_id: promptId,
    };

    fetch(apiHost + '/stream', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(body),
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
