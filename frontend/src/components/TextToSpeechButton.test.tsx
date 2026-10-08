import { configureStore } from '@reduxjs/toolkit';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { Provider } from 'react-redux';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

const { textToSpeech } = vi.hoisted(() => ({ textToSpeech: vi.fn() }));
vi.mock('../api/services/userService', () => ({
  default: { textToSpeech },
}));

import SpeakButton from './TextToSpeechButton';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

describe('SpeakButton', () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
    textToSpeech.mockResolvedValue({
      json: async () => ({ success: false }),
    });
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
    textToSpeech.mockReset();
  });

  it("sends the signed-in user's token", async () => {
    const store = configureStore({
      reducer: { preference: () => ({ token: 'user-token' }) },
    });
    await act(async () => {
      root.render(
        <Provider store={store}>
          <SpeakButton text="Hello there" />
        </Provider>,
      );
    });

    await act(async () => {
      container.querySelector('button')?.click();
    });

    expect(textToSpeech).toHaveBeenCalledWith(
      'Hello there',
      'user-token',
      expect.any(AbortSignal),
    );
  });
});
