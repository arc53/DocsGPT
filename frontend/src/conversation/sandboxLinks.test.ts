import { defaultUrlTransform } from 'react-markdown';
import { describe, expect, it } from 'vitest';

import {
  resolveSandboxLink,
  sandboxUrlTransform,
  type SandboxArtifact,
} from './sandboxLinks';

describe('the bug this module exists for', () => {
  // Pins the upstream behaviour the fix depends on: without a custom
  // transform the href is blanked, and `<a href="" target="_blank">` reopens
  // the app in a new tab instead of downloading anything.
  it('react-markdown blanks sandbox: urls by default', () => {
    expect(defaultUrlTransform('sandbox:/artifact/A1')).toBe('');
    expect(defaultUrlTransform('sandbox:/mnt/data/deck.pptx')).toBe('');
  });
});

// A second-turn pair: the conversation already produced A1 and A2 earlier, so
// these carry refs A3/A4. Resolving `A3` by position would open the wrong file.
const artifacts: SandboxArtifact[] = [
  {
    id: '9d28fc58-f02f-4d78-a45d-143f60d580e4',
    label: 'summer_sweep_up.pdf',
    ref: 'A3',
  },
  {
    id: 'ba9579b0-4125-431d-b47a-8b7e70026cd6',
    label: 'Java Notes.pdf',
    ref: 'A4',
  },
];

describe('sandboxUrlTransform', () => {
  // react-markdown's defaultUrlTransform blanks any unknown protocol, so the
  // href reaching the ``a`` component is '' and the anchor navigates to the
  // current page in a new tab. Keeping the scheme is what makes the link
  // recoverable at render time.
  it('preserves artifact: urls too', () => {
    expect(sandboxUrlTransform('artifact:A1')).toBe('artifact:A1');
    expect(defaultUrlTransform('artifact:A1')).toBe('');
  });

  it('preserves sandbox: urls that the default transform would blank', () => {
    expect(sandboxUrlTransform('sandbox:/artifact/A1')).toBe(
      'sandbox:/artifact/A1',
    );
    expect(sandboxUrlTransform('sandbox:/mnt/data/deck.pptx')).toBe(
      'sandbox:/mnt/data/deck.pptx',
    );
  });

  it('still blanks genuinely unsafe protocols', () => {
    expect(sandboxUrlTransform('javascript:alert(1)')).toBe('');
    expect(sandboxUrlTransform('data:text/html;base64,PHNjcmlwdD4=')).toBe('');
  });

  it('leaves safe and relative urls untouched', () => {
    expect(sandboxUrlTransform('https://example.com/x')).toBe(
      'https://example.com/x',
    );
    expect(sandboxUrlTransform('#cite-2')).toBe('#cite-2');
    expect(sandboxUrlTransform('/api/artifacts/x/download')).toBe(
      '/api/artifacts/x/download',
    );
  });
});

describe('resolveSandboxLink', () => {
  it('treats non-sandbox hrefs as ordinary links', () => {
    expect(resolveSandboxLink('https://example.com', artifacts)).toEqual({
      kind: 'external',
    });
    expect(resolveSandboxLink(undefined, artifacts)).toEqual({
      kind: 'external',
    });
  });

  it('resolves a full artifact id', () => {
    expect(
      resolveSandboxLink(
        'sandbox:/artifact/9d28fc58-f02f-4d78-a45d-143f60d580e4',
        artifacts,
      ),
    ).toEqual({ kind: 'artifact', artifact: artifacts[0] });
  });

  // The model writes both the singular and the plural form.
  it('resolves the plural /artifacts/ spelling', () => {
    expect(
      resolveSandboxLink(
        'sandbox:/artifacts/ba9579b0-4125-431d-b47a-8b7e70026cd6',
        artifacts,
      ),
    ).toEqual({ kind: 'artifact', artifact: artifacts[1] });
  });

  it('resolves a short ref against the artifact ref, case-insensitively', () => {
    expect(resolveSandboxLink('sandbox:/artifact/A3', artifacts)).toEqual({
      kind: 'artifact',
      artifact: artifacts[0],
    });
    expect(resolveSandboxLink('sandbox:/artifact/a4', artifacts)).toEqual({
      kind: 'artifact',
      artifact: artifacts[1],
    });
  });

  // `A{n}` is the artifact's stable per-CONVERSATION ref_seq, not an index into
  // this turn's artifacts. Positional resolution silently opened a different
  // file whenever an earlier turn had produced one.
  it('never resolves a ref by position', () => {
    expect(resolveSandboxLink('sandbox:/artifact/A1', artifacts)).toEqual({
      kind: 'plain',
    });
    expect(resolveSandboxLink('artifact:A2', artifacts)).toEqual({
      kind: 'plain',
    });
  });

  it('degrades a ref to plain text when the artifacts carry none', () => {
    const legacy = [{ id: 'x', label: 'old.pdf' }];
    expect(resolveSandboxLink('artifact:A1', legacy)).toEqual({
      kind: 'plain',
    });
  });

  // The model writes the filename under /artifact/ too, not only under /tmp/.
  it('recovers a filename under an artifact path', () => {
    expect(
      resolveSandboxLink('sandbox:/artifacts/summer_sweep_up.pdf', artifacts),
    ).toEqual({ kind: 'artifact', artifact: artifacts[0] });
    expect(resolveSandboxLink('artifact:Java%20Notes.pdf', artifacts)).toEqual({
      kind: 'artifact',
      artifact: artifacts[1],
    });
  });

  // URL schemes are case-insensitive; a capitalised one reaching the anchor
  // branch is the original dead-link bug.
  it('matches the scheme case-insensitively', () => {
    expect(resolveSandboxLink('Sandbox:/mnt/data/x.pdf', artifacts).kind).toBe(
      'plain',
    );
    expect(sandboxUrlTransform('Sandbox:/artifact/A3')).toBe(
      'Sandbox:/artifact/A3',
    );
  });

  // The fabricated ``/mnt/data/`` form is the oldest and most common one, and
  // the file it names usually does exist as an artifact on the same turn.
  it('recovers a fabricated /mnt/data path by filename', () => {
    expect(
      resolveSandboxLink('sandbox:/mnt/data/summer_sweep_up.pdf', artifacts),
    ).toEqual({ kind: 'artifact', artifact: artifacts[0] });
  });

  it('recovers a fabricated /tmp path and a bare filename', () => {
    expect(
      resolveSandboxLink('sandbox:/tmp/summer_sweep_up.pdf', artifacts),
    ).toEqual({ kind: 'artifact', artifact: artifacts[0] });
    expect(resolveSandboxLink('sandbox:/Java%20Notes.pdf', artifacts)).toEqual({
      kind: 'artifact',
      artifact: artifacts[1],
    });
  });

  it('degrades to plain text when nothing matches', () => {
    expect(
      resolveSandboxLink('sandbox:/tmp/never_existed.pdf', artifacts),
    ).toEqual({ kind: 'plain' });
    expect(resolveSandboxLink('sandbox:/artifact/A9', artifacts)).toEqual({
      kind: 'plain',
    });
    expect(resolveSandboxLink('sandbox:/artifact/A3', [])).toEqual({
      kind: 'plain',
    });
  });

  // Found by running the real model against this build: with no prompt rule
  // it emits `[Download **Q3 Notes**](artifact:A1)` — a bare ref under an
  // `artifact:` scheme, which react-markdown blanks exactly like `sandbox:`.
  it('resolves the artifact: scheme with a bare ref', () => {
    expect(resolveSandboxLink('artifact:A3', artifacts)).toEqual({
      kind: 'artifact',
      artifact: artifacts[0],
    });
    expect(
      resolveSandboxLink(
        'artifact:9d28fc58-f02f-4d78-a45d-143f60d580e4',
        artifacts,
      ),
    ).toEqual({ kind: 'artifact', artifact: artifacts[0] });
  });

  it('resolves the artifact: scheme with a path form', () => {
    expect(resolveSandboxLink('artifact:/artifact/A4', artifacts)).toEqual({
      kind: 'artifact',
      artifact: artifacts[1],
    });
  });

  it('degrades an unresolvable artifact: ref to plain text', () => {
    expect(resolveSandboxLink('artifact:A9', artifacts)).toEqual({
      kind: 'plain',
    });
  });

  it('never renders an anchor for a sandbox href', () => {
    for (const href of [
      'sandbox:/artifact/A1',
      'sandbox:/mnt/data/x.pdf',
      'sandbox:',
      'sandbox:/',
      'artifact:A3',
      'artifact:',
      'Sandbox:/artifact/A3',
    ]) {
      expect(resolveSandboxLink(href, artifacts).kind).not.toBe('external');
    }
  });
});

describe('duplicate filenames within one turn', () => {
  // A second `run_code` that rewrites `report.pdf` creates a second artifact
  // row with the same filename. The model's prose means the file as it stands
  // after the last write, so the newer copy is the one to open.
  const twoWrites = [
    { id: 'stale', label: 'report.pdf', ref: 'A1' },
    { id: 'fresh', label: 'report.pdf', ref: 'A2' },
  ];

  it('resolves a bare filename to the most recent copy', () => {
    const resolved = resolveSandboxLink(
      'sandbox:/mnt/data/report.pdf',
      twoWrites,
    );
    expect(resolved).toEqual({
      kind: 'artifact',
      artifact: { id: 'fresh', label: 'report.pdf', ref: 'A2' },
    });
  });

  it('still honours an explicit ref over the filename', () => {
    const resolved = resolveSandboxLink('artifact:A1', twoWrites);
    expect(resolved).toEqual({
      kind: 'artifact',
      artifact: { id: 'stale', label: 'report.pdf', ref: 'A1' },
    });
  });
});

describe('scheme-less and file: hrefs', () => {
  const available = [{ id: 'a1', label: 'report.pdf', ref: 'A1' }];

  it.each([
    '/mnt/data/report.pdf',
    'report.pdf',
    './report.pdf',
    '/tmp/report.pdf',
    'file:///mnt/data/report.pdf',
  ])('resolves %s to the artifact', (href) => {
    expect(resolveSandboxLink(href, available)).toEqual({
      kind: 'artifact',
      artifact: available[0],
    });
  });

  it('leaves an unresolvable relative link as an ordinary link', () => {
    expect(resolveSandboxLink('/docs/intro', available)).toEqual({
      kind: 'external',
    });
  });

  it('leaves in-page anchors alone', () => {
    expect(resolveSandboxLink('#cite-2', available)).toEqual({
      kind: 'external',
    });
  });

  it('leaves other schemes alone', () => {
    expect(
      resolveSandboxLink('https://example.com/report.pdf', available),
    ).toEqual({
      kind: 'external',
    });
    expect(resolveSandboxLink('mailto:a@b.com', available)).toEqual({
      kind: 'external',
    });
  });

  it('renders an unresolvable file: href as plain text, never a dead href', () => {
    expect(resolveSandboxLink('file:///mnt/data/nope.pdf', available)).toEqual({
      kind: 'plain',
    });
  });
});

// Two turns each produced a file called `report.pdf`. That is not exotic:
// `_filename()` in artifact_generator.py hands EVERY html artifact the name
// `report.html`, and re-running a script that writes `chart.png` collides too.
describe('a filename that two turns both produced', () => {
  const turnOne: SandboxArtifact = {
    id: 'id-old',
    label: 'report.pdf',
    ref: 'A1',
    toolName: 'artifact_generator',
  };
  const turnTwo: SandboxArtifact = {
    id: 'id-new',
    label: 'report.pdf',
    ref: 'A2',
    toolName: 'artifact_generator',
  };
  // What ConversationMessages passes: the whole conversation, in order.
  const conversation = [turnOne, turnTwo];

  it("resolves turn one's link to turn one's file, not the newest copy", () => {
    // Without the turn scope this returned `id-new`, so the prose link opened
    // a different file from the download chip in the very same bubble.
    expect(
      resolveSandboxLink('sandbox:/mnt/data/report.pdf', conversation, [
        turnOne,
      ]),
    ).toEqual({ kind: 'artifact', artifact: turnOne });
  });

  it("resolves turn two's link to turn two's file", () => {
    expect(
      resolveSandboxLink('sandbox:/mnt/data/report.pdf', conversation, [
        turnTwo,
      ]),
    ).toEqual({ kind: 'artifact', artifact: turnTwo });
  });

  it('still reaches an earlier turn when this turn produced nothing', () => {
    // The fallback that keeps "the CSV from earlier" working.
    expect(
      resolveSandboxLink('sandbox:/mnt/data/report.pdf', conversation, []),
    ).toEqual({ kind: 'artifact', artifact: turnTwo });
  });

  it('matches a ref conversation-wide even when this turn owns a file', () => {
    // Refs are unambiguous, so they must NOT be narrowed — this is the
    // cross-turn resolution the conversation-wide list was added for.
    expect(resolveSandboxLink('artifact:A1', conversation, [turnTwo])).toEqual({
      kind: 'artifact',
      artifact: turnOne,
    });
  });

  it('matches an id conversation-wide even when this turn owns a file', () => {
    expect(
      resolveSandboxLink('sandbox:/artifact/id-old', conversation, [turnTwo]),
    ).toEqual({ kind: 'artifact', artifact: turnOne });
  });
});
