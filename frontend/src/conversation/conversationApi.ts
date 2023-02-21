import { Answer } from './conversationModels';

export function fetchAnswerApi(
  question: string,
  apiKey: string,
): Promise<Answer> {
  // a mock answer generator, this is going to be replaced with real http call
  return new Promise((resolve) => {
    setTimeout(() => {
      let result = '';
      const characters =
        'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789';
      const charactersLength = characters.length;
      let counter = 0;
      while (counter < 5) {
        result += characters.charAt(
          Math.floor(Math.random() * charactersLength),
        );
        counter += 1;
      }
      resolve({ answer: result, query: question, result });
    }, 3000);
  });
}
