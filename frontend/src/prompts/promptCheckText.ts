import type { TFunction } from 'i18next';

/** The topics `repeats_builtin` names: lines DocsGPT already adds. */
const BUILTIN_TOPICS = ['date', 'citations', 'formatting', 'data_guard'];

/** What the server's `prompt_checks` report about one line or the whole prompt. */
export type PromptCheckFacts = {
  code: string;
  /** The placeholder as written (`placeholder`). */
  text?: string | null;
  /** Which built-in line it repeats (`repeats_builtin`). */
  topic?: string | null;
  /** The `{{ tools.… }}` variables (`tool_variables`). */
  variables?: string[];
  /** The 1-based line it is on, when it is on one. */
  line?: number | null;
};

/**
 * One server check in words (`prompts.checks.*`), shared by the prompt
 * editor's hint and a review's server findings: the placeholder or the
 * variables it names, and the line when it has one. A code it doesn't
 * know is null, so a newer server's check shows nothing rather than a key.
 *
 * Args:
 *   t: The translate function.
 *   facts: The check's code and what it names.
 *
 * Returns:
 *   The sentence, or null.
 */
export function promptCheckText(
  t: TFunction,
  facts: PromptCheckFacts,
): string | null {
  const plain = { interpolation: { escapeValue: false } };
  let text: string | null = null;
  switch (facts.code) {
    case 'placeholder':
      text = t('prompts.checks.placeholder', {
        text: facts.text ?? '',
        ...plain,
      });
      break;
    case 'repeats_builtin':
      text = t(
        `prompts.checks.repeatsBuiltin.${
          facts.topic && BUILTIN_TOPICS.includes(facts.topic)
            ? facts.topic
            : 'other'
        }`,
      );
      break;
    case 'tool_variables': {
      const variables = facts.variables?.length
        ? facts.variables
        : facts.text
          ? [facts.text]
          : [];
      text = t('prompts.checks.toolVariables', {
        count: Math.max(variables.length, 1),
        variables: variables.join(', '),
        ...plain,
      });
      break;
    }
    case 'template_invalid':
      text = t('prompts.checks.templateInvalid');
      break;
    case 'boundaries_missing':
      text = t('prompts.checks.boundariesMissing');
      break;
    case 'citations_missing':
      text = t('prompts.checks.citationsMissing');
      break;
    default:
      return null;
  }
  return typeof facts.line === 'number' && facts.code !== 'placeholder'
    ? t('prompts.checks.onLine', { check: text, line: facts.line, ...plain })
    : text;
}
