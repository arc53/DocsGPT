import { renderToStaticMarkup } from 'react-dom/server';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

import AgentPageToolbar from './components/AgentPageToolbar';
import OwnerInactiveNotice, {
  AgentNoticeContext,
  OwnerInactiveBadge,
} from './OwnerInactiveNotice';
import type { Agent } from './types';

const agent = (ownerInactive: boolean) =>
  ({ id: 'a1', name: 'Desk', owner_inactive: ownerInactive }) as Agent & {
    owner_inactive: boolean;
  };

describe("an agent whose owner's account is deactivated", () => {
  it('says outside access is paused', () => {
    const html = renderToStaticMarkup(
      <OwnerInactiveNotice agent={agent(true)} />,
    );
    expect(html).toContain('workspace.notices.ownerInactive');
    expect(html).toContain('role="note"');
  });

  it('says nothing for an active owner', () => {
    expect(
      renderToStaticMarkup(<OwnerInactiveNotice agent={agent(false)} />),
    ).toBe('');
  });

  it("shows on an agent page's toolbar from the opened agent", () => {
    const html = renderToStaticMarkup(
      <AgentNoticeContext.Provider value={agent(true)}>
        <AgentPageToolbar name="Desk" />
      </AgentNoticeContext.Provider>,
    );
    expect(html).toContain('workspace.notices.ownerInactive');
  });

  it("doesn't show on a toolbar outside an agent's pages", () => {
    expect(
      renderToStaticMarkup(<AgentPageToolbar name="Desk" />),
    ).not.toContain('workspace.notices.ownerInactive');
  });

  it("the builder's header carries a short badge", () => {
    const html = renderToStaticMarkup(
      <AgentNoticeContext.Provider value={agent(true)}>
        <OwnerInactiveBadge />
      </AgentNoticeContext.Provider>,
    );
    expect(html).toContain('workspace.notices.ownerInactiveShort');
  });
});
