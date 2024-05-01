import React from 'react';
import { useSelector, useDispatch } from 'react-redux';
import Prompts from './Prompts';
import { useDarkTheme } from '../hooks';
import Dropdown from '../components/Dropdown';
import {
  selectPrompt,
  setPrompt,
  setChunks,
  selectChunks,
  setModalStateDeleteConv,
} from '../preferences/preferenceSlice';

const apiHost = import.meta.env.VITE_API_HOST || 'https://docsapi.arc53.com';

const General: React.FC = () => {
  const themes = ['Light', 'Dark'];
  const languages = ['English'];
  const chunks = ['0', '2', '4', '6', '8', '10'];
  const [prompts, setPrompts] = React.useState<
    { name: string; id: string; type: string }[]
  >([]);
  const selectedChunks = useSelector(selectChunks);
  const [isDarkTheme, toggleTheme] = useDarkTheme();
  const [selectedTheme, setSelectedTheme] = React.useState(
    isDarkTheme ? 'Dark' : 'Light',
  );
  const dispatch = useDispatch();
  const [selectedLanguage, setSelectedLanguage] = React.useState(languages[0]);
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

  return (
    <div className="mt-[59px]">
      <div className="mb-4">
        <p className="font-bold text-jet dark:text-bright-gray">Select Theme</p>
        <Dropdown
          options={themes}
          selectedValue={selectedTheme}
          onSelect={(option: string) => {
            setSelectedTheme(option);
            option !== selectedTheme && toggleTheme();
          }}
          size="w-56"
          rounded="3xl"
        />
      </div>
      <div className="mb-4">
        <p className="font-bold text-jet dark:text-bright-gray">
          Select Language
        </p>
        <Dropdown
          options={languages}
          selectedValue={selectedLanguage}
          onSelect={setSelectedLanguage}
          size="w-56"
          rounded="3xl"
        />
      </div>
      <div className="mb-4">
        <p className="font-bold text-jet dark:text-bright-gray">
          Chunks processed per query
        </p>
        <Dropdown
          options={chunks}
          selectedValue={selectedChunks}
          onSelect={(value: string) => dispatch(setChunks(value))}
          size="w-56"
          rounded="3xl"
        />
      </div>
      <div>
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
      <div className="w-55 w-56">
        <p className="font-bold text-jet dark:text-bright-gray">
          Delete all conversations
        </p>
        <button
          className="mt-2 flex w-full cursor-pointer items-center justify-between rounded-3xl  border-2 border-solid border-purple-30 bg-white  px-5 py-3 text-purple-30 hover:bg-purple-30 hover:text-white dark:border-chinese-silver dark:bg-transparent"
          onClick={() => dispatch(setModalStateDeleteConv('ACTIVE'))}
        >
          <span className="overflow-hidden text-ellipsis dark:text-bright-gray">
            Delete
          </span>
        </button>
      </div>
    </div>
  );
};

export default General;
