import { configureStore } from '@reduxjs/toolkit';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { Provider } from 'react-redux';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

const listed = vi.hoisted(() => ({ models: [] as unknown[] }));
vi.mock('./api/services/modelService', () => ({
  default: {
    getModels: vi.fn(async () => ({
      ok: true,
      json: async () => ({ models: listed.models, default_model_id: 'gpt' }),
    })),
    transformModels: (models: unknown[]) => models,
  },
}));
// A plain stand-in for the Radix select: every group and item renders.
vi.mock('./components/ui/select', () => {
  const Pass = ({ children }: { children?: React.ReactNode }) => (
    <div>{children}</div>
  );
  return {
    Select: Pass,
    SelectTrigger: Pass,
    SelectValue: () => null,
    SelectContent: Pass,
    SelectGroup: ({ children }: { children: React.ReactNode }) => (
      <div data-testid="group">{children}</div>
    ),
    SelectLabel: ({ children }: { children: React.ReactNode }) => (
      <span data-testid="group-label">{children}</span>
    ),
    SelectItem: ({ children }: { children: React.ReactNode }) => (
      <span data-testid="item">{children}</span>
    ),
  };
});

import { HeroModelSelect } from './Hero';
import preferenceReducer from './preferences/preferenceSlice';
import workspaceReducer from './workspace/workspaceSlice';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const builtin = { id: 'gpt', display_name: 'GPT', source: 'builtin' };
const teamModel = { id: 'ops', display_name: 'Ops model', source: 'team' };

describe('HeroModelSelect in a team', () => {
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
  });

  it("groups the team's models under Team models, apart from the catalog", async () => {
    listed.models = [builtin, teamModel];
    const store = configureStore({
      reducer: { preference: preferenceReducer, workspace: workspaceReducer },
    });
    await act(async () => {
      root.render(
        <Provider store={store}>
          <HeroModelSelect />
        </Provider>,
      );
    });
    const labels = Array.from(
      container.querySelectorAll('[data-testid="group-label"]'),
    ).map((label) => label.textContent);
    expect(labels).toEqual([
      'settings.customModels.modelsGroup.builtin',
      'settings.customModels.team.pickerGroup',
    ]);
    const groups = Array.from(
      container.querySelectorAll('[data-testid="group"]'),
    ).map((group) => group.textContent);
    expect(groups[0]).not.toContain('Ops model');
    expect(groups[1]).toContain('Ops model');
  });
});
