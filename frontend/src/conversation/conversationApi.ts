import { Answer } from './conversationModels';

export function fetchAnswerApi(
  question: string,
  apiKey: string,
): Promise<Answer> {
  // a mock answer generator, this is going to be replaced with real http call
  return new Promise((resolve, reject) => {
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
      const randNum = getRandomInt(0, 10);
      randNum < 5
        ? reject()
        : resolve({ answer: result, query: question, result });
    }, 3000);
  });
}

function getRandomInt(min: number, max: number) {
  min = Math.ceil(min);
  max = Math.floor(max);
  return Math.floor(Math.random() * (max - min) + min); // The maximum is exclusive and the minimum is inclusive
}
