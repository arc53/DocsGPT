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
      order: ['localStorage', 'navigator'], // checks localStorage for existing lang before browser's
      caches: ['localStorage'], //stores detected lang to localStorage with i18nextLng key
      lookupLocalStorage: 'docsgpt-locale', //using docsgpt-locale as the custom key for storing and retrieving the lang rather than the default `i18nextLng`
    },
  });

const savedLocale = localStorage.getItem('docsgpt-locale') ?? i18n.language;
i18n.changeLanguage(savedLocale);

export default i18n;
