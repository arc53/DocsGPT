import { describe, expect, it } from 'vitest';

import { canMoveToFolder } from './folderFiling';

describe('canMoveToFolder', () => {
  it("offers Move to folder in Personal for the caller's own and shared items", () => {
    expect(canMoveToFolder({ origin: 'own' }, false)).toBe(true);
    expect(canMoveToFolder({ origin: 'shared' }, false)).toBe(true);
    // An API older than workspaces sends no origin: the caller's own.
    expect(canMoveToFolder({}, false)).toBe(true);
  });

  it("never files a team's item in a personal folder", () => {
    expect(canMoveToFolder({ origin: 'team' }, false)).toBe(false);
  });

  it("files only the team's own items in a team's folders", () => {
    expect(canMoveToFolder({ origin: 'team' }, true)).toBe(true);
    expect(canMoveToFolder({ origin: 'shared' }, true)).toBe(false);
    expect(canMoveToFolder({ origin: 'own' }, true)).toBe(false);
  });

  it('follows allowed_actions when the item lists them', () => {
    expect(
      canMoveToFolder({ origin: 'own', allowed_actions: ['view'] }, false),
    ).toBe(false);
    expect(
      canMoveToFolder(
        { origin: 'team', allowed_actions: ['view', 'move_folder'] },
        true,
      ),
    ).toBe(true);
  });
});
