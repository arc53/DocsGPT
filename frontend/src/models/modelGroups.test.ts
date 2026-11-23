import { groupModels, isCatalogModel } from './modelGroups';
import type { ModelSource } from './types';

const model = (id: string, source?: ModelSource) => ({ id, source });

describe('groupModels', () => {
  it("puts a team's models in their own group, not the catalog's", () => {
    const groups = groupModels([
      model('gpt', 'builtin'),
      model('ops', 'team'),
      model('mine', 'user'),
      model('legacy'),
      model('ops-2', 'team'),
    ]);
    expect(groups.builtin.map((m) => m.id)).toEqual(['gpt', 'legacy']);
    expect(groups.team.map((m) => m.id)).toEqual(['ops', 'ops-2']);
    expect(groups.user.map((m) => m.id)).toEqual(['mine']);
  });
});

describe('isCatalogModel', () => {
  it('is false for any custom model', () => {
    expect(isCatalogModel(model('gpt', 'builtin'))).toBe(true);
    expect(isCatalogModel(model('legacy'))).toBe(true);
    expect(isCatalogModel(model('ops', 'team'))).toBe(false);
    expect(isCatalogModel(model('mine', 'user'))).toBe(false);
  });
});
