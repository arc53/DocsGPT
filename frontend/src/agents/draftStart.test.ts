import { draftStartState, readDraftStart } from './draftStart';

describe('readDraftStart', () => {
  it('reads back what draftStartState wrote', () => {
    expect(readDraftStart(draftStartState({ starter: 'research' }))).toEqual({
      starter: 'research',
    });
    expect(readDraftStart(draftStartState({ text: ' Help desk ' }))).toEqual({
      text: 'Help desk',
    });
    expect(readDraftStart(draftStartState({}))).toEqual({});
  });

  it('is null for a state that carries no draft start', () => {
    expect(readDraftStart(null)).toBeNull();
    expect(readDraftStart(undefined)).toBeNull();
    expect(readDraftStart('draftStart')).toBeNull();
    expect(readDraftStart({ from: '/agents' })).toBeNull();
    expect(readDraftStart({ draftStart: 'website' })).toBeNull();
  });

  it('drops an unknown starter and blank text', () => {
    expect(
      readDraftStart({ draftStart: { starter: 'pirate', text: '   ' } }),
    ).toEqual({});
    expect(readDraftStart({ draftStart: { starter: 7, text: 7 } })).toEqual({});
  });
});
