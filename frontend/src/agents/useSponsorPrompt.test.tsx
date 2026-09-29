import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

vi.mock('../hooks', () => ({
  useMediaQuery: () => ({ isMobile: false, isDesktop: true }),
}));

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string) => key,
    i18n: { language: 'en' },
  }),
}));

import { saveWithSponsorConsent } from './sponsorConsent';
import { useSponsorPrompt } from './useSponsorPrompt';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const json = (status: number, body: unknown) =>
  new Response(JSON.stringify(body), { status });

const refused = () =>
  json(409, {
    code: 'sponsor_confirmation_required',
    resources: [{ key: 'tool:t1', type: 'tool', id: 't1', name: 'Jira' }],
    audience: { teams: ['Ops'], api_key: false, public_link: false },
  });

/** A workflow save as the builder does it: one call, one outcome. */
function Harness({
  send,
  onOutcome,
}: {
  send: (keys: string[]) => Promise<Response>;
  onOutcome: (outcome: string) => void;
}) {
  const prompt = useSponsorPrompt();
  const save = async () => {
    const response = await saveWithSponsorConsent(send, prompt.ask);
    onOutcome(!response ? 'cancelled' : response.ok ? 'saved' : 'failed');
  };
  return (
    <>
      <button type="button" data-testid="save" onClick={() => void save()} />
      {prompt.modal}
    </>
  );
}

describe('useSponsorPrompt with a workflow save', () => {
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

  const start = async (send: (keys: string[]) => Promise<Response>) => {
    const onOutcome = vi.fn();
    await act(async () => {
      root.render(<Harness send={send} onOutcome={onOutcome} />);
    });
    await act(async () =>
      container
        .querySelector<HTMLButtonElement>('[data-testid="save"]')!
        .click(),
    );
    return onOutcome;
  };

  const dialogButton = (label: string) =>
    Array.from(document.querySelectorAll('button')).find(
      (b) => b.textContent === label,
    ) as HTMLButtonElement;

  it('resolves the original save with the confirmed retry', async () => {
    const send = vi
      .fn<(keys: string[]) => Promise<Response>>()
      .mockResolvedValueOnce(refused())
      .mockResolvedValueOnce(json(200, { success: true }));
    const onOutcome = await start(send);
    // Waiting on the caller: the save hasn't ended yet.
    expect(onOutcome).not.toHaveBeenCalled();
    expect(document.body.textContent).toContain('Jira');
    await act(async () =>
      dialogButton('agents.form.sponsorConfirm.confirm').click(),
    );
    expect(send.mock.calls.map(([keys]) => keys)).toEqual([[], ['tool:t1']]);
    expect(onOutcome).toHaveBeenCalledWith('saved');
    expect(document.querySelector('[data-slot="modal-content"]')).toBeNull();
  });

  it('ends as cancelled, not failed, when the caller declines', async () => {
    const send = vi.fn(async () => refused());
    const onOutcome = await start(send);
    await act(async () => dialogButton('cancel').click());
    expect(onOutcome).toHaveBeenCalledWith('cancelled');
    expect(send).toHaveBeenCalledTimes(1);
  });
});
