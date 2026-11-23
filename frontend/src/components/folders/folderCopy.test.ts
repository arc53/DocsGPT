import { createInstance } from 'i18next';
import { describe, expect, it } from 'vitest';

import en from '../../locale/en.json';
import ru from '../../locale/ru.json';
import {
  folderCountLine,
  folderDeleteConsequence,
  folderErrorMessage,
  folderRenamedMessage,
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

  it("counts the page's kind first, then what else the folder holds", async () => {
    const t = await make('en', en);
    const counts = { agent: 2, source: 4, tool: 3, prompt: 6 };
    expect(folderCountLine(t, { counts, folder_count: 0 }, 'prompt')).toBe(
      '6 prompts · also 2 agents, 4 sources, 3 tools',
    );
    expect(
      folderCountLine(
        t,
        { counts: { agent: 2, source: 0, tool: 3, prompt: 6 } },
        'prompt',
      ),
    ).toBe('6 prompts · also 2 agents, 3 tools');
    expect(
      folderCountLine(
        t,
        {
          counts: { agent: 0, source: 0, tool: 1, prompt: 0 },
          folder_count: 1,
        },
        'tool',
      ),
    ).toBe('1 tool · 1 folder');
    // Nothing of the page's kind: the rest, without "also".
    expect(
      folderCountLine(
        t,
        { counts: { agent: 1, source: 0, tool: 0, prompt: 0 } },
        'prompt',
      ),
    ).toBe('1 agent');
    expect(
      folderCountLine(
        t,
        { counts: { agent: 0, source: 0, tool: 0, prompt: 0 } },
        'prompt',
      ),
    ).toBe('Empty');
    // `counts` wins over the total in item_count.
    expect(
      folderCountLine(
        t,
        { item_count: 9, counts: { agent: 0, source: 2, tool: 7, prompt: 0 } },
        'source',
        { also: false },
      ),
    ).toBe('2 sources');
  });

  it('names the tools and prompts roots, and Agents in a team', async () => {
    const t = await make('en', en);
    expect(folderRootLabel(t, 'tool')).toBe('Tools');
    expect(folderRootLabel(t, 'prompt')).toBe('Prompts');
    expect(folderRootLabel(t, 'agent', { team: true })).toBe('Agents');
    expect(folderRootLabel(t, 'source', { team: true })).toBe('Knowledge');
  });

  it('says every kind a delete moves', async () => {
    const t = await make('en', en);
    expect(
      folderDeleteConsequence(
        t,
        {
          counts: { agent: 2, source: 0, tool: 1, prompt: 6 },
          folder_count: 1,
        },
        'prompt',
        'Prompts',
      ),
    ).toBe(
      'Its 6 prompts, 2 agents, 1 tool and 1 folder move to Prompts. Nothing is deleted.',
    );
  });

  it('maps the team filing refusals', async () => {
    const t = await make('en', en);
    expect(
      folderErrorMessage(
        t,
        new FolderRequestError('item_not_in_team', ''),
        'folders.errors.moveFailed',
      ),
    ).toBe(
      "A team's folders hold only the team's own items. Move the item to the team first.",
    );
    expect(
      folderErrorMessage(
        t,
        new FolderRequestError('team_item_not_fileable', ''),
        'folders.errors.moveFailed',
      ),
    ).toBe("A team's items can't go in a personal folder.");
  });

  it('lists the folders a delete renamed, or nothing', async () => {
    const t = await make('en', en);
    expect(folderRenamedMessage(t, [])).toBeNull();
    expect(
      folderRenamedMessage(t, [{ id: 'a', from: 'Rates', to: 'Rates (2)' }]),
    ).toBe(
      'Folder deleted. 1 folder was renamed to keep names unique: Rates → Rates (2).',
    );
    expect(
      folderRenamedMessage(t, [
        { id: 'a', from: 'Rates', to: 'Rates (2)' },
        { id: 'b', from: 'Old', to: 'Old (2)' },
      ]),
    ).toBe(
      'Folder deleted. 2 folders were renamed to keep names unique: Rates → Rates (2), Old → Old (2).',
    );
  });
});
