import { act, useState } from 'react';
import { createRoot, type Root } from 'react-dom/client';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

import { SettingRow } from '@/components/ui/setting-row';

import { DraftedBadge, DraftedField } from './DraftedBadge';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

function Field() {
  const [drafted, setDrafted] = useState(true);
  return (
    <DraftedField
      drafted={drafted}
      onUndo={() => setDrafted(false)}
      fieldLabel="Name"
    >
      <input aria-label="Name" />
    </DraftedField>
  );
}

function Row() {
  const [drafted, setDrafted] = useState(true);
  return (
    <SettingRow
      label="Limit"
      htmlFor="limit"
      drafted={drafted}
      onUndo={() => setDrafted(false)}
    >
      <input id="limit" />
    </SettingRow>
  );
}

function Heading() {
  const [drafted, setDrafted] = useState(true);
  return (
    <div>
      <h2>
        <button type="button">Analytics</button>
      </h2>
      {drafted && (
        <DraftedBadge onUndo={() => setDrafted(false)} fieldLabel="A" />
      )}
    </div>
  );
}

describe('DraftedBadge undo', () => {
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
  });

  const undo = async () => {
    const button = container.querySelector<HTMLButtonElement>(
      'button[aria-label="drafter.undoField"]',
    )!;
    button.focus();
    await act(async () => button.click());
    expect(
      container.querySelector('button[aria-label="drafter.undoField"]'),
    ).toBeNull();
  };

  it('keeps focus in the field it restored', async () => {
    await act(async () => root.render(<Field />));
    await undo();
    expect(document.activeElement).toBe(container.querySelector('input'));
  });

  it('keeps focus on a setting row’s control', async () => {
    await act(async () => root.render(<Row />));
    await undo();
    expect(document.activeElement).toBe(container.querySelector('#limit'));
  });

  it('falls back to the control beside a lone badge', async () => {
    await act(async () => root.render(<Heading />));
    await undo();
    expect(document.activeElement).toBe(container.querySelector('h2 button'));
  });
});
