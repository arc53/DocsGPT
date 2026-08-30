interface HistoryItem {
  prompt: string;
  response?: string;
}

interface FetchAnswerStreamingProps {
  question?: string;
  apiKey?: string;
  selectedDocs?: string;
  history?: HistoryItem[];
  conversationId?: string | null;
  apiHost?: string;
  onEvent?: (event: MessageEvent) => void;
  signal?: AbortSignal;
}

export interface FeedbackPayload {
  question?: string;
  answer?: string;
  feedback: string | null;
  apikey?: string;
  conversation_id: string;
  question_index: number;
}

export function fetchAnswerStreaming({
  question = '',
  apiKey = '',
  history = [],
  conversationId = null,
  apiHost = '',
  onEvent = () => {
    console.log('Event triggered, but no handler provided.');
  },
  signal,
}: FetchAnswerStreamingProps): Promise<void> {
  return new Promise<void>((resolve, reject) => {
    const body = {
      question: question,
      history: JSON.stringify(
        history
          .filter((item) => item.prompt && item.response)
          .map(({ prompt, response }) => ({ prompt, response })),
      ),
      conversation_id: conversationId,
      api_key: apiKey,
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
    
        let buffer = '';

        const emit = (rawLine: string) => {
          const line = rawLine.trim();
          if (line === '') return;
          if (!line.startsWith('data:')) return;

          const payload = line.substring(5).trim();
          if (payload === '' || payload === '[DONE]') return;

          onEvent(new MessageEvent('message', { data: payload }));
        };

        const processStream = ({
          done,
          value,
        }: ReadableStreamReadResult<Uint8Array>) => {
          if (done) {
            if (buffer.trim() !== '') emit(buffer);
            buffer = '';
            resolve();
            return;
          }
          buffer += decoder.decode(value, { stream: true });

          const lines = buffer.split('\n');
          buffer = lines.pop() ?? '';
          for (const line of lines) emit(line);

          reader.read().then(processStream).catch(onReadError);
        };

        const onReadError = (error: unknown) => {
          if (signal?.aborted || (error as Error)?.name === 'AbortError') {
            resolve();
            return;
          }
          reject(error);
        };

        reader.read().then(processStream).catch(onReadError);
      })
      .catch((error) => {
        if (signal?.aborted || (error as Error)?.name === 'AbortError') {
          resolve();
          return;
        }
        console.error('Connection failed:', error);
        reject(error);
      });
  });
}

export const sendFeedback = (
  payload: FeedbackPayload,
  apiHost: string,
): Promise<Response> => {
  return fetch(`${apiHost}/api/feedback`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      question: payload.question,
      answer: payload.answer,
      feedback: payload.feedback,
      api_key: payload.apikey,
      conversation_id: payload.conversation_id,
      question_index: payload.question_index,
    }),
  });
};
