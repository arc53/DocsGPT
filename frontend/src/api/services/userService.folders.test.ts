import {
  setRequestWorkspace,
  WORKSPACE_HEADER,
} from '../../workspace/requestWorkspace';
import userService from './userService';

type Call = { url: string; init: RequestInit };
const calls: Call[] = [];

beforeEach(() => {
  calls.length = 0;
  vi.stubGlobal(
    'fetch',
    vi.fn((url: string, init: RequestInit) => {
      calls.push({ url, init });
      return Promise.resolve(new Response('{}', { status: 200 }));
    }),
  );
  setRequestWorkspace('t1', 1);
});

afterEach(() => {
  vi.unstubAllGlobals();
  setRequestWorkspace('personal', 0);
});

const headers = (i = 0) => calls[i].init.headers as Record<string, string>;

describe('userService folders', () => {
  it("loads the current workspace's whole tree", async () => {
    await userService.getFolders('tok');
    expect(calls[0].url.endsWith('/api/folders')).toBe(true);
    expect(headers()[WORKSPACE_HEADER]).toBe('t1');
  });

  it("reads another workspace's tree when asked", async () => {
    await userService.getFolders('tok', { workspace: 'personal' });
    expect(headers()[WORKSPACE_HEADER]).toBe('personal');
  });

  it('creates a folder without a kind', async () => {
    await userService.createFolder(
      { name: 'Onboarding', parent_id: null },
      'tok',
    );
    expect(JSON.parse(calls[0].init.body as string)).toEqual({
      name: 'Onboarding',
      parent_id: null,
    });
  });

  it('files tools and prompts', async () => {
    await userService.fileFolderItems(
      { type: 'prompt', folder_id: 'f1', ids: ['p1'] },
      'tok',
    );
    expect(JSON.parse(calls[0].init.body as string)).toEqual({
      type: 'prompt',
      folder_id: 'f1',
      ids: ['p1'],
    });
  });
});

describe('userService.getDocsWithPagination', () => {
  it('narrows the page by origin when asked', async () => {
    await userService.getDocsWithPagination('page=1', 'tok', 'shared');
    expect(calls[0].url).toMatch(
      /\/api\/sources\/paginated\?page=1&origin=shared$/,
    );
    await userService.getDocsWithPagination('page=1', 'tok');
    expect(calls[1].url).toMatch(/\/api\/sources\/paginated\?page=1$/);
  });
});
