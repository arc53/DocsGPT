import type { TFunction } from 'i18next';

const TEAM_ERRORS = 'settings.customModels.team.errors';

/**
 * Refusal codes about custom models and the locale key each reads as. The
 * model routes and an agent save send the code in `error`; a workflow save
 * keeps a sentence in `error` and sends the code in `code`.
 */
export const CUSTOM_MODEL_ERROR_KEYS: Readonly<Record<string, string>> = {
  credentials_unreadable: `${TEAM_ERRORS}.credentialsUnreadable`,
  custom_model_admin_required: `${TEAM_ERRORS}.adminRequired`,
  custom_model_personal_only: `${TEAM_ERRORS}.personalOnly`,
  custom_model_team_only: `${TEAM_ERRORS}.teamOnly`,
  model_admin_required: `${TEAM_ERRORS}.modelAdminRequired`,
  model_already_in_team: `${TEAM_ERRORS}.alreadyInTeam`,
  model_not_found: `${TEAM_ERRORS}.notFound`,
  not_available_to_tokens: `${TEAM_ERRORS}.notAvailableToTokens`,
  team_id_required: `${TEAM_ERRORS}.teamIdRequired`,
  team_workspace_required: `${TEAM_ERRORS}.teamWorkspaceRequired`,
  workspace_not_found: `${TEAM_ERRORS}.teamNotFound`,
  workspace_role_required: `${TEAM_ERRORS}.roleRequired`,
};

/**
 * A team chat without an agent asked for the caller's own model
 * (`custom_model_personal_only` on `/stream` and `/api/answer`): the chat
 * words it apart from a save refused for the same code.
 */
export const CUSTOM_MODEL_CHAT_PERSONAL_ONLY_KEY = `${TEAM_ERRORS}.chatPersonalOnly`;

// The codes an agent or workflow save answers when it names a custom model
// its owner can't run with.
const SAVE_CODES = new Set([
  'custom_model_personal_only',
  'custom_model_team_only',
]);

type Body = Record<string, unknown>;

const asBody = (data: unknown): Body | null =>
  data && typeof data === 'object' ? (data as Body) : null;

/**
 * The custom model refusal code in a response body: `code` when it is one,
 * else `error` when it is one.
 *
 * Args:
 *   data: The response's JSON.
 *
 * Returns:
 *   A key of `CUSTOM_MODEL_ERROR_KEYS`, or null.
 */
export function customModelErrorCode(data: unknown): string | null {
  const body = asBody(data);
  if (!body) return null;
  for (const value of [body.code, body.error]) {
    if (typeof value === 'string' && value in CUSTOM_MODEL_ERROR_KEYS)
      return value;
  }
  return null;
}

/**
 * Whether an agent or workflow save was refused for a custom model its
 * owner can't run with (a person's model on a team item, a team's model on
 * a personal item or another team's). Other codes of the map mean something
 * else on those routes, so only these two count.
 *
 * Args:
 *   data: The response's JSON.
 *
 * Returns:
 *   True for `custom_model_personal_only` and `custom_model_team_only`.
 */
export function isCustomModelSaveRefusal(data: unknown): boolean {
  const code = customModelErrorCode(data);
  return code !== null && SAVE_CODES.has(code);
}

/**
 * The model ids a refused save named (`models`), as the item gave them.
 *
 * Args:
 *   data: The response's JSON.
 *
 * Returns:
 *   The ids; empty for any other body.
 */
export function customModelRefusedIds(data: unknown): string[] {
  if (!isCustomModelSaveRefusal(data)) return [];
  const models = asBody(data)?.models;
  return Array.isArray(models)
    ? models.filter((id): id is string => typeof id === 'string')
    : [];
}

// A bare code (`invalid_owner`) is not a sentence to show.
const isCode = (text: string) => /^[a-z0-9_]+$/.test(text);

/**
 * What to say about a refused custom model request: the app's words for a
 * custom model code, else the server's own sentence (`message`, then
 * `error`), else `fallback`. A server error's text (5xx) is never shown.
 *
 * Args:
 *   t: The translate function.
 *   data: The response's JSON, if it parsed.
 *   options.status: The response's HTTP status.
 *   options.fallback: The generic line; empty when left out.
 *
 * Returns:
 *   The message.
 */
export function customModelErrorMessage(
  t: TFunction,
  data: unknown,
  { status, fallback = '' }: { status?: number; fallback?: string } = {},
): string {
  const code = customModelErrorCode(data);
  if (code) return t(CUSTOM_MODEL_ERROR_KEYS[code]);
  if (status !== undefined && status >= 500) return fallback;
  const body = asBody(data);
  const text = [body?.message, body?.error].find(
    (value): value is string =>
      typeof value === 'string' && !!value.trim() && !isCode(value),
  );
  return text ?? fallback;
}

/**
 * `customModelErrorMessage` for an error `customModelsService` threw: it
 * carries the response's `status` and parsed body as `payload`. A network
 * error (neither) reads as `fallback`.
 *
 * Args:
 *   t: The translate function.
 *   error: What the service call threw.
 *   fallback: The generic line.
 *
 * Returns:
 *   The message.
 */
export function customModelRequestError(
  t: TFunction,
  error: unknown,
  fallback: string,
): string {
  const failed = asBody(error) as {
    status?: unknown;
    payload?: unknown;
  } | null;
  return customModelErrorMessage(t, failed?.payload, {
    status: typeof failed?.status === 'number' ? failed.status : undefined,
    fallback,
  });
}
