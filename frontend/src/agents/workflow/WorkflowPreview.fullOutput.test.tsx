import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

vi.mock('react-redux', () => ({
  useSelector: () => 'session-token',
  useDispatch: () => vi.fn(),
}));

const getWorkflowRunStep = vi.fn();
vi.mock('../../api/services/userService', () => ({
  default: {
    getWorkflowRunStep: (...args: unknown[]) => getWorkflowRunStep(...args),
  },
}));

import { ExecutionDetails } from './WorkflowPreview';
import type { WorkflowNode } from '../types/workflow';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const nodes = [
  {
    id: 'n1',
    type: 'code',
    title: 'Read files',
    position: { x: 0, y: 0 },
    data: {},
  },
] as unknown as WorkflowNode[];

const summarized = {
  nodeId: 'n1',
  nodeType: 'code',
  nodeTitle: 'Read files',
  status: 'completed',
  stepIndex: 1,
  summarized: true,
  outputPreview: 'First lines of a long report',
  outputTruncated: true,
  stateKeysChanged: ['report', 'pages'],
};

const response = (status: number, body: unknown) =>
  ({ ok: status < 400, status, json: async () => body }) as Response;

describe('ExecutionDetails full output on demand', () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    getWorkflowRunStep.mockReset();
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
  });

  const render = async (step: object, workflowRunId?: string) => {
    await act(async () => {
      root.render(
        <ExecutionDetails
          steps={[step] as never}
          nodes={nodes}
          isOpen
          onToggle={() => undefined}
          workflowRunId={workflowRunId}
        />,
      );
    });
  };

  const showFull = () =>
    Array.from(container.querySelectorAll('button')).find(
      (b) => b.textContent === 'agents.workflow.preview.showFullOutput',
    );

  it('shows the preview and the changed keys of a summarized step', async () => {
    await render(summarized, 'run-1');
    expect(container.textContent).toContain('First lines of a long report…');
    expect(container.textContent).toContain('report');
    expect(container.textContent).toContain('pages');
    expect(showFull()).toBeDefined();
  });

  it('loads the full output and state when asked', async () => {
    getWorkflowRunStep.mockResolvedValue(
      response(200, {
        success: true,
        step: { output: 'The whole report', state_delta: { pages: 12 } },
      }),
    );
    await render(summarized, 'run-1');

    await act(async () => showFull()!.click());

    expect(getWorkflowRunStep).toHaveBeenCalledWith(
      'run-1',
      1,
      'session-token',
    );
    expect(container.textContent).toContain('The whole report');
    expect(container.textContent).toContain('12');
    expect(showFull()).toBeUndefined();
  });

  it('says when the run has not saved the step yet', async () => {
    getWorkflowRunStep.mockResolvedValue(
      response(409, { success: false, code: 'step_not_saved_yet' }),
    );
    await render(summarized, 'run-1');

    await act(async () => showFull()!.click());

    expect(container.textContent).toContain(
      'agents.workflow.preview.fullOutputPending',
    );
  });

  it('says when the full output could not be loaded', async () => {
    getWorkflowRunStep.mockRejectedValue(new Error('offline'));
    await render(summarized, 'run-1');

    await act(async () => showFull()!.click());

    expect(container.textContent).toContain(
      'agents.workflow.preview.fullOutputFailed',
    );
  });

  it('marks a step that streams its status only', async () => {
    await render(
      {
        ...summarized,
        summarized: undefined,
        outputPreview: undefined,
        outputOmitted: true,
      },
      'run-1',
    );
    expect(container.textContent).toContain(
      'agents.workflow.preview.outputNotStreamed',
    );
    expect(showFull()).toBeDefined();
  });

  it('offers nothing to load without a saved run', async () => {
    await render(summarized);
    expect(showFull()).toBeUndefined();
  });

  it('says to save the workflow when the run is an unsaved draft', async () => {
    await act(async () => {
      root.render(
        <ExecutionDetails
          steps={[summarized] as never}
          nodes={nodes}
          isOpen
          onToggle={() => undefined}
          workflowRunId="draft-run"
          runSaved={false}
        />,
      );
    });
    expect(showFull()).toBeUndefined();
    expect(container.textContent).toContain(
      'agents.workflow.preview.fullOutputUnsaved',
    );
  });

  it('leaves a whole step as it was', async () => {
    await render(
      { nodeId: 'n1', nodeType: 'code', status: 'completed', output: 'done' },
      'run-1',
    );
    expect(container.textContent).toContain('done');
    expect(showFull()).toBeUndefined();
  });
});
