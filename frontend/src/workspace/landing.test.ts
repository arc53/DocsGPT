import {
  switchOnArrival,
  withoutSwitchRequest,
  workspaceLandingPath,
} from './landing';

describe('workspaceLandingPath: where a switch lands', () => {
  it.each([
    // List pages stay, without the folder or an open item.
    ['/agents/manage', '?folder=f1', '/agents/manage'],
    ['/agents/manage/mine', '', '/agents/manage/mine'],
    [
      '/settings/knowledge',
      '?source=s1&folder=f1&kind=web',
      '/settings/knowledge?kind=web',
    ],
    ['/settings/tools', '', '/settings/tools'],
    ['/settings/prompts', '?folder=f2', '/settings/prompts'],
    ['/settings/connectors', '', '/settings/connectors'],
    ['/activity/history', '', '/activity/history'],
    ['/c/new', '', '/c/new'],
    ['/', '', '/'],
    // Personal settings and team pages stay.
    ['/settings/general', '', '/settings/general'],
    ['/settings/access-tokens', '', '/settings/access-tokens'],
    ['/teams/t1/members', '', '/teams/t1/members'],
    ['/admin/users', '?q=dana', '/admin/users?q=dana'],
    // An item's page goes to its list.
    ['/agents/manage/edit/a1', '', '/agents/manage'],
    ['/agents/manage/logs/a1', '', '/agents/manage'],
    ['/agents/manage/workflow/edit/a1', '', '/agents/manage'],
    ['/agents/manage/new', '', '/agents/manage'],
    ['/agents/shared/a1', '', '/agents/manage'],
    ['/agents/a1/c/c1', '', '/c/new'],
    ['/c/0b6f2a', '', '/c/new'],
  ])('%s%s → %s', (pathname, search, expected) => {
    expect(workspaceLandingPath(pathname, search)).toBe(expected);
  });
});

describe('withoutSwitchRequest: what a page keeps once its switch is done', () => {
  it('keeps the rest of the state, and nothing when only the switch was in it', () => {
    expect(
      withoutSwitchRequest({
        newMcpServer: { a: 1 },
        ...switchOnArrival('t1'),
      }),
    ).toEqual({ newMcpServer: { a: 1 } });
    expect(withoutSwitchRequest(switchOnArrival('t1'))).toBeNull();
    expect(withoutSwitchRequest(null)).toBeNull();
  });
});
