import React, { useState } from 'react';
import Arrow2 from './assets/dropdown-arrow.svg';

const Setting = () => {
  const list = ['General', 'Prompts', 'Documents', 'Widgets'];
  const [active, setActive] = useState('General');
  const returnActiveTabs = (): JSX.Element => {
    if (active === 'General') return <General />;
    else if (active === 'Prompts') return <Prompts />;
    else if (active === 'Documents') return <Documents />;
    else if (active === 'Widgets') return <Widgets />;
    else return <></>;
  };
  return (
    <div className="pt-20 pl-2 md:p-12">
      <p className="text-2xl font-bold text-eerie-black">Settings</p>
      <div className="mt-4 flex flex-row overflow-x-scroll md:overflow-x-hidden">
        {list.map((item, index) => (
          <div
            key={index}
            className={`my-auto mr-6 mb-5 flex h-9 cursor-pointer items-center gap-4 rounded-3xl px-4 font-bold text-purple-30 hover:bg-purple-3000 ${
              active === item ? 'bg-purple-3000' : ''
            }`}
            onClick={() => setActive(item)}
          >
            {item}
          </div>
        ))}
      </div>
      {returnActiveTabs()}
    </div>
  );
};

const General = () => {
  const [theme, setTheme] = useState('Light');
  const [isThemeListOpen, setIsThemeListOpen] = useState(false);
  const themes = ['Light', 'Dark'];
  const [language, setLanguage] = useState('English');
  const languages = ['English', 'French'];
  const [isLanguageListOpen, setIsLanguageListOpen] = useState(false);
  return (
    <>
      <div className="mt-10 w-80">
        <p className="font-bold text-jet">Select Theme</p>
        <div className="relative my-4 flex gap-2 px-2">
          <div
            className="flex h-12 w-full cursor-pointer justify-between rounded-3xl border-2 bg-white"
            onClick={() => setIsThemeListOpen(!isThemeListOpen)}
          >
            {theme && (
              <p className="my-3 mx-4 overflow-hidden text-ellipsis">{theme}</p>
            )}
            <img
              src={Arrow2}
              alt="arrow"
              className={`${
                !isThemeListOpen ? 'rotate-0' : 'rotate-180'
              } ml-auto mr-3 w-3 transition-all`}
            />
          </div>
          {isThemeListOpen && (
            <div
              className="absolute top-12 left-0 right-6 ml-2 mr-4 max-h-52 overflow-y-scroll bg-white shadow-lg"
              style={{ zIndex: 100 }}
            >
              {themes.map((item, index) => (
                <div
                  key={index}
                  onClick={() => {
                    setTheme(item);
                    setIsThemeListOpen(false);
                  }}
                  className="flex h-10 w-full cursor-pointer items-center justify-between border-x-2 border-b-2 hover:bg-gray-100"
                >
                  <p className="ml-5 flex-1 overflow-hidden overflow-ellipsis whitespace-nowrap py-3">
                    {item}
                  </p>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
      <div className="mt-12 w-80">
        <p className="font-bold text-jet">Select Language</p>
        <div className="relative my-4 flex gap-2 px-2">
          <div
            className="flex h-12 w-full cursor-pointer justify-between rounded-3xl border-2 bg-white"
            onClick={() => setIsLanguageListOpen(!isLanguageListOpen)}
          >
            {language && (
              <p className="my-3 mx-4 overflow-hidden text-ellipsis whitespace-nowrap">
                {language}
              </p>
            )}
            <img
              src={Arrow2}
              alt="arrow"
              className={`${
                !isLanguageListOpen ? 'rotate-0' : 'rotate-180'
              } ml-auto mr-3 w-3 transition-all`}
            />
          </div>
          {isLanguageListOpen && (
            <div className="absolute top-12 left-0 right-6 ml-2 mr-4 max-h-52 overflow-y-scroll bg-white shadow-lg">
              {languages.map((item, index) => (
                <div
                  key={index}
                  onClick={() => {
                    setLanguage(item);
                    setIsLanguageListOpen(false);
                  }}
                  className="flex h-10 w-full cursor-pointer items-center justify-between border-x-2 border-b-2 hover:bg-gray-100"
                >
                  <p className="ml-5 flex-1 overflow-hidden overflow-ellipsis whitespace-nowrap py-3">
                    {item}
                  </p>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </>
  );
};
const Prompts = () => {
  return <div>This is prompts</div>;
};
const Documents = () => {
  return <div>This is Documents</div>;
};
const Widgets = () => {
  return <div>This is widgets</div>;
};
export default Setting;
