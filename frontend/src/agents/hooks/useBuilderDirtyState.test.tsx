import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

import {
  type BuilderDirtyState,
  useBuilderDirtyState,
} from './useBuilderDirtyState';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

type Payload = { name: string; tools: string[] };

describe('useBuilderDirtyState', () => {
  let container: HTMLDivElement;
  let root: Root;
  let state: BuilderDirtyState<Payload>;

  function Probe(props: {
    payload: Payload;
    ready?: boolean;
    extras?: boolean;
  }) {
    state = useBuilderDirtyState(props.payload, {
      ready: props.ready,
      extras: props.extras,
    });
    return null;
  }

  const render = (props: Parameters<typeof Probe>[0]) =>
    act(async () => root.render(<Probe {...props} />));

  beforeEach(() => {
    container = document.createElement('div');
    root = createRoot(container);
  });

  afterEach(() => act(async () => root.unmount()));

  it('is clean on open and dirty once the payload moves away', async () => {
    await render({ payload: { name: '', tools: [] }, ready: true });
    expect(state.dirty).toBe(false);
    await render({ payload: { name: 'Bot', tools: [] }, ready: true });
    expect(state.dirty).toBe(true);
    // Back to what it opened with: nothing to save.
    await render({ payload: { name: '', tools: [] }, ready: true });
    expect(state.dirty).toBe(false);
  });

  it('waits for a loading item, then compares with what was loaded', async () => {
    await render({ payload: { name: '', tools: [] } });
    expect(state.dirty).toBe(false);
    await act(async () => state.markSaved({ name: 'Saved', tools: ['t'] }));
    await render({ payload: { name: 'Saved', tools: ['t'] } });
    expect(state.dirty).toBe(false);
    await render({ payload: { name: 'Saved', tools: [] } });
    expect(state.dirty).toBe(true);
  });

  it('takes a save, a draft save included, as the new baseline', async () => {
    await render({ payload: { name: '', tools: [] }, ready: true });
    await render({ payload: { name: 'Bot', tools: [] }, ready: true });
    await act(async () => state.markSaved({ name: 'Bot', tools: [] }));
    expect(state.dirty).toBe(false);
  });

  it('rebases a part saved on its own', async () => {
    await render({ payload: { name: '', tools: [] }, ready: true });
    await render({ payload: { name: '', tools: ['t'] }, ready: true });
    expect(state.dirty).toBe(true);
    await act(async () =>
      state.markSaved((base) => ({ ...base, tools: ['t'] })),
    );
    expect(state.dirty).toBe(false);
  });

  it('is dirty while an extra is pending', async () => {
    await render({ payload: { name: '', tools: [] }, ready: true });
    await render({
      payload: { name: '', tools: [] },
      ready: true,
      extras: true,
    });
    expect(state.dirty).toBe(true);
  });
});
