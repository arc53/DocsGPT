import { describe, expect, it } from 'vitest';

import de from '../../locale/de.json';
import en from '../../locale/en.json';
import es from '../../locale/es.json';
import fr from '../../locale/fr.json';
import jp from '../../locale/jp.json';
import ru from '../../locale/ru.json';
import zhTW from '../../locale/zh-TW.json';
import zh from '../../locale/zh.json';
import {
  CANNOT_MOVE_EFFECTS,
  CANNOT_MOVE_REASONS,
  MOVE_ERROR_CODES,
  MOVE_KINDS,
  MOVE_WITH_REASONS,
  cannotMoveEffectKey,
  cannotMoveReasonKey,
  moveErrorKey,
  moveErrorMessage,
  moveKindKey,
  moveWithReasonKey,
  nameList,
  payerName,
} from './movePlanCopy';

type Tree = { [key: string]: string | Tree };

const LOCALES = { de, en, es, fr, jp, ru, zh, zhTW } as Record<string, Tree>;

// A key resolves when the path holds a string, or (plural keys) `_other`.
const hasKey = (tree: Tree, key: string): boolean => {
  const parts = key.split('.');
  const leaf = parts.pop() as string;
  let node: string | Tree | undefined = tree;
  for (const part of parts) {
    if (!node || typeof node === 'string') return false;
    node = node[part];
  }
  if (!node || typeof node === 'string') return false;
  return (
    typeof node[leaf] === 'string' || typeof node[`${leaf}_other`] === 'string'
  );
};

const t = ((key: string, options?: Record<string, unknown>) => {
  if (!options) return key;
  const params = Object.entries(options)
    .filter(([name]) => name !== 'interpolation')
    .map(([name, value]) => `${name}=${value}`)
    .join(',');
  return `${key}(${params})`;
}) as never;

describe('move plan copy', () => {
  const keys = [
    ...CANNOT_MOVE_REASONS.map(cannotMoveReasonKey),
    ...CANNOT_MOVE_EFFECTS.map(cannotMoveEffectKey),
    ...MOVE_WITH_REASONS.map(moveWithReasonKey),
    ...MOVE_ERROR_CODES.map(moveErrorKey),
    ...MOVE_KINDS.map(moveKindKey),
  ];

  it('covers every reason, effect and code the backend sends', () => {
    expect([...CANNOT_MOVE_REASONS].sort()).toEqual(
      [
        'connection_account',
        'connector_synced',
        'credentials_unreadable',
        'custom_model',
        'in_knowledge_folder',
        'not_yours',
        'remote_device',
      ].sort(),
    );
    expect([...CANNOT_MOVE_EFFECTS].sort()).toEqual([
      'removed_from_holder',
      'stays',
    ]);
    expect([...MOVE_WITH_REASONS].sort()).toEqual([
      'in_folder',
      'same_workflow',
      'used_by_agent',
    ]);
    expect(MOVE_ERROR_CODES).toEqual(
      expect.arrayContaining([
        'move_plan_changed',
        'move_would_borrow',
        'move_needs_admin',
        'credentials_unreadable',
        'credentials_unavailable',
        'nothing_to_move',
        'fingerprint_required',
        'folder_too_deep',
        'already_in_workspace',
        'invalid_request',
        'workspace_role_required',
        'not_a_person',
        'workspace_not_found',
        'not_found',
        'folder_not_found',
        'move_failed',
      ]),
    );
    expect(MOVE_KINDS).toEqual(
      expect.arrayContaining([
        'agent',
        'source',
        'tool',
        'prompt',
        'folder',
        'model',
      ]),
    );
  });

  it.each(Object.entries(LOCALES))('%s has every string', (_name, tree) => {
    expect(keys.filter((key) => !hasKey(tree, key))).toEqual([]);
  });

  it('reads an unknown code as a failed move', () => {
    expect(moveErrorKey('something_new')).toBe(
      'workspace.move.errors.move_failed',
    );
  });

  it('names the agents a refusal lists, and counts the rest', () => {
    const message = moveErrorMessage(t, {
      error: 'move_would_borrow',
      body: { agents: [{ id: 'a', name: 'Public bot' }], others: 2 },
      direction: 'in',
      teamName: 'Operations',
    });
    expect(message).toContain('workspace.move.borrow.in');
    expect(message).toContain('Public bot');
    expect(message).toContain('workspace.move.othersYouCantOpen');
  });

  it('names the tools whose secret is unreadable', () => {
    const message = moveErrorMessage(t, {
      error: 'credentials_unreadable',
      body: { tools: [{ id: 't', name: 'Linear' }] },
      direction: 'in',
      teamName: 'Operations',
    });
    expect(message).toContain('workspace.move.errors.credentials_unreadable');
    expect(message).toContain('Linear');
  });

  it('joins names and says "you" for the caller', () => {
    expect(nameList(t, ['A', 'B'])).toContain('A');
    expect(payerName(t, { user_id: 'u1', label: 'lena@x' }, 'u1')).toBe(
      'workspace.move.payerYou',
    );
    expect(payerName(t, { user_id: 'u2', label: 'dana@x' }, 'u1')).toBe(
      'dana@x',
    );
    expect(payerName(t, null, 'u1')).toBe('workspace.move.someone');
  });
});
