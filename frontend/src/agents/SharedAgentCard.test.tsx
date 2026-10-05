import { renderToStaticMarkup } from 'react-dom/server';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

import SharedAgentCard from './SharedAgentCard';

describe('SharedAgentCard', () => {
  // Card surfaces: a summary of one agent is a thing, so it is a filled tile.
  it('is a filled tile', () => {
    const html = renderToStaticMarkup(
      <SharedAgentCard
        agent={
          { id: 'a1', name: 'Carrier FAQ', description: 'Answers' } as never
        }
      />,
    );
    expect(html).toContain('data-slot="card"');
    expect(html).toContain('data-variant="filled"');
  });
});
