import i18n from 'i18next';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { I18nextProvider, initReactI18next } from 'react-i18next';

vi.mock('../hooks', () => ({
  useMediaQuery: () => ({ isMobile: false, isDesktop: true }),
}));

vi.mock('react-redux', () => ({
  useSelector: () => null,
  useDispatch: () => vi.fn(),
}));

vi.mock('../api/services/userService', () => ({
  default: { updateSourceConfig: vi.fn(), testSourceRetrieval: vi.fn() },
}));

import en from '../locale/en.json';
import type { Doc } from '../models/misc';
import SourceConfigModal from './SourceConfigModal';
import TestRetrievalModal from './TestRetrievalModal';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

// A real i18next instance: it HTML-escapes interpolated values unless told not
// to, and React escapes them again, so "&" would render as "&amp;".
const testI18n = i18n.createInstance();

const doc: Doc = {
  id: 'src-1',
  name: 'Policies & Contracts Library',
  date: '',
  model: '',
};

describe('source modal subtitles', () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeAll(async () => {
    await testI18n.use(initReactI18next).init({
      lng: 'en',
      fallbackLng: 'en',
      resources: { en: { translation: en } },
    });
  });

  beforeEach(() => {
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
    document.body.innerHTML = '';
  });

  it('shows the source name unescaped in Source settings', async () => {
    await act(async () => {
      root.render(
        <I18nextProvider i18n={testI18n}>
          <SourceConfigModal
            modalState="ACTIVE"
            setModalState={vi.fn()}
            document={doc}
            onReingest={vi.fn()}
            onEnableGraphRAG={vi.fn()}
          />
        </I18nextProvider>,
      );
    });
    expect(document.body.textContent).toContain(
      'Configure how "Policies & Contracts Library" is chunked',
    );
    expect(document.body.textContent).not.toContain('&amp;');
  });

  it('shows the source name unescaped in Test retrieval', async () => {
    await act(async () => {
      root.render(
        <I18nextProvider i18n={testI18n}>
          <TestRetrievalModal
            modalState="ACTIVE"
            setModalState={() => undefined}
            document={doc}
          />
        </I18nextProvider>,
      );
    });
    expect(document.body.textContent).toContain(
      'retrieves from "Policies & Contracts Library"',
    );
    expect(document.body.textContent).not.toContain('&amp;');
  });
});
