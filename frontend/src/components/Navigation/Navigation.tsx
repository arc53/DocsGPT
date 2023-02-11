import React, { useState } from 'react';
import { NavLink } from 'react-router-dom';
import Arrow1 from './imgs/arrow.svg';
import Key from './imgs/key.svg';
import Info from './imgs/info.svg';
import Link from './imgs/link.svg';

function MobileNavigation() {
  return <div>Mobile Navigation</div>;
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
    return <MobileNavigation />;
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
