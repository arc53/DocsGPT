import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

vi.mock('react-redux', () => ({
  useSelector: () => 'token',
  useDispatch: () => vi.fn(),
}));
vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

const getModels = vi.fn();
vi.mock('../api/services/userService', () => ({
  default: {
    getPreferences: async () => ({
      ok: true,
      json: async () => ({ task_model_id: null, instance_task_model_id: '' }),
    }),
    updatePreferences: vi.fn(),
  },
}));
vi.mock('../api/services/modelService', async (importOriginal) => {
  const actual =
    await importOriginal<typeof import('../api/services/modelService')>();
  return {
    default: {
      ...actual.default,
      getModels: (...args: unknown[]) => {
        getModels(...args);
        return Promise.resolve({
          ok: true,
          json: async () => ({ models: [] }),
        });
      },
    },
  };
});

import { setRequestWorkspace } from '../workspace/requestWorkspace';
import TaskModelSection from './TaskModelSection';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

describe('TaskModelSection in a team', () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
    setRequestWorkspace('personal', 0);
  });

  it("lists the person's own models, whatever workspace the app is in", async () => {
    // The task model is the person's (their custom models included), not
    // the team's.
    setRequestWorkspace('t1', 1);
    await act(async () => root.render(<TaskModelSection />));
    expect(getModels).toHaveBeenCalledWith('token', {
      'X-DocsGPT-Workspace': 'personal',
    });
  });
});
