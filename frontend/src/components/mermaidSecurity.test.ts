import mermaid from 'mermaid';

import { initializeSecureMermaid } from './mermaidSecurity';

describe('initializeSecureMermaid', () => {
  beforeEach(() => {
    document.body.replaceChildren();
  });

  it('ignores security-level downgrade attempts in init directives', async () => {
    initializeSecureMermaid(false);
    const storedPayload = [
      '%%{init: {"securityLevel":"loose"}}%%',
      'flowchart LR',
      '  A[Click me]',
      '  click A "javascript:alert(document.domain)"',
    ].join('\n');

    const parsed = await mermaid.parse(storedPayload);

    expect(parsed).toMatchObject({ diagramType: 'flowchart-v2' });
    expect(mermaid.mermaidAPI.getConfig().securityLevel).toBe('strict');
  });

  it('continues to accept ordinary diagrams', async () => {
    initializeSecureMermaid(true);

    const parsed = await mermaid.parse(
      'flowchart LR\n  A[Start] --> B[Finish]',
    );

    expect(parsed).toMatchObject({ diagramType: 'flowchart-v2' });
    expect(mermaid.mermaidAPI.getConfig().theme).toBe('dark');
  });
});
