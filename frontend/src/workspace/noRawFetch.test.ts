// Every request that lists or creates something must carry the workspace
// header, and `api/client.ts` adds it to all of them. A request sent around
// the client (a bare `fetch`, an XHR, a beacon, an EventSource) doesn't get
// it, and a create sent that way silently lands in Personal. This test fails
// on any new one; add it to the list only once it sets the header itself or
// goes to a route that doesn't read the workspace.

const sources = import.meta.glob<string>(
  ['../**/*.ts', '../**/*.tsx', '!../**/*.test.ts', '!../**/*.test.tsx'],
  { query: '?raw', import: 'default', eager: true },
);

/**
 * The raw request sites allowed, by file, with how many each has:
 * - `api/client.ts`: the client itself (plain and throttled transport).
 * - `upload/Upload.tsx`: the upload and remote-ingest XHRs, which set the
 *   header themselves (checked below).
 * - `components/message-input/attachmentUpload.ts`: chat attachments, not
 *   kept per workspace.
 * - `conversation/conversationHandlers.ts`: the reconnect reader of one
 *   message, by its id.
 * - `events/eventStreamClient.ts`: the per-user event stream.
 * - `api/services/backgroundService.ts`: per-user presence and push.
 * - `components/useArtifactBytes.ts`: a presigned storage URL, which must
 *   not get the header (CORS).
 */
const ALLOWED: Record<string, number> = {
  '../api/client.ts': 2,
  '../upload/Upload.tsx': 2,
  '../components/message-input/attachmentUpload.ts': 1,
  '../conversation/conversationHandlers.ts': 2,
  '../events/eventStreamClient.ts': 1,
  '../api/services/backgroundService.ts': 3,
  '../components/useArtifactBytes.ts': 1,
};

// A call of the global `fetch` (not `refetch(`, `prefetch(`, `obj.fetch(`),
// an XHR, a beacon or an EventSource.
const RAW_REQUEST =
  /(?<![\w.$])fetch\(|new XMLHttpRequest\b|\.sendBeacon\(|new EventSource\b/g;

const stripComments = (text: string) =>
  text.replace(/\/\*[\s\S]*?\*\//g, '').replace(/^\s*\/\/.*$/gm, '');

const counts = Object.fromEntries(
  Object.entries(sources)
    .map(([file, text]) => [
      file,
      (stripComments(text).match(RAW_REQUEST) ?? []).length,
    ])
    .filter(([, n]) => (n as number) > 0),
) as Record<string, number>;

describe('requests go through the API client', () => {
  it('has no raw request outside the known sites', () => {
    const extra = Object.entries(counts)
      .filter(([file, n]) => n > (ALLOWED[file] ?? 0))
      .map(([file, n]) => `${file}: ${n}`);
    expect(extra).toEqual([]);
  });

  it('has every listed site still there (keep the list honest)', () => {
    const gone = Object.entries(ALLOWED)
      .filter(([file, n]) => (counts[file] ?? 0) < n)
      .map(([file]) => file);
    expect(gone).toEqual([]);
  });

  it('sends the workspace header from both upload XHRs', () => {
    const upload = stripComments(sources['../upload/Upload.tsx']);
    const headers = upload.match(/setRequestHeader\(\s*WORKSPACE_HEADER\b/g);
    expect(headers ?? []).toHaveLength(2);
  });
});
