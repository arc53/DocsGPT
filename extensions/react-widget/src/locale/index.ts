import { de } from './de';
import { en, type Messages, type PluralKey } from './en';
import { es } from './es';
import { fr } from './fr';
import { ja } from './ja';
import { ru } from './ru';
import { zh } from './zh';
import { zhTW } from './zhTW';

export type { Messages, PluralKey };

/** The languages the widget's UI text ships in, as BCP 47 codes. */
export const SUPPORTED_LOCALES = [
  'en',
  'es',
  'fr',
  'ja',
  'zh',
  'zh-TW',
  'ru',
  'de',
] as const;

/** One of `SUPPORTED_LOCALES`. */
export type SupportedLocale = (typeof SUPPORTED_LOCALES)[number];

// Bundled rather than loaded on demand: the script-tag build is one file.
const CATALOGS: Record<SupportedLocale, Messages> = {
  en,
  es,
  fr,
  ja,
  zh,
  'zh-TW': zhTW,
  ru,
  de,
};

/**
 * The supported locale a BCP 47 tag maps to, or null. Exact code first, then
 * the base language (`de-AT` → `de`). Chinese splits by script: Traditional
 * (`zh-Hant*`, or the TW/HK/MO regions) is `zh-TW`, any other `zh*` is `zh`.
 */
export const matchLocale = (tag: string): SupportedLocale | null => {
  const parts = String(tag).trim().replace(/_/g, '-').toLowerCase().split('-');
  const base = parts[0];
  if (!base) return null;
  if (base === 'zh') {
    const script = parts.find((part) => part.length === 4);
    if (script === 'hant') return 'zh-TW';
    if (script === 'hans') return 'zh';
    return parts.some((part) => ['tw', 'hk', 'mo'].includes(part))
      ? 'zh-TW'
      : 'zh';
  }
  const exact = SUPPORTED_LOCALES.find(
    (code) => code.toLowerCase() === parts.join('-'),
  );
  if (exact) return exact;
  return SUPPORTED_LOCALES.find((code) => code === base) ?? null;
};

/** The visitor's preferred languages, most preferred first. */
export const browserLanguages = (): readonly string[] => {
  if (typeof navigator === 'undefined') return [];
  if (navigator.languages?.length) return navigator.languages;
  return navigator.language ? [navigator.language] : [];
};

const isAuto = (setting: string | undefined) =>
  !setting || setting.trim().toLowerCase() === 'auto';

/** The first of `languages` the widget supports, or null. */
const firstSupported = (languages: readonly string[]) => {
  for (const language of languages) {
    const match = matchLocale(language);
    if (match) return match;
  }
  return null;
};

/**
 * The locale to show. `auto` (or nothing) takes the first of `languages`
 * the widget supports; an explicit code is matched the same way. Anything
 * unsupported is English.
 */
export const resolveLocale = (
  setting: string | undefined,
  languages: readonly string[] = browserLanguages(),
): SupportedLocale =>
  (isAuto(setting)
    ? firstSupported(languages)
    : matchLocale(setting as string)) ?? 'en';

/**
 * The language to recognise speech in: the visitor's own tag when it maps to
 * the UI locale, so `en-GB` keeps its region; otherwise the locale code.
 * Under `auto` with no supported browser language (an Italian visitor sees
 * English text), speech is still recognised in the browser's language.
 */
export const speechLanguage = (
  setting: string | undefined,
  languages: readonly string[] = browserLanguages(),
  browserLanguage: string | undefined = typeof navigator === 'undefined'
    ? undefined
    : navigator.language,
): string => {
  if (isAuto(setting) && !firstSupported(languages) && browserLanguage)
    return browserLanguage;
  const locale = resolveLocale(setting, languages);
  return (
    languages.find((language) => matchLocale(language) === locale) ?? locale
  );
};

/** A locale's catalogue with the host's overrides on top. Blank overrides are kept. */
export const buildMessages = (
  locale: SupportedLocale,
  overrides?: Partial<Messages>,
): Messages => {
  const messages: Messages = { ...en, ...CATALOGS[locale] };
  if (!overrides || typeof overrides !== 'object') return messages;
  for (const [key, value] of Object.entries(overrides)) {
    if (typeof value === 'string')
      (messages as Record<string, string>)[key] = value;
  }
  return messages;
};

export type MessageValues = Record<string, string | number>;

/** Fills `{name}` placeholders; unknown names are left as written. */
export const interpolate = (template: string, values?: MessageValues) =>
  values
    ? template.replace(/\{(\w+)\}/g, (match, name: string) =>
        Object.prototype.hasOwnProperty.call(values, name)
          ? String(values[name])
          : match,
      )
    : template;

/** The plural form of `key` for `count` in `locale`, falling back to `_other`. */
export const pluralMessage = (
  messages: Messages,
  locale: SupportedLocale,
  key: PluralKey,
  count: number,
): string => {
  const table = messages as Record<string, string | undefined>;
  let category = 'other';
  try {
    category = new Intl.PluralRules(locale).select(count);
  } catch {
    // Very old engines have no PluralRules; `_other` still reads.
  }
  return table[`${key}_${category}`] ?? table[`${key}_other`] ?? '';
};
