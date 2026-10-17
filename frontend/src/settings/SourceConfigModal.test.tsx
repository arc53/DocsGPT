import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

const dispatch = vi.hoisted(() => vi.fn());
vi.mock('react-redux', () => ({
  useSelector: () => null,
  useDispatch: () => dispatch,
}));

const updateSourceConfig = vi.hoisted(() => vi.fn());
vi.mock('../api/services/userService', () => ({
  default: { updateSourceConfig },
}));

import type { Doc } from '../models/misc';
import type { DecisionFeatures } from './components/RetrievalOptions';
import SourceConfigModal from './SourceConfigModal';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const doc = (fields: Partial<Doc>): Doc => ({
  id: 'src-1',
  name: 'Contracts',
  date: '',
  model: '',
  ...fields,
});

describe('SourceConfigModal access', () => {
  let container: HTMLDivElement;
  let root: Root;

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

  const render = async (document: Doc, decision?: DecisionFeatures) => {
    await act(async () => {
      root.render(
        <SourceConfigModal
          modalState="ACTIVE"
          setModalState={vi.fn()}
          document={document}
          onReingest={vi.fn()}
          onEnableGraphRAG={vi.fn()}
          decision={decision}
        />,
      );
    });
  };

  const readOnlyNotice = () =>
    document.body.textContent?.includes('common.viewOnlyNotice');

  const buttonLabels = () =>
    Array.from(document.body.querySelectorAll('button')).map(
      (b) => b.textContent,
    );

  it('a viewer with view_config only sees the read-only notice', async () => {
    await render(
      doc({
        access: 'viewer',
        ownership: 'team',
        team_access: 'viewer',
        allowed_actions: ['use', 'view_config'],
      }),
    );
    expect(readOnlyNotice()).toBe(true);
    const note = document.body.querySelector('[data-slot="alert"]');
    expect(note?.getAttribute('role')).toBe('note');
    // View-only: no Save, and Cancel becomes a lone Close.
    expect(buttonLabels()).not.toContain('settings.sources.configModal.save');
    expect(buttonLabels()).not.toContain('cancel');
    expect(buttonLabels()).toContain('common.close');
  });

  it('an editor can edit (no read-only notice)', async () => {
    await render(
      doc({
        access: 'editor',
        ownership: 'team',
        team_access: 'editor',
        allowed_actions: ['edit', 'use', 'view_config'],
      }),
    );
    expect(readOnlyNotice()).toBe(false);
    expect(buttonLabels()).toContain('settings.sources.configModal.save');
    expect(buttonLabels()).toContain('cancel');
  });

  it('follows allowed_actions over the legacy team_access', async () => {
    await render(
      doc({
        access: 'viewer',
        ownership: 'team',
        team_access: 'editor',
        allowed_actions: ['use', 'view_config'],
      }),
    );
    expect(readOnlyNotice()).toBe(true);
  });

  it('an owned source without access fields is editable', async () => {
    await render(doc({}));
    expect(readOnlyNotice()).toBe(false);
  });

  it('saves a strictness picked in the Relevance section', async () => {
    updateSourceConfig.mockResolvedValue({
      ok: true,
      json: async () => ({ success: true, requires_reingest: false }),
    });
    await render(
      doc({
        config: {
          retrieval: {
            reranker: { type: 'decision', min_relevance: 0.3 },
          },
        },
      }),
      { relevance: true, injection: false },
    );
    const strict = Array.from(
      document.body.querySelectorAll<HTMLButtonElement>(
        '#retrieval-relevance-strictness [data-slot="toggle-group-item"]',
      ),
    ).find(
      (b) =>
        b.textContent ===
        'settings.sources.retrievalOptions.relevance.presets.strict',
    )!;
    await act(async () => strict.click());
    const save = Array.from(document.body.querySelectorAll('button')).find(
      (b) => b.textContent === 'settings.sources.configModal.save',
    )!;
    await act(async () => save.click());
    const config = updateSourceConfig.mock.calls[0][1];
    expect(config.retrieval.reranker).toEqual({
      type: 'decision',
      min_relevance: 0.5,
      candidate_k: null,
    });
    expect(config.retrieval.prescreen).toBe(null);
  });
});

describe('SourceConfigModal prompt-injection scan', () => {
  let container: HTMLDivElement;
  let root: Root;
  const setModalState = vi.fn();

  beforeEach(() => {
    updateSourceConfig.mockReset();
    dispatch.mockReset();
    setModalState.mockReset();
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
    document.body.innerHTML = '';
  });

  const owned = doc({
    access: 'owner',
    allowed_actions: ['use', 'view_config', 'edit'],
    config: { guardrails: { injection_scan: false } },
  });

  const render = async (injection: boolean) => {
    await act(async () => {
      root.render(
        <SourceConfigModal
          modalState="ACTIVE"
          setModalState={setModalState}
          document={owned}
          onReingest={vi.fn()}
          onEnableGraphRAG={vi.fn()}
          decision={{ relevance: false, injection }}
        />,
      );
    });
  };

  const scan = () =>
    document.body.querySelector<HTMLButtonElement>(
      '[data-testid="source-injection-scan"]',
    );
  const save = () =>
    Array.from(document.body.querySelectorAll('button')).find(
      (b) => b.textContent === 'settings.sources.configModal.save',
    )!;

  it('is not offered while the operator has the model off', async () => {
    await render(false);
    expect(scan()).toBeNull();
  });

  it('saves the scan and says the indexed chunks are being scanned', async () => {
    updateSourceConfig.mockResolvedValue({
      ok: true,
      json: async () => ({
        success: true,
        requires_reingest: false,
        injection_backfill: 'queued',
      }),
    });
    await render(true);
    expect(scan()?.getAttribute('aria-checked')).toBe('false');
    expect(document.body.textContent).toContain(
      'settings.sources.configModal.injectionScan',
    );
    expect(save().disabled).toBe(true);
    await act(async () => scan()!.click());
    expect(save().disabled).toBe(false);
    await act(async () => save().click());
    const config = updateSourceConfig.mock.calls[0][1];
    expect(config.guardrails).toEqual({ injection_scan: true });
    expect(dispatch).toHaveBeenCalledWith(
      expect.objectContaining({
        payload: {
          variant: 'success',
          message: 'settings.sources.configModal.backfillQueued',
        },
      }),
    );
    expect(setModalState).toHaveBeenCalledWith('INACTIVE');
  });

  it('says chunks are scanned as they are retrieved where the store cannot list them', async () => {
    updateSourceConfig.mockResolvedValue({
      ok: true,
      json: async () => ({
        success: true,
        requires_reingest: false,
        injection_backfill: 'lazy',
      }),
    });
    await render(true);
    await act(async () => scan()!.click());
    await act(async () => save().click());
    expect(dispatch.mock.calls[0][0].payload.message).toBe(
      'settings.sources.configModal.backfillLazy',
    );
  });
});
