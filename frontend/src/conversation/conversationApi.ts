import { Answer, FEEDBACK } from './conversationModels';
import { Doc } from '../preferences/preferenceApi';

const apiHost = import.meta.env.VITE_API_HOST || 'https://docsapi.arc53.com';

export function fetchAnswerApi(
  question: string,
  apiKey: string,
  selectedDocs: Doc,
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
      history: localStorage.getItem('chatHistory'),
      active_docs: docPath,
    }),
  })
    .then((response) => {
      if (response.ok) {
        return response.json();
      } else {
        Promise.reject(response);
      }
    })
    .then((data) => {
      let result = data.answer;
      const sources = data.sources;
      const titlesSet = new Set<string>();
      if (sources) {
        result += '\n\n**For more information, please check:** \n';
        sources.forEach((item: { title: string; source: string }) => {
          if (!titlesSet.has(item.title)) {
            titlesSet.add(item.title);
            const formattedString =
              '\n' + `[${item.title}](${item.source})` + '\n';
            result += formattedString;
          }
        });
      }

      return { answer: result, query: question, result };
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
