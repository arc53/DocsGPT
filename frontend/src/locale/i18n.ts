import i18n from 'i18next';
import { initReactI18next } from 'react-i18next';
import LanguageDetector from 'i18next-browser-languagedetector';

import { intlLocale } from '../utils/dateTimeUtils';

import en from './en.json'; //English
import es from './es.json'; //Spanish
import fr from './fr.json'; //French
import ja from './jp.json'; //Japanese
import zh from './zh.json'; //Mandarin
import zhTW from './zh-TW.json'; //Traditional Chinese
import ru from './ru.json'; //Russian
import de from './de.json'; //German

// Codes older builds stored for the UI language. They aren't BCP 47 tags, so
// browsers never matched them and Intl gave them English plural rules.
const LEGACY_CODES: Record<string, string> = { jp: 'ja', zhTW: 'zh-TW' };

// A stored legacy code is read as its tag; a Traditional Chinese browser
// (zh-HK, zh-MO, zh-Hant…) reads as zh-TW rather than reducing to zh.
const toAppLanguage = (lng: string): string =>
  LEGACY_CODES[lng] ?? (/^zh-(hant|hk|mo)\b/i.test(lng) ? 'zh-TW' : lng);

i18n
  .use(LanguageDetector)
  .use(initReactI18next)
  .init({
    resources: {
      en: {
        translation: en,
      },
      es: {
        translation: es,
      },
      fr: {
        translation: fr,
      },
      ja: {
        translation: ja,
      },
      zh: {
        translation: zh,
      },
      'zh-TW': {
        translation: zhTW,
      },
      ru: {
        translation: ru,
      },
      de: {
        translation: de,
      },
    },
    fallbackLng: 'en',
    // Detection skips codes outside this list (a stored "undefined" from old
    // builds) and maps a region to its language (ru-RU -> ru); the detector
    // then caches the result over the stored value. A new language goes here
    // as well as in `resources`.
    supportedLngs: ['en', 'es', 'fr', 'ja', 'zh', 'zh-TW', 'ru', 'de'],
    detection: {
      order: ['localStorage', 'navigator'],
      caches: ['localStorage'],
      lookupLocalStorage: 'docsgpt-locale',
      // The converted code is cached over the stored one.
      convertDetectedLanguage: toAppLanguage,
    },
  });

i18n.changeLanguage(i18n.language);

// Declare the UI language on <html>. A Spanish page marked lang="en" makes the
// browser offer to translate it, and the translator's DOM rewrites break
// React's next commit (removeChild / insertBefore NotFoundError).
const syncHtmlLang = (lng: string) => {
  if (typeof document !== 'undefined') {
    document.documentElement.lang = intlLocale(lng);
  }
};
i18n.on('languageChanged', syncHtmlLang);
syncHtmlLang(i18n.language);

export default i18n;
