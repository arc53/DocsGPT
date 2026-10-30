import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

vi.mock('react-redux', () => ({ useSelector: () => 'tok' }));
vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, opts?: Record<string, unknown>) =>
      key === 'agents.workflow.artifacts.untitled'
        ? `Artifact ${opts?.id}`
        : key,
  }),
}));
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

  // An unsaved draft's preview has a run id but no saved run: no files.
  it('reads a 403 as no files, not a failure', async () => {
    listMock.mockResolvedValue({ ok: false, status: 403 });
    await act(async () => root.render(<Probe id="run-1" />));
    expect(latest.failed).toBe(false);
    expect(latest.items).toEqual([]);
  });

  // A re-asked answer gets a new run; the old run's files are not its own.
  it('drops the previous run’s files as soon as the run changes', async () => {
    listMock.mockResolvedValueOnce(
      ok([{ id: 'old', title: 'Old', current_version: 1, filename: 'a.pdf' }]),
    );
    await act(async () => root.render(<Probe id="run-1" />));
    expect(latest.items.map((i) => i.id)).toEqual(['old']);

    let resolve: (value: unknown) => void = () => {};
    listMock.mockReturnValueOnce(new Promise((r) => (resolve = r)));
    await act(async () => root.render(<Probe id="run-2" />));
    expect(latest.items).toEqual([]);

    await act(async () => resolve({ ok: false, status: 500 }));
    expect(latest.failed).toBe(true);
    expect(latest.items).toEqual([]);
  });

  it('keeps the run’s files while it refetches the same run', async () => {
    listMock.mockResolvedValueOnce(
      ok([{ id: 'a', title: 'A', current_version: 1, filename: 'a.pdf' }]),
    );
    await act(async () => root.render(<Probe id="run-1" live />));
    listMock.mockReturnValueOnce(new Promise(() => {}));
    await act(async () => root.render(<Probe id="run-1" live={false} />));
    expect(latest.items.map((i) => i.id)).toEqual(['a']);
  });

  it('names a file with no title or filename by its translated fallback', async () => {
    listMock.mockResolvedValue(
      ok([
        {
          id: 'abcdef123456',
          title: null,
          current_version: null,
          filename: null,
        },
      ]),
    );
    await act(async () => root.render(<Probe id="run-1" />));
    expect(latest.items[0].title).toBe('Artifact abcdef12');
  });
});
