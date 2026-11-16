import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, options?: Record<string, unknown>) => {
      if (!options) return key;
      const values = Object.entries(options)
        .filter(([name]) => name !== 'interpolation')
        .map(([name, value]) => `${name}=${value}`)
        .join(',');
      return `${key}(${values})`;
    },
    i18n: { language: 'en' },
  }),
}));

import { PayerApiError } from '../api/services/payerService';
import TakeOverModal from './TakeOverModal';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

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
  document.body.innerHTML = '';
});

const render = (
  props: Partial<React.ComponentProps<typeof TakeOverModal>> = {},
) => {
  const setModalState = vi.fn();
  const onConfirm = vi.fn(() => Promise.resolve());
  act(() => {
    root.render(
      <TakeOverModal
        kind="schedule"
        name="Weekly lane report"
        payer={{ user_id: 'u2', label: 'Dana' }}
        modalState="ACTIVE"
        setModalState={setModalState}
        onConfirm={onConfirm}
        {...props}
      />,
    );
  });
  return { setModalState, onConfirm };
};

const text = () => document.body.textContent ?? '';
const submit = () =>
  [...document.body.querySelectorAll('button')].find(
    (b) => b.textContent === 'payer.common.takeOver.submit',
  )!;

describe('TakeOverModal', () => {
  it('asks to take over the named item and says who pays from now on', () => {
    render();
    expect(text()).toContain(
      'payer.common.takeOver.title(name=Weekly lane report)',
    );
    expect(text()).toContain('payer.common.takeOver.schedule.youPay');
    expect(text()).toContain(
      'payer.common.takeOver.schedule.youPayDetail(name=Dana)',
    );
    expect(text()).toContain('payer.common.takeOver.limitApplies');
    expect(text()).toContain('payer.common.takeOver.limitDetail');
  });

  it('names nobody when the team itself is the payer', () => {
    render({ payer: { user_id: '__team__t1', label: 'Operations' } });
    expect(text()).toContain('payer.common.takeOver.schedule.youPayUnnamed');
    expect(text()).not.toContain('Operations');
  });

  it('words outside access and shows the caller’s own facts', () => {
    render({
      kind: 'outside_access',
      name: 'Carrier desk',
      agentLimit: 'Carrier desk: no agent limit set.',
      history: 'It ran 4 times in November and used $2.60',
    });
    expect(text()).toContain('payer.common.takeOver.access.youPay');
    expect(text()).toContain(
      'payer.common.takeOver.access.youPayDetail(name=Dana)',
    );
    expect(text()).toContain('Carrier desk: no agent limit set.');
    expect(text()).toContain('It ran 4 times in November and used $2.60');
    expect(text()).not.toContain('payer.common.takeOver.limitDetail');
  });

  it('leaves the old payer out when nobody pays', () => {
    render({ payer: null });
    expect(text()).toContain('payer.common.takeOver.schedule.youPayUnnamed');
  });

  it('confirms and closes on success', async () => {
    const { onConfirm, setModalState } = render();
    await act(async () => submit().click());
    expect(onConfirm).toHaveBeenCalledTimes(1);
    expect(setModalState).toHaveBeenCalledWith('INACTIVE');
  });

  it('stays open with the refusal worded', async () => {
    const { setModalState } = render({
      onConfirm: () =>
        Promise.reject(
          new PayerApiError(429, 'Too many', 'max_schedules', undefined),
        ),
    });
    await act(async () => submit().click());
    expect(setModalState).not.toHaveBeenCalledWith('INACTIVE');
    expect(text()).toContain('payer.common.errors.maxSchedules');
  });
});
