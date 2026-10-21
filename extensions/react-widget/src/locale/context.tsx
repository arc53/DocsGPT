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
  messages: Messages;
  /** A message with its `{name}` placeholders filled. */
  t: (key: keyof Messages, values?: MessageValues) => string;
  /** The plural form for `count`, which also fills `{count}`. */
  plural: (key: PluralKey, count: number, values?: MessageValues) => string;
}

const createI18n = (
  locale: SupportedLocale,
  translations?: Partial<Messages>,
): I18n => {
  const messages = buildMessages(locale, translations);
  return {
    locale,
    messages,
    t: (key, values) => interpolate(messages[key] ?? '', values),
    plural: (key, count, values) =>
      interpolate(pluralMessage(messages, locale, key, count), {
        count,
        ...values,
      }),
  };
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
  const resolved = React.useMemo(() => resolveLocale(locale), [locale]);
  // Hosts often pass an inline object; compare by content, not identity, so
  // memoised children keep their labels.
  const overridesKey = translations ? JSON.stringify(translations) : '';
  const value = React.useMemo(
    () => createI18n(resolved, translations),
    [resolved, overridesKey],
  );
  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
};

/** The widget's messages in the resolved locale. */
export const useMessages = (): I18n => React.useContext(I18nContext);
