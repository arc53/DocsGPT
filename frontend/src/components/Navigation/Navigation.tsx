import React, { useState } from 'react';
import { NavLink } from 'react-router-dom';
import Arrow1 from './imgs/arrow.svg';
import Hamburger from './imgs/hamburger.svg';
import Key from './imgs/key.svg';
import Info from './imgs/info.svg';
import Link from './imgs/link.svg';
import Exit from './imgs/exit.svg';

function MobileNavigation({
  isMenuOpen,
  setIsMenuOpen,
  setIsApiModalOpen,
}: {
  isMenuOpen: boolean;
  setIsMenuOpen: React.Dispatch<React.SetStateAction<boolean>>;
  setIsApiModalOpen: React.Dispatch<React.SetStateAction<boolean>>;
}) {
  //TODO - Need to replace Chat button to open secondary nav with scrollable past chats option and new chat at top
  //TODO - Need to add Discord and Github links
  return (
    <div
      className={`${
        isMenuOpen ? 'border-b-2 border-gray-100' : 'h-16'
      } fixed flex w-full flex-col bg-gray-50 transition-all`}
    >
      <div className="h-16 w-full border-b-2 border-gray-100">
        {isMenuOpen ? (
          <>
            <button
              className="mt-5 ml-6 h-6 w-6"
              onClick={() => setIsMenuOpen(!isMenuOpen)}
            >
              <img src={Exit} alt="menu toggle" className="w-5" />
            </button>
          </>
        ) : (
          <>
            <button
              className="mt-5 ml-6 h-6 w-6"
              onClick={() => setIsMenuOpen(!isMenuOpen)}
            >
              <img src={Hamburger} alt="menu toggle" className="w-7" />
            </button>
          </>
        )}
      </div>
      {isMenuOpen && (
        <nav className="my-4 flex flex-col">
          <NavLink
            to="/"
            className="flex h-12 cursor-pointer gap-4 rounded-md px-6 hover:bg-gray-100"
          >
            <img src={Info} alt="info" className="ml-2 w-5" />
            <p className="my-auto text-eerie-black">Chat</p>
          </NavLink>
          <NavLink
            to="/about"
            className="flex h-12 cursor-pointer gap-4 rounded-md px-6 hover:bg-gray-100"
          >
            <img src={Info} alt="info" className="ml-2 w-5" />
            <p className="my-auto text-eerie-black">About</p>
          </NavLink>
          <div className="flex h-12 cursor-pointer gap-4 rounded-md px-6 hover:bg-gray-100">
            <img src={Link} alt="info" className="ml-2 w-5" />
            <p className="my-auto text-eerie-black">Discord</p>
          </div>
          <div className="flex h-12 cursor-pointer gap-4 rounded-md px-6 hover:bg-gray-100">
            <img src={Link} alt="info" className="ml-2 w-5" />
            <p className="my-auto text-eerie-black">Github</p>
          </div>
          <div
            className="flex h-12 cursor-pointer gap-4 rounded-md px-6 hover:bg-gray-100"
            onClick={() => setIsApiModalOpen(true)}
          >
            <img src={Key} alt="info" className="ml-2 w-5" />
            <p className="my-auto text-eerie-black">Reset Key</p>
          </div>
        </nav>
      )}
    </div>
  );
}

function DesktopNavigation({
  isMenuOpen,
  setIsMenuOpen,
  setIsApiModalOpen,
}: {
  isMenuOpen: boolean;
  setIsMenuOpen: React.Dispatch<React.SetStateAction<boolean>>;
  setIsApiModalOpen: React.Dispatch<React.SetStateAction<boolean>>;
}) {
  return (
    <div
      className={`${
        isMenuOpen ? 'w-72 lg:w-96' : 'w-16'
      } fixed flex h-screen flex-col border-r-2 border-gray-100 bg-gray-50 transition-all`}
    >
      <div
        className={`${
          isMenuOpen ? 'w-full' : 'w-16'
        } ml-auto h-16 border-b-2 border-gray-100`}
      >
        <button
          className="float-right mr-5 mt-5 h-5 w-5"
          onClick={() => setIsMenuOpen(!isMenuOpen)}
        >
          <img
            src={Arrow1}
            alt="menu toggle"
            className={`${
              isMenuOpen ? 'rotate-0' : 'rotate-180'
            } m-auto w-3 transition-all`}
          />
        </button>
      </div>

      {isMenuOpen && (
        <>
          <div className="flex-grow border-b-2 border-gray-100"></div>

          <div className="flex h-16 flex-col border-b-2 border-gray-100">
            <div
              className="my-auto mx-4 flex h-12 cursor-pointer gap-4 rounded-md hover:bg-gray-100"
              onClick={() => setIsApiModalOpen(true)}
            >
              <img src={Key} alt="key" className="ml-2 w-6" />
              <p className="my-auto text-eerie-black">Reset Key</p>
            </div>
          </div>

          <div className="flex h-48 flex-col border-b-2 border-gray-100">
            <NavLink
              to="/about"
              className="my-auto mx-4 flex h-12 cursor-pointer gap-4 rounded-md hover:bg-gray-100"
            >
              <img src={Info} alt="info" className="ml-2 w-5" />
              <p className="my-auto text-eerie-black">About</p>
            </NavLink>

            <div className="my-auto mx-4 flex h-12 cursor-pointer gap-4 rounded-md hover:bg-gray-100">
              <img src={Link} alt="link" className="ml-2 w-5" />
              <p className="my-auto text-eerie-black">Discord</p>
            </div>

            <div className="my-auto mx-4 flex h-12 cursor-pointer gap-4 rounded-md hover:bg-gray-100">
              <img src={Link} alt="link" className="ml-2 w-5" />
              <p className="my-auto text-eerie-black">Github</p>
            </div>
          </div>
        </>
      )}
    </div>
  );
}

export default function Navigation({
  isMobile,
  isMenuOpen,
  setIsMenuOpen,
  setIsApiModalOpen,
}: {
  isMobile: boolean;
  isMenuOpen: boolean;
  setIsMenuOpen: React.Dispatch<React.SetStateAction<boolean>>;
  setIsApiModalOpen: React.Dispatch<React.SetStateAction<boolean>>;
}) {
  if (isMobile) {
    return (
      <MobileNavigation
        isMenuOpen={isMenuOpen}
        setIsMenuOpen={setIsMenuOpen}
        setIsApiModalOpen={setIsApiModalOpen}
      />
    );
  } else {
    return (
      <DesktopNavigation
        isMenuOpen={isMenuOpen}
        setIsMenuOpen={setIsMenuOpen}
        setIsApiModalOpen={setIsApiModalOpen}
      />
    );
  }
}
