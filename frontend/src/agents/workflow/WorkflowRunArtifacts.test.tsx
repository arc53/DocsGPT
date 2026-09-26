import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

vi.mock('react-redux', () => ({
  useSelector: () => null,
}));

const listMock = vi.fn();
const detailMock = vi.fn();
vi.mock('../../api/services/userService', () => ({
  default: {
    listWorkflowRunArtifacts: (...args: unknown[]) => listMock(...args),
    getDocumentArtifact: (...args: unknown[]) => detailMock(...args),
  },
}));

vi.mock('../../components/DocumentArtifactView', () => ({
  default: () => <div data-testid="artifact-view" />,
}));

import WorkflowRunArtifacts from './WorkflowRunArtifacts';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const failed = { ok: false, status: 500, json: async () => ({}) };

describe('WorkflowRunArtifacts', () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    listMock.mockReset();
    detailMock.mockReset();
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
  });

  const render = async () => {
    await act(async () => {
      root.render(<WorkflowRunArtifacts workflowRunId="run-1" />);
    });
  };

  const buttonByText = (text: string) =>
    Array.from(container.querySelectorAll('button')).find((b) =>
      b.textContent?.includes(text),
    );

  it('shows a failed list load as an alert with Retry that refetches', async () => {
    listMock.mockResolvedValue(failed);
    await render();

    const alert = container.querySelector('[role="alert"]');
    expect(alert?.textContent).toContain(
      'agents.workflow.artifacts.loadListFailed',
    );
    expect(listMock).toHaveBeenCalledTimes(1);

    await act(async () => buttonByText('retry')!.click());
    expect(listMock).toHaveBeenCalledTimes(2);
  });

  it('retries a failed artifact preview', async () => {
    listMock.mockResolvedValue({
      ok: true,
      json: async () => ({
        success: true,
        artifacts: [
          { id: 'a1', kind: 'pdf', title: 'Report', current_version: 1 },
        ],
      }),
    });
    detailMock.mockResolvedValue(failed);
    await render();

    await act(async () => buttonByText('Report')!.click());
    expect(container.querySelector('[role="alert"]')?.textContent).toContain(
      'agents.workflow.artifacts.loadFailed',
    );
    expect(detailMock).toHaveBeenCalledTimes(1);

    await act(async () => buttonByText('retry')!.click());
    expect(detailMock).toHaveBeenCalledTimes(2);
  });
});
