const mermaidMock = vi.hoisted(() => ({
  initialize: vi.fn(),
  render: vi.fn(),
}));

vi.mock('mermaid', () => ({ default: mermaidMock }));

import { renderMermaidDiagram } from './mermaidSecurity';

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => {
    resolve = done;
  });
  return { promise, resolve };
}

describe('renderMermaidDiagram', () => {
  beforeEach(() => {
    mermaidMock.initialize.mockReset();
    mermaidMock.render.mockReset();
  });

  it('serializes initialization with rendering across security levels', async () => {
    const firstRender = deferred<{ svg: string }>();
    mermaidMock.render
      .mockImplementationOnce(() => firstRender.promise)
      .mockResolvedValueOnce({ svg: '<iframe sandbox=""></iframe>' });

    const conversation = renderMermaidDiagram({
      id: 'conversation-diagram',
      code: 'flowchart LR\nA --> B',
      isDarkTheme: false,
      securityLevel: 'strict',
    });
    const artifact = renderMermaidDiagram({
      id: 'artifact-diagram',
      code: 'flowchart LR\nB --> C',
      isDarkTheme: true,
      securityLevel: 'sandbox',
    });

    await vi.waitFor(() => expect(mermaidMock.render).toHaveBeenCalledTimes(1));
    expect(mermaidMock.initialize).toHaveBeenLastCalledWith(
      expect.objectContaining({ securityLevel: 'strict' }),
    );

    firstRender.resolve({ svg: '<svg></svg>' });
    await conversation;
    await artifact;

    expect(mermaidMock.initialize.mock.calls.map(([config]) => config)).toEqual(
      [
        expect.objectContaining({ securityLevel: 'strict' }),
        expect.objectContaining({ securityLevel: 'sandbox' }),
      ],
    );
    expect(mermaidMock.render.mock.calls).toEqual([
      ['conversation-diagram', 'flowchart LR\nA --> B'],
      ['artifact-diagram', 'flowchart LR\nB --> C'],
    ]);
  });

  it('renders from the code argument again when only the theme changes', async () => {
    mermaidMock.render.mockResolvedValue({ svg: '<svg></svg>' });
    const code = 'flowchart LR\nA --> B';

    await renderMermaidDiagram({
      id: 'theme-diagram',
      code,
      isDarkTheme: false,
      securityLevel: 'strict',
    });
    await renderMermaidDiagram({
      id: 'theme-diagram',
      code,
      isDarkTheme: true,
      securityLevel: 'strict',
    });

    expect(mermaidMock.render).toHaveBeenNthCalledWith(
      1,
      'theme-diagram',
      code,
    );
    expect(mermaidMock.render).toHaveBeenNthCalledWith(
      2,
      'theme-diagram',
      code,
    );
    expect(
      mermaidMock.initialize.mock.calls.map(([config]) => config.theme),
    ).toEqual(['default', 'dark']);
  });
});
