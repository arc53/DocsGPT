import React from 'react';
import { useSelector, useDispatch } from 'react-redux';
import Prompts from './Prompts';
import { useDarkTheme } from '../hooks';
import { useTranslation } from 'react-i18next';
import Dropdown from '../components/Dropdown';
import {
  selectPrompt,
  setPrompt,
  setChunks,
  selectChunks,
  setTokenLimit,
  selectTokenLimit,
  setModalStateDeleteConv,
} from '../preferences/preferenceSlice';

const apiHost = import.meta.env.VITE_API_HOST || 'https://docsapi.arc53.com';

const General: React.FC = () => {
  const {
    t,
    i18n: { changeLanguage, language },
  } = useTranslation();
  const themes = ['Light', 'Dark'];

  const languageOptions = [
    {
      label: 'English',
      value: 'en',
    },
    {
      label: 'Spanish',
      value: 'es',
    },
    {
      label: 'Japanese',
      value: 'jp',
    },
    {
      label: 'Mandarin',
      value: 'zh',
    },
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
    const fetchPrompts = async () => {
      try {
        const response = await fetch(`${apiHost}/api/get_prompts`);
        if (!response.ok) {
          throw new Error('Failed to fetch prompts');
        }
        const promptsData = await response.json();
        setPrompts(promptsData);
      } catch (error) {
        console.error(error);
      }
    };
    fetchPrompts();
  }, []);

  React.useEffect(() => {
    localStorage.setItem('docsgpt-locale', selectedLanguage?.value as string);
    changeLanguage(selectedLanguage?.value);
  }, [selectedLanguage, changeLanguage]);

  return (
    <div className="mt-[59px]">
      <div className="mb-5">
        <p className="font-bold text-jet dark:text-bright-gray">
          {t('settings.general.selectTheme')}
        </p>
        <Dropdown
          options={themes}
          selectedValue={selectedTheme}
          onSelect={(option: string) => {
            setSelectedTheme(option);
            option !== selectedTheme && toggleTheme();
          }}
          size="w-56"
          rounded="3xl"
          border="border"
        />
      </div>
      <div className="mb-5">
        <p className="mb-2 font-bold text-jet dark:text-bright-gray">
          {t('settings.general.selectLanguage')}
        </p>
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
        <p className="font-bold text-jet dark:text-bright-gray">
          {t('settings.general.chunks')}
        </p>
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
        <p className="mb-2 font-bold text-jet dark:text-bright-gray">
          {t('settings.general.convHistory')}
        </p>
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
          apiHost={apiHost}
        />
      </div>
      <div className="w-56">
        <p className="font-bold text-jet dark:text-bright-gray">
          {t('settings.general.deleteAllLabel')}
        </p>
        <button
          className="mt-2 flex w-full cursor-pointer items-center justify-between rounded-3xl  border border-solid border-red-500 px-5 py-3 text-red-500 hover:bg-red-500 hover:text-white"
          onClick={() => dispatch(setModalStateDeleteConv('ACTIVE'))}
        >
          <span className="overflow-hidden text-ellipsis ">
            {t('settings.general.deleteAllBtn')}
          </span>
        </button>
      </div>
    </div>
  );
};

export default General;
