'use client';

import { useState } from 'react';
import Globe from '../assets/globe.svg';
import Profile from '../assets/profie.png';
import Logo from '../assets/Logo.svg';
import L2C1 from '../assets/file_upload.svg';
import L2C2 from '../assets/website_collect.svg';
import Back from '../assets/Back.svg';
import UploadFromDeviceForm from './UploadFromDeviceForm';
import CollectFromWebsiteForm from './CollectFromWebsiteForm';
import { useDarkTheme } from '../hooks';

interface LevelIndicatorProps {
  currentLevel: number;
  indicatorLevel: number;
}

const LevelIndicator: React.FC<LevelIndicatorProps> = ({
  currentLevel,
  indicatorLevel,
}) => {
  const isActive = currentLevel === indicatorLevel;
  const isPast = currentLevel > indicatorLevel;

  return (
    <div className="flex flex-col items-center mx-2 transition-transform duration-500 ease-in-out">
      <div
        className={`h-2 rounded-full transition-all duration-500 ease-in-out
          ${
            isActive
              ? 'w-24 h-2 bg-[#7d54d1]'
              : isPast
                ? 'w-4 bg-gray-200'
                : 'w-4 bg-gray-200'
          }`}
      />
    </div>
  );
};

export default function Onboarding() {
  const [language] = useState<string>('EN');
  const [level, setLevel] = useState<number>(1);
  const [selectedCard, setSelectedCard] = useState<number | null>(null);
  const [isLoading, setIsLoading] = useState<boolean>(false);
  const [progress, setProgress] = useState<number>(0);
  const [isFinalPage, setIsFinalPage] = useState<boolean>(false);
  const [isTrainingComplete, setIsTrainingComplete] = useState<boolean>(false);
  const [isDarkTheme, toggleTheme] = useDarkTheme();

  const handleLevelUp = () => {
    if (level < 3) {
      setLevel((prevLevel) => prevLevel + 1);
    }
  };

  const handleLevelDown = () => {
    if (level > 1) {
      setLevel((prevLevel) => prevLevel - 1);
    }
    setSelectedCard(null);
  };

  const handleCardSelect = (card: number) => {
    setSelectedCard(card);
  };

  const handleFinalButtonClick = () => {
    setIsLoading(true);
    setIsFinalPage(true);

    const updateProgress = (current: number) => {
      if (current >= 100) {
        setProgress(100);
        setIsLoading(false);
        setIsTrainingComplete(true);
        return;
      }
      setProgress(current);
      setTimeout(() => updateProgress(current + 10), 400);
    };

    updateProgress(0);
  };

  const getGradientForLevel = (level: number): string => {
    switch (level) {
      case 1:
        return `relative bg-gradient-to-br from-green-200 via-white to-white dark:from-[#222327] dark:to-black`; // Light greenish tone
      case 2:
        return 'bg-gradient-to-br from-pink-300 via-white to-white  dark:from-[#222327] dark:to-black'; // Light pink tone
      case 3:
        return `bg-gradient-to-br  ${isTrainingComplete == true ? 'from-green-200 ' : 'from-orange-100 '} via-white to-white dark:from-[#222327] dark:to-black`; // Light orange tone
      default:
        return 'bg-white dark:bg-gray-900'; // Default light and dark backgrounds
    }
  };

  const renderContentForLevel = (level: number) => {
    if (isFinalPage) {
      return (
        <div className="flex flex-col items-center justify-center h-full w-full ">
          <img
            src={Logo}
            alt="Logo"
            className="w-16 h-16 sm:w-20 sm:h-20 opacity-0 animate-fadeInSlideUp"
          />
          {isTrainingComplete == true ? (
            <div className="opacity-0 animate-fadeInSlideUp w-4/5 md:w-3/5 lg:w-2/5">
              <h1 className="font-bold text-2xl opacity-0 animate-fadeInSlideUp  md:text-3xl lg:text-4xl  text-center mt-4 dark:text-white">
                Training Complete !
              </h1>
            </div>
          ) : (
            <>
              {' '}
              {/* Heading */}
              <h1 className="font-bold text-2xl opacity-0 animate-fadeInSlideUp  md:text-3xl lg:text-4xl w-4/5 md:w-3/5 lg:w-2/5 text-center mt-4 dark:text-white">
                Training is in progress...
              </h1>
              {/* Subheading */}
              <h4 className="text-sm sm:text-base opacity-0 animate-fadeInSlideUp md:text-lg lg:text-xl w-5/6 md:w-3/5 lg:w-1/3 font-normal text-center mt-2 md:mt-4 dark:text-gray-300">
                This may take several minutes
              </h4>
            </>
          )}

          <div className="mt-16 mb-12 flex flex-col items-center transition-all duration-400 ease-in-out opacity-0 animate-fadeInSlideUp">
            <div className="relative w-60 h-60 flex items-center justify-center">
              {/* New Progress Bar */}
              <div className="relative w-40 h-40 rounded-full">
                <div className="absolute inset-0 rounded-full shadow-[0_0_10px_2px_rgba(0,0,0,0.3)_inset] dark:shadow-[0_0_10px_2px_rgba(0,0,0,0.3)_inset]"></div>
                <div
                  className={`absolute inset-0 rounded-full ${
                    progress === 100
                      ? 'shadow-xl shadow-lime-300/50 dark:shadow-lime-300/50 '
                      : 'shadow-[0_4px_0_#7D54D1] dark:shadow-[0_4px_0_#7D54D1]'
                  }`}
                  style={{
                    animation: `${progress === 100 ? 'none' : 'rotate 2s linear infinite'}`,
                  }}
                ></div>
                <div className="absolute inset-0 flex items-center justify-center">
                  <span className="text-2xl font-bold dark:text-white text-gray-800">
                    {progress}%
                  </span>
                </div>
              </div>

              {/* Keyframes for rotation animation */}
              <style>{`
      @keyframes rotate {
        0% {
          transform: rotate(0deg);
        }
        100% {
          transform: rotate(360deg);
        }
      }
    `}</style>
            </div>
          </div>

          {!isLoading && (
            <button className="mt-6 px-8 py-3 bg-purple-600 text-white rounded-lg  hover:bg-purple-700 shadow-[0_4px_8px_rgba(128,90,213,0.3)] transition-all duration-400 ease-in-out opacity-0 animate-fadeInSlideUp">
              Start Chatting
            </button>
          )}
          {isLoading && (
            <button className="mt-6 px-8 py-3 bg-purple-300 text-white rounded-lg disabled:cursor-not-allowed  shadow-[0_4px_8px_rgba(128,90,213,0.3)] transition-all duration-400 ease-in-out opacity-0 animate-fadeInSlideUp ">
              Please wait...
            </button>
          )}
        </div>
      );
    }

    switch (level) {
      case 1:
        return (
          <>
            <div className="flex flex-col items-center transition-opacity duration-1000 ease-out opacity-0 animate-fadeInSlideUp">
              <img
                src={Logo}
                alt="Logo"
                className="w-20 h-20 mb-4 max-sm:w-22 sm:w-24 sm:h-24 md:w-28 md:h-28 lg:w-32 lg:h-32 xl:w-36 xl:h-36 2xl:w-40 2xl:h-40"
              />
              <h1 className="font-bold text-4xl max-sm:text-center sm:text-5xl md:text-6xl dark:text-white">
                Welcome to DocsGPT
              </h1>
              <p className="text-base sm:text-lg md:text-xl mt-6 dark:text-gray-300">
                Your technical documentation assistant.
              </p>
            </div>
          </>
        );
      case 2:
        return (
          <div className="flex w-full flex-col items-center transition-all duration-500 ease-in-out opacity-0 animate-fadeInSlideUp max-sm:mt-24">
            {/* Logo */}
            <img
              src={Logo}
              alt="Logo"
              className="w-16 h-16 sm:w-20 sm:h-20 md:w-22 md:h-22"
            />

            {/* Heading */}
            <h1 className="font-bold text-xl sm:text-2xl md:text-3xl lg:text-4xl w-4/5 md:w-3/5 xl:w-1/3 2xl:w-1/4 text-center mt-3 dark:text-white">
              Upload from device or from web?
            </h1>

            {/* Subheading */}
            <h4 className="text-sm sm:text-base md:text-lg lg:text-xl w-4/5 sm:w-2/5 md:w-[40%] xl:w-1/4 2xl:w-1/5  font-normal text-center mt-2 md:mt-4 dark:text-gray-300">
              You can choose how to add your first document to DocsGPT
            </h4>

            {/* Card Container */}
            <div className="flex flex-col sm:flex-row gap-6 sm:gap-8 mt-6">
              {/* Card 1 */}
              <div className="flex flex-col items-center ">
                <div
                  className={`p-4 border-2 ${selectedCard === 1 ? 'border-purple-700 shadow-all-sides-hover  dark:shadow-[-20px_35px_50px_-15px_rgba(0,0,0,0.5)]' : 'border-transparent shadow-all-sides hover:shadow-all-sides-hover'} 
                  rounded-xl bg-white dark:bg-gray-800 cursor-pointer transition-all duration-500 ease-in-out`}
                  onClick={() => handleCardSelect(1)}
                >
                  <div className="p-6 sm:p-8 md:p-10 lg:p-12">
                    <img
                      src={L2C1}
                      alt="L1C1"
                      className={`w-8 h-8 sm:w-10 sm:h-10 md:w-12 md:h-12 dark:filter dark:invert transition-transform duration-300 ease-in-out ${selectedCard === 1 ? 'scale-125' : ''}`}
                    />
                  </div>
                </div>
                <h4
                  className={`text-xs sm:text-base md:text-lg w-4/5 md:w-2/3 text-center mt-4 dark:text-gray-200 transition-all duration-500 ease-in-out ${selectedCard === 1 ? 'text-purple-700 ' : ''}`}
                >
                  Upload from device
                </h4>
              </div>

              {/* Card 2 */}
              <div className="flex flex-col items-center ">
                <div
                  className={`p-4 border-2 ${selectedCard === 2 ? 'border-purple-700 shadow-all-sides-hover dark:shadow-[20px_35px_50px_-15px_rgba(0,0,0,0.5)]' : 'border-transparent shadow-all-sides hover:shadow-all-sides-hover'} 
                  rounded-xl bg-white dark:bg-gray-800 cursor-pointer transition-all duration-500 ease-in-out`}
                  onClick={() => handleCardSelect(2)}
                >
                  <div className="p-6 sm:p-8 md:p-10 lg:p-12">
                    <img
                      src={L2C2}
                      alt="L1C2"
                      className={`w-8 h-8 sm:w-10 sm:h-10 md:w-12 md:h-12 dark:filter dark:invert transition-transform duration-300 ease-in-out ${selectedCard === 2 ? 'scale-125' : ''}`}
                    />
                  </div>
                </div>
                <h4
                  className={`text-xs sm:text-base md:text-lg w-4/5 md:w-2/3 text-center mt-4 dark:text-gray-200 transition-all duration-500 ease-in-out ${selectedCard === 2 ? 'text-purple-700' : ''}`}
                >
                  Collect from a website
                </h4>
              </div>
            </div>
          </div>
        );
      case 3:
        return (
          <div className="flex flex-col w-full items-center gap-5 transition-all duration-500 ease-in-out opacity-0 animate-fadeInSlideUp">
            <img
              src={Logo}
              alt="Logo"
              className="w-16 h-16 sm:w-20 sm:h-20 opacity-0 animate-fadeInSlideUp"
            />

            {/* Heading */}
            <h1 className="font-bold text-xl sm:text-2xl md:text-3xl opacity-0 animate-fadeInSlideUp  w-4/5 md:w-3/5 lg:w-2/5 text-center mb-5 dark:text-white">
              Upload new document
            </h1>
            {selectedCard === 1 ? (
              <UploadFromDeviceForm />
            ) : (
              <CollectFromWebsiteForm />
            )}
            {isLoading && (
              <div className="mt-8">
                <div className="w-16 h-16 border-t-4 border-purple-600 rounded-full animate-spin"></div>
                <p className="text-lg mt-2">{progress}%</p>
              </div>
            )}
          </div>
        );
      default:
        return null;
    }
  };

  return (
    <div
      className={`p-4 w-full relative flex flex-col h-screen ${getGradientForLevel(level)}`}
    >
      <div className="absolute inset-0 dark:bg-[url('./assets/bg.svg')] dark:bg-center dark:bg-cover"></div>
      {/* alternate background */}
      {/* <div className="dark:absolute dark:top-1/4 dark:left-1/4 dark:w-96 dark:h-96 dark:bg-blue-600/10 dark:rounded-full dark:blur-2xl dark:transform dark:-translate-x-2/4 dark:-translate-y-1/2"></div>
      <div className="dark:absolute dark:top-1/3 dark:left-1/3 dark:w-96 dark:h-96 dark:bg-green-600/10 dark:rounded-full dark:blur-2xl dark:transform dark:-translate-x-1/3 dark:-translate-y-1/3"></div>
      <div className="dark:absolute dark:top-1/2 dark:left-1/2 dark:w-[500px] dark:h-[500px] dark:bg-orange-700/20 dark:rounded-full dark:blur-3xl dark:transform dark:-translate-x-1/2 dark:-translate-y-1/2"></div> */}

      <div className="flex w-full justify-between items-center lg:items-start">
        {/* Left Section */}
        <div className="flex w-full justify-between items-center lg:items-start">
          {/* Left Section */}
          <div className="flex items-center space-x-2 hover:cursor-pointer z-30">
            <span className="font-normal dark:text-white">{language}</span>
            <img
              src={Globe}
              height={24}
              width={24}
              alt="Globe"
              className=" dark:invert"
              onClick={toggleTheme}
            />
          </div>
        </div>

        {/* Profile Section */}
        <div className="flex-grow"></div>
        <div className="rounded-full flex justify-center items-center w-12 h-12 overflow-hidden bg-red-400">
          <img
            src={Profile}
            alt="Profile"
            className="w-full h-full object-cover"
          />
        </div>
      </div>

      {/* Main content section */}
      <div
        className="flex-grow flex flex-col  justify-center items-center gap-8 -translate-y-20"
        id="here"
      >
        {renderContentForLevel(level)}

        {!isFinalPage && (
          <>
            <div className="flex justify-center mb-2">
              <div className="flex space-x-1">
                {[1, 2, 3].map((num) => (
                  <LevelIndicator
                    key={num}
                    currentLevel={level}
                    indicatorLevel={num}
                  />
                ))}
              </div>
            </div>

            <div className="flex space-x-4">
              {level === 3 && !isLoading && (
                <button
                  onClick={handleLevelDown}
                  className="px-2 py-1 text-gray-500 hover:text-gray-700 text-lg font-medium transition-colors flex items-center"
                >
                  <img src={Back} alt="<" className="mr-2 dark:invert" />
                  <span className="dark:text-gray-400">Back</span>
                </button>
              )}
              <button
                onClick={
                  level === 2 && selectedCard === null
                    ? undefined
                    : level === 3
                      ? handleFinalButtonClick
                      : handleLevelUp
                }
                className={`px-8 py-3 ${level === 2 && selectedCard === null ? 'bg-gray-300 dark:bg-[#7d54d14d] cursor-not-allowed' : 'bg-purple-600 hover:bg-purple-800'} 
                text-white rounded-lg transition-all duration-500 ease-in-out shadow-[0_4px_8px_rgba(128,90,213,0.3)]`}
                disabled={level === 2 && selectedCard === null}
              >
                {isLoading
                  ? 'In Progress'
                  : level === 1
                    ? 'Get Started'
                    : level === 2
                      ? 'Next'
                      : 'Train'}
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
