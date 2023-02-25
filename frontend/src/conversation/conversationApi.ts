import { Answer } from './conversationModels';
import { Doc } from '../preferences/preferenceApi';

export function fetchAnswerApi(
  question: string,
  apiKey: string,
  selectedDocs: Doc,
): Promise<Answer> {
  let namePath = selectedDocs.name;
  if (selectedDocs.language === namePath) {
    namePath = '.project';
  }

  const docPath =
    selectedDocs.language +
    '/' +
    namePath +
    '/' +
    selectedDocs.version +
    '/' +
    selectedDocs.model;
  return new Promise((resolve, reject) => {
    const activeDocs = 'default';
    fetch('https://docsgpt.arc53.com/api/answer', {
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
      .then((response) => response.json())
      .then((data) => {
        const result = data.answer;
        resolve({ answer: result, query: question, result });
      })
      .catch((error) => {
        reject();
      });
  });
}

function getRandomInt(min: number, max: number) {
  min = Math.ceil(min);
  max = Math.floor(max);
  return Math.floor(Math.random() * (max - min) + min); // The maximum is exclusive and the minimum is inclusive
}
