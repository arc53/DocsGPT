import i18n from 'i18next';
import { initReactI18next } from 'react-i18next';
import LanguageDetector from 'i18next-browser-languagedetector';

import en from './en.json'; //English
import es from './es.json'; //Spanish
import jp from './jp.json'; //Japanese
import zh from './zh.json'; //Mandarin

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
    },
    fallbackLng: 'en',
    detection: {
      order: ['localStorage', 'navigator'],
      caches: ['localStorage'],
      lookupLocalStorage: 'docsgpt-locale',
    },
  });

i18n.changeLanguage(i18n.language);

export default i18n;
