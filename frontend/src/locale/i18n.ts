import i18n from 'i18next';
import { initReactI18next } from 'react-i18next';
import LanguageDetector from 'i18next-browser-languagedetector';

import en from './en.json'; //English
import es from './es.json'; //Spanish
import jp from './jp.json'; //Japanese
import zh from './zh.json'; //Mandarin
import zhTW from './zh-TW.json'; //Traditional Chinese
import ru from './ru.json'; //Russian
import de from './de.json'; //German

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
      jp: {
        translation: jp,
      },
      zh: {
        translation: zh,
      },
      zhTW: {
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
    supportedLngs: ['en', 'es', 'jp', 'zh', 'zhTW', 'ru', 'de'],
    detection: {
      order: ['localStorage', 'navigator'],
      caches: ['localStorage'],
      lookupLocalStorage: 'docsgpt-locale',
    },
  });

i18n.changeLanguage(i18n.language);

export default i18n;
