import React from 'react';

import {
  buildMessages,
  interpolate,
  pluralMessage,
  resolveLocale,
  type MessageValues,
  type Messages,
  type PluralKey,
  type SupportedLocale,
} from './index';

export interface I18n {
  /** The resolved locale, for `lang` and `Intl` formatters. */
  locale: SupportedLocale;
  /** The `locale` prop as the host set it; `auto` when unset. */
  setting: string;
  messages: Messages;
  /** A message with its `{name}` placeholders filled. */
  t: (key: keyof Messages, values?: MessageValues) => string;
  /** The plural form for `count`, which also fills `{count}`. */
  plural: (key: PluralKey, count: number, values?: MessageValues) => string;
}

const createI18n = (
  locale: SupportedLocale,
  setting = 'auto',
  translations?: Partial<Messages>,
): I18n => {
  const messages = buildMessages(locale, translations);
  return {
    locale,
    setting,
    messages,
    t: (key, values) => interpolate(messages[key] ?? '', values),
    plural: (key, count, values) =>
      interpolate(pluralMessage(messages, locale, key, count), {
        count,
        ...values,
      }),
  };
};

const subscribeToLanguages = (onChange: () => void) => {
  if (typeof window === 'undefined') return () => undefined;
  window.addEventListener('languagechange', onChange);
  return () => window.removeEventListener('languagechange', onChange);
};

// English without a provider, so an inner component never renders blank.
const I18nContext = React.createContext<I18n>(createI18n('en'));

/**
 * Resolves `locale` (`'auto'` by default) and shares the messages, with the
 * host's `translations` on top, with everything rendered inside.
 */
export const I18nProvider = ({
  locale,
  translations,
  children,
}: {
  locale?: string;
  translations?: Partial<Messages>;
  children: React.ReactNode;
}) => {
  // The server can't see the visitor's languages, so it renders English and
  // the browser's choice lands after hydration, without a mismatch.
  const resolved = React.useSyncExternalStore(
    subscribeToLanguages,
    () => resolveLocale(locale),
    () => resolveLocale(locale, []),
  );
  // Hosts often pass an inline object; compare by content, not identity, so
  // memoised children keep their labels.
  const overridesKey = translations ? JSON.stringify(translations) : '';
  const value = React.useMemo(
    () => createI18n(resolved, locale, translations),
    [resolved, locale, overridesKey],
  );
  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
};

/** The widget's messages in the resolved locale. */
export const useMessages = (): I18n => React.useContext(I18nContext);
