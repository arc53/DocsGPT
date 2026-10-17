import actionToastReducer, {
  dismissActionToast,
  selectActionToast,
  showActionToast,
} from './actionToastSlice';

const state = (s: ReturnType<typeof actionToastReducer>) => ({
  actionToast: s,
});

describe('actionToastSlice', () => {
  it('starts empty', () => {
    const s = actionToastReducer(undefined, { type: '@@init' });
    expect(selectActionToast(state(s))).toBeNull();
  });

  it('shows a toast with a fresh id, replacing the previous one', () => {
    let s = actionToastReducer(
      undefined,
      showActionToast({ variant: 'success', message: 'a deactivated' }),
    );
    const first = selectActionToast(state(s));
    expect(first).toMatchObject({
      variant: 'success',
      message: 'a deactivated',
    });

    s = actionToastReducer(
      s,
      showActionToast({
        variant: 'destructive',
        message: 'Action failed for a',
      }),
    );
    const second = selectActionToast(state(s));
    expect(second).toMatchObject({
      variant: 'destructive',
      message: 'Action failed for a',
    });
    expect(second?.id).not.toBe(first?.id);
  });

  it('dismisses only the toast with the given id', () => {
    let s = actionToastReducer(
      undefined,
      showActionToast({ variant: 'success', message: 'one' }),
    );
    const id = selectActionToast(state(s))!.id;
    s = actionToastReducer(s, dismissActionToast(id + 1));
    expect(selectActionToast(state(s))).not.toBeNull();
    s = actionToastReducer(s, dismissActionToast(id));
    expect(selectActionToast(state(s))).toBeNull();
  });
});
