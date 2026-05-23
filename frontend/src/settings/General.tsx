import React from 'react';
import { useTranslation } from 'react-i18next';
import { useDispatch, useSelector } from 'react-redux';

import { Button } from '../components/ui/button';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '../components/ui/select';
import { useDarkTheme } from '../hooks';
import {
  selectChunks,
  selectPrompt,
  selectPrompts,
  setChunks,
  setModalStateDeleteConv,
  setPrompt,
  setPrompts,
} from '../preferences/preferenceSlice';
import Prompts from './Prompts';

export default function General() {
  const {
    t,
    i18n: { changeLanguage },
  } = useTranslation();
  const themes = [
    { value: 'Light', label: t('settings.general.light') },
    { value: 'Dark', label: t('settings.general.dark') },
  ];

  const languageOptions = [
    { label: 'English', value: 'en' },
    { label: 'Deutsch', value: 'de' },
    { label: 'Español', value: 'es' },
    { label: '日本語', value: 'jp' },
    { label: '普通话', value: 'zh' },
    { label: '繁體中文（臺灣）', value: 'zhTW' },
    { label: 'Русский', value: 'ru' },
  ];
  const chunks = ['0', '2', '4', '6', '8', '10'];
  const prompts = useSelector(selectPrompts);
  const selectedChunks = useSelector(selectChunks);
  const [isDarkTheme, toggleTheme] = useDarkTheme();
  const [selectedTheme, setSelectedTheme] = React.useState(
    isDarkTheme ? 'Dark' : 'Light',
  );
  const dispatch = useDispatch();
  const locale = localStorage.getItem('docsgpt-locale');
  const [selectedLanguage, setSelectedLanguage] = React.useState(
    locale
      ? languageOptions.find((option) => option.value === locale)
      : languageOptions[0],
  );
  const selectedPrompt = useSelector(selectPrompt);

  React.useEffect(() => {
    localStorage.setItem('docsgpt-locale', selectedLanguage?.value as string);
    changeLanguage(selectedLanguage?.value);
  }, [selectedLanguage, changeLanguage]);
  return (
    <div className="mt-8 flex flex-col gap-6">
      <div className="flex flex-col gap-4">
        <Prompts
          prompts={prompts}
          selectedPrompt={selectedPrompt}
          onSelectPrompt={(name, id, type) =>
            dispatch(setPrompt({ name: name, id: id, type: type }))
          }
          setPrompts={(newPrompts) => dispatch(setPrompts(newPrompts))}
        />
      </div>
      <div className="flex flex-col gap-4">
        <label className="text-foreground dark:text-foreground text-base font-medium">
          {t('settings.general.chunks')}
        </label>
        <Select
          value={selectedChunks}
          onValueChange={(value) => dispatch(setChunks(value))}
        >
          <SelectTrigger className="w-56 rounded-3xl px-5 py-3" size="lg">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {chunks.map((c) => (
              <SelectItem key={c} value={c}>
                {c}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
      <div className="flex flex-col gap-4">
        <label className="text-foreground dark:text-foreground text-base font-medium">
          {t('settings.general.selectTheme')}
        </label>
        <Select
          value={selectedTheme}
          onValueChange={(value) => {
            setSelectedTheme(value);
            value !== selectedTheme && toggleTheme();
          }}
        >
          <SelectTrigger className="w-56 rounded-3xl px-5 py-3" size="lg">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {themes.map((theme) => (
              <SelectItem key={theme.value} value={theme.value}>
                {theme.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
      <div className="flex flex-col gap-4">
        <label className="text-foreground dark:text-foreground text-base font-medium">
          {t('settings.general.selectLanguage')}
        </label>
        <Select
          value={selectedLanguage?.value}
          onValueChange={(value) => {
            const opt = languageOptions.find((o) => o.value === value);
            if (opt) setSelectedLanguage(opt);
          }}
        >
          <SelectTrigger className="w-56 rounded-3xl px-5 py-3" size="lg">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {languageOptions.map((opt) => (
              <SelectItem key={opt.value} value={opt.value}>
                {opt.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
      <hr className="border-border dark:border-border my-4 w-[calc(min(665px,100%))] border-t" />
      <div className="flex flex-col gap-2">
        <Button
          type="button"
          variant="destructive-outline"
          title={t('settings.general.deleteAllLabel')}
          className="w-fit rounded-3xl px-5 py-3 tracking-[0.015em] hover:font-bold hover:tracking-normal"
          onClick={() => dispatch(setModalStateDeleteConv('ACTIVE'))}
        >
          {t('settings.general.deleteAllBtn')}
        </Button>
      </div>
    </div>
  );
}
