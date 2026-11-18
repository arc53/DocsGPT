import { RESOURCE_FETCHERS } from './CreateAccessTokenModal';
import {
  setRequestWorkspace,
  WORKSPACE_HEADER,
} from '../workspace/requestWorkspace';

const calls: { url: string; init: RequestInit }[] = [];

beforeEach(() => {
  calls.length = 0;
  vi.stubGlobal(
    'fetch',
    vi.fn((url: string, init: RequestInit) => {
      calls.push({ url, init });
      return Promise.resolve(new Response('[]'));
    }),
  );
  setRequestWorkspace('t1', 1);
});

afterEach(() => {
  vi.unstubAllGlobals();
  setRequestWorkspace('personal', 0);
});

describe('access token pickers', () => {
  it.each(Object.keys(RESOURCE_FETCHERS))(
    'list Personal %s while the app is in a team',
    async (kind) => {
      await RESOURCE_FETCHERS[kind]('tok');
      const headers = calls[0].init.headers as Record<string, string>;
      expect(headers[WORKSPACE_HEADER]).toBe('personal');
    },
  );
});
