import { describe, expect, it } from 'vitest';

import en from '../locale/en.json';

// The confirm copy rule (DESIGN "Confirm dialogs"): the title is the verb and
// the quoted name as a question, the consequence is the description, and the
// submit is the bare verb from the domain's own key, on a destructive variant.

const sources = import.meta.glob<string>(
  ['../**/*.tsx', '!../**/*.test.tsx', '!../design/**'],
  { query: '?raw', import: 'default', eager: true },
);

const get = (path: string): unknown =>
  path
    .split('.')
    .reduce<unknown>(
      (o, k) =>
        o && typeof o === 'object' ? (o as Record<string, unknown>)[k] : null,
      en,
    );

// Every `<ConfirmationModal …>` opening tag in the app, with its file.
const confirms = Object.entries(sources).flatMap(([file, text]) => {
  const out: { file: string; tag: string }[] = [];
  const re = /<ConfirmationModal\b/g;
  let m: RegExpExecArray | null;
  while ((m = re.exec(text))) {
    // The tag ends at the first `/>` or `>` at the tag's indentation.
    const rest = text.slice(m.index);
    const end = rest.search(/\n\s*\/?>/);
    out.push({ file, tag: rest.slice(0, end) });
  }
  return out;
});

const DESTRUCTIVE_SUBMIT =
  /submitLabel=\{t\('[\w.]*\.(delete|revoke|remove|reset|deactivate|discard)\w*'\)\}|submitLabel=\{confirm\.submitLabel\}/i;

describe('confirm dialog copy', () => {
  it('finds the confirms', () => {
    expect(confirms.length).toBeGreaterThan(20);
  });

  it('puts a destructive variant on every destructive confirm', () => {
    const missing = confirms
      .filter(({ tag }) => DESTRUCTIVE_SUBMIT.test(tag))
      .filter(({ tag }) => !tag.includes('variant="destructive"'))
      .map(({ file }) => file);
    expect(missing).toEqual([]);
  });

  it('gives every destructive confirm a description', () => {
    const missing = confirms
      .filter(({ tag }) => tag.includes('variant="destructive"'))
      // The unsaved-edits discard has nothing more to say.
      .filter(({ tag }) => !tag.includes('editor.discardMessage'))
      .filter(({ tag }) => !/\bdescription=/.test(tag))
      .map(({ file }) => file);
    expect(missing).toEqual([]);
  });

  it('never borrows the conversation delete keys outside conversations', () => {
    const allowed = [
      'conversation/ConversationTile.tsx',
      'navigation/MobileTopBar.tsx',
      'Navigation.tsx',
    ];
    const borrowers = Object.entries(sources)
      .filter(([, text]) =>
        /t\('(convTile\.delete|modals\.deleteConv\.delete)'\)/.test(text),
      )
      .map(([file]) => file.replace(/^\.\.\//, ''))
      .filter((file) => !allowed.includes(file));
    expect(borrowers).toEqual([]);
  });

  it.each([
    'convTile.deleteWarning',
    'agents.deleteConfirmation',
    'agents.folders.deleteConfirm',
    'agents.schedules.deleteConfirm',
    'modals.prompts.deleteConfirmation',
    'modals.agentDetails.resetKeyConfirm',
    'settings.devices.revokeWarning',
    'settings.accessTokens.revokeWarning',
    'settings.customModels.deleteWarning',
    'settings.tools.deleteWarning',
    'settings.tools.deleteActionWarning',
    'settings.sources.deleteWarning',
    'settings.sources.syncConfirmation',
    'settings.teams.deleteTeamConfirmation',
    'settings.teams.removeMemberConfirmation',
    'settings.teams.share.removeConfirm',
    'settings.connectors.disconnect.title',
    'settings.connectors.remove.title',
  ])('%s is the verb and the quoted name as a question', (key) => {
    expect(get(key)).toMatch(/^[A-Z][a-z]+ (.* )?"\{\{\w+\}\}"( .*)?\?$/);
  });

  it.each([
    'modals.deleteConv.confirm',
    'modals.chunk.deleteConfirmation',
    'agents.workflow.builder.deleteConfirmUnnamed',
  ])('%s is a short question with no warning in it', (key) => {
    const value = String(get(key));
    expect(value).toMatch(/^[A-Z][^.?]*\?$/);
    expect(value).not.toMatch(/Are you sure/);
  });
});
