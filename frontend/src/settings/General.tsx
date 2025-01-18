import React from 'react';
import { useTranslation } from 'react-i18next';
import { useDispatch, useSelector } from 'react-redux';

import userService from '../api/services/userService';
import Dropdown from '../components/Dropdown';
import { useDarkTheme } from '../hooks';
import {
  selectChunks,
  selectPrompt,
  selectTokenLimit,
  setChunks,
  setModalStateDeleteConv,
  setPrompt,
  setTokenLimit,
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
    { label: 'Español', value: 'es' },
    { label: '日本語', value: 'jp' },
    { label: '普通话', value: 'zh' },
    { label: '繁體中文（臺灣）', value: 'zhTW' },
    { label: 'Русский', value: 'ru' },
  ];
  const chunks = ['0', '2', '4', '6', '8', '10'];
  const token_limits = new Map([
    [0, t('settings.general.none')],
    [100, t('settings.general.low')],
    [1000, t('settings.general.medium')],
    [2000, t('settings.general.default')],
    [4000, t('settings.general.high')],
    [1e9, t('settings.general.unlimited')],
  ]);
  const [prompts, setPrompts] = React.useState<
    { name: string; id: string; type: string }[]
  >([]);
  const selectedChunks = useSelector(selectChunks);
  const selectedTokenLimit = useSelector(selectTokenLimit);
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
    const handleFetchPrompts = async () => {
      try {
        const response = await userService.getPrompts();
        if (!response.ok) {
          throw new Error('Failed to fetch prompts');
        }
        const promptsData = await response.json();
        setPrompts(promptsData);
      } catch (error) {
        console.error(error);
      }
    };
    handleFetchPrompts();
  }, []);

  React.useEffect(() => {
    localStorage.setItem('docsgpt-locale', selectedLanguage?.value as string);
    changeLanguage(selectedLanguage?.value);
  }, [selectedLanguage, changeLanguage]);
  return (
    <div className="mt-12">
      <div className="mb-5">
        <label className="block font-bold text-jet dark:text-bright-gray">
          {t('settings.general.selectTheme')}
        </label>
        <Dropdown
          options={themes}
          selectedValue={
            themes.find((theme) => theme.value === selectedTheme) || null
          }
          onSelect={(option: { value: string; label: string }) => {
            setSelectedTheme(option.value);
            option.value !== selectedTheme && toggleTheme();
          }}
          size="w-56"
          rounded="3xl"
          border="border"
        />
      </div>
      <div className="mb-5">
        <label className="block mb-2 font-bold text-jet dark:text-bright-gray">
          {t('settings.general.selectLanguage')}
        </label>
        <Dropdown
          options={languageOptions.filter(
            (languageOption) =>
              languageOption.value !== selectedLanguage?.value,
          )}
          selectedValue={selectedLanguage ?? languageOptions[0]}
          onSelect={(selectedOption: { label: string; value: string }) => {
            setSelectedLanguage(selectedOption);
          }}
          size="w-56"
          rounded="3xl"
          border="border"
        />
      </div>
      <div className="mb-5">
        <label className="block font-bold text-jet dark:text-bright-gray">
          {t('settings.general.chunks')}
        </label>
        <Dropdown
          options={chunks}
          selectedValue={selectedChunks}
          onSelect={(value: string) => dispatch(setChunks(value))}
          size="w-56"
          rounded="3xl"
          border="border"
        />
      </div>
      <div className="mb-5">
        <label className="mb-2 block font-bold text-jet dark:text-bright-gray">
          {t('settings.general.convHistory')}
        </label>
        <Dropdown
          options={Array.from(token_limits, ([value, desc]) => ({
            value: value,
            description: desc,
          }))}
          selectedValue={{
            value: selectedTokenLimit,
            description: token_limits.get(selectedTokenLimit) as string,
          }}
          onSelect={({
            value,
            description,
          }: {
            value: number;
            description: string;
          }) => dispatch(setTokenLimit(value))}
          size="w-56"
          rounded="3xl"
          border="border"
        />
      </div>
      <div className="mb-5">
        <Prompts
          prompts={prompts}
          selectedPrompt={selectedPrompt}
          onSelectPrompt={(name, id, type) =>
            dispatch(setPrompt({ name: name, id: id, type: type }))
          }
          setPrompts={setPrompts}
        />
      </div>
      <div className="w-56">
        <label className="block font-bold text-jet dark:text-bright-gray">
          {t('settings.general.deleteAllLabel')}
        </label>
        <button
          className="mt-2 flex w-full cursor-pointer items-center justify-between rounded-3xl border border-solid border-red-700 px-5 py-3 text-red-700 transition-colors hover:bg-red-700 hover:text-white dark:border-red-600 dark:text-red-600 dark:hover:bg-red-600 dark:hover:text-white"
          onClick={() => dispatch(setModalStateDeleteConv('ACTIVE'))}
        >
          {t('settings.general.deleteAllBtn')}
        </button>
      </div>
    </div>
  );
}
