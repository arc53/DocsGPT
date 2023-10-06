import { Answer, FEEDBACK } from './conversationModels';
import { Doc } from '../preferences/preferenceApi';

const apiHost = import.meta.env.VITE_API_HOST || 'https://docsapi.arc53.com';

export function fetchAnswerApi(
  question: string,
  apiKey: string,
  selectedDocs: Doc,
  history: Array<any> = [],
  conversationId: string | null,
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
        title: data.title,
      };
    });
}

export function fetchSources(
  apiKey: string,
  selectedDocs: Doc,
  conversationId: string | null,
): Promise<any[]> {
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

  return fetch(apiHost + '/api/sources', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      api_key: apiKey,
      active_docs: docPath,
      conversation_id: conversationId,
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
      return data.sources;
    });
}

export function fetchAnswerSteaming(
  question: string,
  apiKey: string,
  selectedDocs: Doc,
  history: Array<any> = [],
  conversationId: string | null,
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

export function sendFeedback(
  prompt: string,
  response: string,
  feedback: FEEDBACK,
): Promise<void> {
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
