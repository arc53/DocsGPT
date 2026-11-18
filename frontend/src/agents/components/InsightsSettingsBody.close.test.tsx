import { act, useState } from 'react';
import { createRoot, type Root } from 'react-dom/client';

import { DEFAULT_ANALYTICS } from '../analyticsConfig';
import type { AnalyticsConfig } from '../types';

vi.mock('react-redux', () => ({ useDispatch: () => vi.fn() }));

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, opts?: Record<string, unknown>) =>
      opts && typeof opts.name === 'string' ? `${key}(${opts.name})` : key,
  }),
}));

vi.mock('../../api/services/userService', () => ({
  default: { getTopicFolders: vi.fn(() => new Promise(() => undefined)) },
}));

// A dialog that stays in the DOM after it closes, as Radix keeps one through
// its exit animation, so the copy it shows while closing can be read.
vi.mock('@/components/ui/modal', () => ({
  Modal: ({
    open,
    title,
    footer,
    children,
  }: {
    open: boolean;
    title?: React.ReactNode;
    footer?: React.ReactNode;
    children: React.ReactNode;
  }) => (
    <div role="dialog" data-open={open}>
      <h2>{title}</h2>
      {children}
      {footer}
    </div>
  ),
  ModalActions: ({
    submitLabel,
    onSubmit,
    onCancel,
    cancelLabel,
  }: {
    submitLabel?: React.ReactNode;
    onSubmit?: () => void;
    onCancel: () => void;
    cancelLabel: React.ReactNode;
  }) => (
    <>
      <button type="button" onClick={onCancel}>
        {cancelLabel}
      </button>
      <button type="button" onClick={onSubmit}>
        {submitLabel}
      </button>
    </>
  ),
}));

import InsightsSettingsBody from './InsightsSettingsBody';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const K = 'agents.form.analytics';
const REFUND = {
  id: 'a1b2c3d4e5f60718',
  name: 'Refund',
  description: 'Wants money back.',
  overlap: true,
};

function Harness({ initial }: { initial: AnalyticsConfig }) {
  const [value, setValue] = useState(initial);
  return (
    <InsightsSettingsBody
      value={value}
      onChange={setValue}
      agentId="a1"
      maxTopics={3}
      maxOverlapping={20}
      token="token"
    />
  );
}

// FX-4: the add/edit dialog and the remove-topic confirm keep their copy
// while they close, instead of flipping to "Add topic" and `Remove ""?`.
describe('InsightsSettingsBody dialogs while closing', () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(async () => {
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
    await act(async () =>
      root.render(
        <Harness initial={{ ...DEFAULT_ANALYTICS, topics: [REFUND] }} />,
      ),
    );
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
  });

  const button = (text: string, scope: ParentNode = container) =>
    Array.from(scope.querySelectorAll<HTMLButtonElement>('button')).find(
      (el) => el.textContent === text,
    )!;
  const cancelOpenDialog = () =>
    button(
      'cancel',
      container.querySelector('[role="dialog"][data-open="true"]')!,
    ).click();
  const dialogTitles = () =>
    Array.from(container.querySelectorAll('[role="dialog"]')).map((dialog) => [
      dialog.getAttribute('data-open'),
      dialog.querySelector('h2')!.textContent,
    ]);

  const openMenuItem = async (label: string) => {
    const trigger = container.querySelector<HTMLButtonElement>(
      '[aria-haspopup="menu"]',
    )!;
    await act(async () => {
      trigger.dispatchEvent(
        new PointerEvent('pointerdown', { bubbles: true, button: 0 }),
      );
      trigger.click();
    });
    const item = Array.from(
      document.body.querySelectorAll<HTMLElement>('[role="menuitem"]'),
    ).find((el) => el.textContent === label)!;
    await act(async () => item.click());
  };

  it('keeps "Edit topic" on the closing edit dialog', async () => {
    await openMenuItem(`${K}.edit`);
    expect(dialogTitles()).toContainEqual(['true', `${K}.modal.editTopic`]);
    await act(async () => cancelOpenDialog());
    expect(dialogTitles()).toContainEqual(['false', `${K}.modal.editTopic`]);
  });

  it('keeps the topic name on the closing remove confirm', async () => {
    await openMenuItem(`${K}.remove`);
    const title = `${K}.removeTopic.title(Refund)`;
    expect(dialogTitles()).toContainEqual(['true', title]);
    await act(async () => cancelOpenDialog());
    expect(dialogTitles()).toContainEqual(['false', title]);
  });
});
