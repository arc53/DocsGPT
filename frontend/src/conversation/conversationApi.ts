import { Answer } from './conversationModels';

export function fetchAnswerApi(
  question: string,
  apiKey: string,
  selectedDocs: string,
): Promise<Answer> {
  // a mock answer generator, this is going to be replaced with real http call
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
        active_docs: selectedDocs,
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
