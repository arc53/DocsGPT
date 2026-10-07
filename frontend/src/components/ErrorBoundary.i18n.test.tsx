import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

import i18n from '../locale/i18n';
import ErrorBoundary from './ErrorBoundary';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

function Bomb(): never {
  throw new Error('render exploded');
}

// The error screen is what a user sees when the UI fails them, so it must be
// in their language too, not the English fallback.
describe('ErrorBoundary fallback in each locale', () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
    vi.spyOn(console, 'error').mockImplementation(() => {});
  });
  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
    vi.restoreAllMocks();
    await i18n.changeLanguage('en');
  });

  it.each([
    ['es', 'Algo salió mal al mostrar este contenido.', 'Reintentar'],
    [
      'de',
      'Beim Anzeigen dieses Inhalts ist ein Fehler aufgetreten.',
      'Erneut versuchen',
    ],
    ['jp', 'このコンテンツの表示中に問題が発生しました。', '再試行'],
    ['ru', 'Не удалось отобразить этот контент.', 'Повторить'],
    ['zh', '显示此内容时出错。', '重试'],
    ['zhTW', '顯示此內容時發生錯誤。', '重試'],
  ])('renders the %s message and button', async (lng, message, button) => {
    await i18n.changeLanguage(lng);
    await act(async () => {
      root.render(
        <ErrorBoundary>
          <Bomb />
        </ErrorBoundary>,
      );
    });
    const alert = container.querySelector('[role="alert"]');
    expect(alert?.querySelector('p')?.textContent).toBe(message);
    expect(alert?.querySelector('button')?.textContent).toBe(button);
  });
});
