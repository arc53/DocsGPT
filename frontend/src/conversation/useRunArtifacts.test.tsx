import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

vi.mock('react-redux', () => ({ useSelector: () => 'tok' }));
const listMock = vi.fn();
vi.mock('../api/services/userService', () => ({
  default: {
    listWorkflowRunArtifacts: (...args: unknown[]) => listMock(...args),
  },
}));

import { useRunArtifacts } from './useRunArtifacts';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const ok = (artifacts: unknown[]) => ({
  ok: true,
  json: async () => ({ success: true, artifacts }),
});

describe('useRunArtifacts', () => {
  let container: HTMLDivElement;
  let root: Root;
  let latest: ReturnType<typeof useRunArtifacts>;

  function Probe({ id, live }: { id?: string; live?: boolean }) {
    latest = useRunArtifacts(id, live);
    return null;
  }

  beforeEach(() => {
    listMock.mockReset();
    container = document.createElement('div');
    root = createRoot(container);
  });
  afterEach(async () => {
    await act(async () => root.unmount());
  });

  it('fetches nothing without a run', async () => {
    await act(async () => root.render(<Probe />));
    expect(listMock).not.toHaveBeenCalled();
    expect(latest.items).toEqual([]);
  });

  it('lists the run’s files as cards in the order produced', async () => {
    // The endpoint answers newest first.
    listMock.mockResolvedValue(
      ok([
        {
          id: 'b',
          title: 'QBR (PDF)',
          current_version: 1,
          filename: 'qbr.pdf',
        },
        { id: 'a', title: 'QBR', current_version: 1, filename: 'qbr.html' },
      ]),
    );
    await act(async () => root.render(<Probe id="run-1" />));
    expect(listMock).toHaveBeenCalledWith('run-1', 'tok');
    expect(latest.items.map((i) => [i.id, i.kind])).toEqual([
      ['a', 'page'],
      ['b', 'pdf'],
    ]);
  });

  // A run's last files are saved as it ends.
  it('refetches when the run stops streaming', async () => {
    listMock.mockResolvedValue(ok([]));
    await act(async () => root.render(<Probe id="run-1" live />));
    await act(async () => root.render(<Probe id="run-1" live={false} />));
    expect(listMock).toHaveBeenCalledTimes(2);
  });

  it('reports a failed list and retries it', async () => {
    listMock.mockResolvedValueOnce({ ok: false });
    await act(async () => root.render(<Probe id="run-1" />));
    expect(latest.failed).toBe(true);
    listMock.mockResolvedValueOnce(ok([]));
    await act(async () => latest.retry());
    expect(latest.failed).toBe(false);
    expect(listMock).toHaveBeenCalledTimes(2);
  });
});
