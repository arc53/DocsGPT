import { Answer, FEEDBACK } from './conversationModels';
import { Doc } from '../preferences/preferenceApi';

const apiHost = import.meta.env.VITE_API_HOST || 'https://docsapi.arc53.com';

export function fetchAnswerApi(
  question: string,
  apiKey: string,
  selectedDocs: Doc,
  history: Array<any> = [],
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
      return { answer: result, query: question, result };
    });
}

export function fetchAnswerSteaming(
  question: string,
  apiKey: string,
  selectedDocs: Doc,
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

  return new Promise<Answer>((resolve, reject) => {
    const url = new URL(apiHost + '/stream');
    url.searchParams.append('question', question);
    url.searchParams.append('api_key', apiKey);
    url.searchParams.append('embeddings_key', apiKey);
    url.searchParams.append('history', localStorage.getItem('chatHistory'));
    url.searchParams.append('active_docs', docPath);

    const eventSource = new EventSource(url.href);

    eventSource.onmessage = onEvent;

    eventSource.onerror = (error) => {
      console.log('Connection failed.');
      eventSource.close();
    };
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
