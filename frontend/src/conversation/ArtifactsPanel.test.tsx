import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));
vi.mock('react-redux', () => ({
  useSelector: () => null,
  useDispatch: () => vi.fn(),
}));
vi.mock('../hooks', () => ({
  useDarkTheme: () => [false],
  useMediaQuery: () => ({ isMobile: false, isDesktop: true }),
}));
vi.mock('../components/ArtifactPanel', () => ({
  default: (props: {
    artifactId: string;
    version?: number;
    onBack?: () => void;
  }) => (
    <div
      data-testid="artifact-panel"
      data-id={props.artifactId}
      data-version={props.version}
    >
      <button type="button" onClick={props.onBack}>
        back
      </button>
    </div>
  ),
}));

import { SidePanel } from '../components/ui/side-panel';
import type { ArtifactCardItem } from './artifactCards';
import ArtifactsPanel from './ArtifactsPanel';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const item = (
  id: string,
  kind: ArtifactCardItem['kind'],
): ArtifactCardItem => ({
  id,
  title: `title-${id}`,
  kind,
  version: 1,
  filename: `${id}.bin`,
  toolName: 'code_executor',
  downloadable: true,
});

const items = [
  item('model', 'spreadsheet'),
  item('scores', 'pdf'),
  item('chart', 'image'),
  item('raw', 'data'),
];

describe('ArtifactsPanel', () => {
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

  const render = async (
    open: Parameters<typeof ArtifactsPanel>[0]['open'],
    onOpenChange = vi.fn(),
  ) => {
    await act(async () => {
      root.render(
        <SidePanel variant="docked" open onOpenChange={vi.fn()}>
          <ArtifactsPanel
            items={items}
            open={open}
            onOpenChange={onOpenChange}
            conversationId="c1"
          />
        </SidePanel>,
      );
    });
    return onOpenChange;
  };

  it('lists every artifact of the answer, grouped by kind', async () => {
    await render(null);
    const headings = Array.from(container.querySelectorAll('h3')).map(
      (h) => h.textContent,
    );
    expect(headings).toEqual([
      expect.stringContaining('conversation.artifacts.group.documents'),
      expect.stringContaining('conversation.artifacts.group.images'),
      expect.stringContaining('conversation.artifacts.group.data'),
    ]);
    expect(container.querySelectorAll('[data-artifact-row]')).toHaveLength(4);
  });

  it('opens a row as the second level', async () => {
    const onOpenChange = await render(null);
    const row = Array.from(
      container.querySelectorAll('[data-artifact-row]'),
    ).find((b) => b.textContent === 'title-chart') as HTMLButtonElement;
    await act(async () => row.click());
    expect(onOpenChange).toHaveBeenCalledWith({
      id: 'chart',
      toolName: 'code_executor',
      version: 1,
    });
  });

  it('shows the open artifact with Back to the list', async () => {
    const onOpenChange = await render({
      id: 'raw',
      toolName: 'code_executor',
      version: 1,
    });
    const panel = container.querySelector(
      '[data-testid="artifact-panel"]',
    ) as HTMLElement;
    expect(panel.dataset.id).toBe('raw');
    await act(async () =>
      (panel.querySelector('button') as HTMLButtonElement).click(),
    );
    expect(onOpenChange).toHaveBeenCalledWith(null);
  });
});
