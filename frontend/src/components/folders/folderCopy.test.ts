import { createInstance } from 'i18next';
import { describe, expect, it } from 'vitest';

import en from '../../locale/en.json';
import ru from '../../locale/ru.json';
import {
  folderCountLine,
  folderDeleteConsequence,
  folderErrorMessage,
  folderRootLabel,
} from './folderCopy';
import { FolderRequestError } from './useFolderActions';

const make = async (lng: string, translation: object) => {
  const i18n = createInstance();
  await i18n.init({
    lng,
    resources: { [lng]: { translation } },
    interpolation: { escapeValue: false },
  });
  return i18n.t;
};

describe('folder copy', () => {
  it('counts direct children, plural-aware, or says Empty', async () => {
    const t = await make('en', en);
    expect(
      folderCountLine(t, { item_count: 3, folder_count: 1 }, 'source'),
    ).toBe('3 sources · 1 folder');
    expect(
      folderCountLine(t, { item_count: 1, folder_count: 0 }, 'agent'),
    ).toBe('1 agent');
    expect(folderCountLine(t, { folder_count: 2 }, 'agent')).toBe('2 folders');
    expect(folderCountLine(t, {}, 'agent')).toBe('Empty');
  });

  it('uses the Russian plural forms', async () => {
    const t = await make('ru', ru);
    expect(
      folderCountLine(t, { item_count: 2, folder_count: 5 }, 'agent'),
    ).toBe('2 агента · 5 папок');
  });

  it('names the roots', async () => {
    const t = await make('en', en);
    expect(folderRootLabel(t, 'agent')).toBe('My agents');
    expect(folderRootLabel(t, 'source')).toBe('Knowledge');
  });

  it('says what a delete moves and where', async () => {
    const t = await make('en', en);
    expect(
      folderDeleteConsequence(
        t,
        { item_count: 12, folder_count: 2 },
        'source',
        'Knowledge',
      ),
    ).toBe(
      'Its 12 sources and 2 folders move to Knowledge. Nothing is deleted.',
    );
    expect(
      folderDeleteConsequence(t, { item_count: 1 }, 'agent', 'My agents'),
    ).toBe('Its 1 agent moves to My agents. Nothing is deleted.');
    expect(folderDeleteConsequence(t, {}, 'agent', 'My agents')).toBe(
      'The folder is empty. Nothing else is deleted.',
    );
  });

  it('maps server codes to messages, else the fallback', async () => {
    const t = await make('en', en);
    expect(
      folderErrorMessage(
        t,
        new FolderRequestError('folder_name_taken', ''),
        'folders.errors.saveFailed',
      ),
    ).toBe('A folder with this name already exists.');
    expect(
      folderErrorMessage(t, new Error('boom'), 'folders.errors.saveFailed'),
    ).toBe("Couldn't save the folder. Try again.");
  });
});
