import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

import type { DrafterSession } from '../drafter/useDrafterSession';
import { type AgentBuildStep, parseAgentProposal } from './agentDraft';
import { type AgentBuild, useAgentBuild } from './useAgentBuild';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const fakeSession = () => {
  const calls: string[] = [];
  const session = {
    recipe: 'agent',
    items: [],
    step: null,
    streaming: false,
    texts: [] as string[],
    send: vi.fn<(text: string, options?: { hidden?: boolean }) => void>(),
    addMessage: vi.fn((text: string) => calls.push(`message:${text}`)),
    userTexts: () => [...session.texts],
    stop: vi.fn(),
    retry: vi.fn(),
    reset: vi.fn(() => calls.push('reset')),
  };
  return { session, calls };
};

const proposal = (
  fields: Record<string, unknown>,
  steps: AgentBuildStep[],
  next: AgentBuildStep | null,
) => parseAgentProposal({ fields, steps, next_step: next })!;

describe('useAgentBuild', () => {
  let container: HTMLDivElement;
  let root: Root;
  let build: AgentBuild;
  let fake: ReturnType<typeof fakeSession>;
  let skipped: AgentBuildStep[];
  // The step each context read sees, as a message sent right after reads it.
  let contexts: (AgentBuildStep | null)[];
  let hold: boolean;

  function Host() {
    build = useAgentBuild({
      session: fake.session as unknown as DrafterSession,
      skipped,
      continueText: (step) => `Continue with ${step}.`,
      doneText: 'All done.',
      hold,
    });
    return null;
  }

  const render = () => act(async () => root.render(<Host />));

  beforeEach(async () => {
    container = document.createElement('div');
    root = createRoot(container);
    fake = fakeSession();
    skipped = [];
    contexts = [];
    hold = false;
    fake.session.send.mockImplementation((text, options) => {
      contexts.push(build.context().step);
      fake.calls.push(`send:${text}:${options?.hidden ? 'hidden' : 'shown'}`);
    });
    await render();
  });
  afterEach(async () => {
    await act(async () => root.unmount());
  });

  it('starts at basics and counts four steps', async () => {
    expect(build.guided).toBe(false);
    expect(build.step).toBeNull();
    await act(async () => build.start());
    expect(build).toMatchObject({
      guided: true,
      step: 'basics',
      number: 1,
      total: 4,
      ready: false,
      done: false,
      nextStep: 'knowledge',
    });
    expect(build.context()).toEqual({
      step: 'basics',
      earlier: [],
      starter: null,
    });
  });

  it('keeps the starting point it began from for every step, until reset', async () => {
    await act(async () => build.start('website'));
    expect(build.context().starter).toBe('website');
    await act(async () =>
      build.onProposal(proposal({ name: 'Ship' }, ['basics'], 'knowledge')),
    );
    await act(async () => build.next());
    expect(build.context()).toMatchObject({
      step: 'knowledge',
      starter: 'website',
    });
    // A second start while the build runs changes nothing.
    await act(async () => build.start('research'));
    expect(build.context().starter).toBe('website');
    await act(async () => build.reset());
    expect(build.context().starter).toBeNull();
  });

  it('moves on with Next: folds the step, keeps the words, starts the next one hidden', async () => {
    await act(async () => build.start());
    fake.session.texts = ['A shipping agent for our website'];
    await act(async () =>
      build.onProposal(proposal({ name: 'Ship' }, ['basics'], 'knowledge')),
    );
    expect(build.ready).toBe(true);
    await act(async () => build.next());
    expect(fake.calls).toEqual([
      'reset',
      'send:Continue with knowledge.:hidden',
    ]);
    // The hidden message already runs in the new step.
    expect(contexts).toEqual(['knowledge']);
    expect(build).toMatchObject({
      step: 'knowledge',
      number: 2,
      finished: ['basics'],
      ready: false,
      filledAtOnce: 0,
    });
    expect(build.context().earlier).toEqual([
      'A shipping agent for our website',
    ]);
  });

  it('jumps past the steps a proposal filled at once', async () => {
    await act(async () => build.start());
    await act(async () =>
      build.onProposal(
        proposal(
          {
            name: 'Ops',
            sources: ['s1'],
            prompt: { kind: 'existing', id: 'p' },
          },
          ['basics', 'knowledge', 'prompt'],
          'safety',
        ),
      ),
    );
    expect(build.filledAhead).toBe(true);
    expect(build.nextStep).toBe('safety');
    await act(async () => build.next());
    expect(build).toMatchObject({
      step: 'safety',
      number: 4,
      filledAtOnce: 3,
      finished: ['basics', 'knowledge', 'prompt'],
    });
  });

  it('runs Next itself once an approval turn ends', async () => {
    await act(async () => build.start());
    fake.session.streaming = true;
    await render();
    await act(async () =>
      build.onProposal(proposal({}, ['basics'], 'knowledge')),
    );
    expect(build.ready).toBe(false);
    expect(fake.calls).toEqual([]);
    fake.session.streaming = false;
    await render();
    expect(fake.calls).toEqual([
      'reset',
      'send:Continue with knowledge.:hidden',
    ]);
    expect(build.step).toBe('knowledge');
  });

  it("doesn't take a proposal whose every part was dropped as an approval", async () => {
    await act(async () => build.start());
    fake.session.streaming = true;
    await render();
    await act(async () =>
      build.onProposal(
        parseAgentProposal({
          fields: {},
          dropped: [{ field: 'sources', id: 'made-up', reason: 'not_found' }],
          steps: ['basics'],
          next_step: 'knowledge',
        })!,
      ),
    );
    fake.session.streaming = false;
    await render();
    // The step stays, its Next for the user to press.
    expect(fake.calls).toEqual([]);
    expect(build.step).toBe('basics');
    expect(build.ready).toBe(true);
  });

  it("runs an approval's Next only once nothing on the form holds it", async () => {
    await act(async () => build.start());
    hold = true;
    await render();
    await act(async () =>
      build.onProposal(proposal({}, ['basics'], 'knowledge')),
    );
    expect(fake.calls).toEqual([]);
    hold = false;
    await render();
    expect(build.step).toBe('knowledge');
  });

  it('finishes after the last step with a message, and then reads as done', async () => {
    await act(async () => build.start());
    for (const [step, nextStep] of [
      ['basics', 'knowledge'],
      ['knowledge', 'prompt'],
      ['prompt', 'safety'],
      ['safety', null],
    ] as const) {
      await act(async () =>
        build.onProposal(proposal({ name: step }, [step], nextStep)),
      );
      await act(async () => build.next());
    }
    expect(fake.calls.at(-1)).toBe('message:All done.');
    expect(build).toMatchObject({
      done: true,
      step: null,
      guided: true,
      finished: ['basics', 'knowledge', 'prompt', 'safety'],
    });
    expect(build.context().step).toBeNull();
  });

  it('passes over a skipped step, and the count drops', async () => {
    skipped = ['safety'];
    await render();
    await act(async () => build.start());
    expect(build.total).toBe(3);
    await act(async () => build.next());
    await act(async () => build.next());
    expect(build.step).toBe('prompt');
    expect(build.nextStep).toBeNull();
    await act(async () =>
      build.onProposal(proposal({ starters: ['Hi'] }, ['prompt'], 'safety')),
    );
    // The server names safety; the client can't set it.
    expect(build.nextStep).toBeNull();
    await act(async () => build.next());
    expect(build.done).toBe(true);
  });

  it('keeps at most twelve earlier messages', async () => {
    await act(async () => build.start());
    fake.session.texts = Array.from({ length: 14 }, (_, i) => `m${i}`);
    await act(async () => build.next());
    expect(build.context().earlier).toHaveLength(12);
    expect(build.context().earlier[0]).toBe('m2');
  });

  it('focuses one step on a saved agent, with no Next', async () => {
    await act(async () => build.focus('safety'));
    expect(build).toMatchObject({ guided: false, step: 'safety' });
    await act(async () =>
      build.onProposal(
        proposal({ limits: { mode: 'none' } }, ['safety'], null),
      ),
    );
    expect(build.ready).toBe(false);
    await act(async () => build.next());
    expect(fake.calls).toEqual([]);
    await act(async () => build.reset());
    expect(build.step).toBeNull();
  });
});
