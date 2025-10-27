import React from 'react';

import Exit from '../assets/exit.svg';

type SidebarProps = {
  isOpen: boolean;
  toggleState: (arg0: boolean) => void;
  children: React.ReactNode;
};

export default function Sidebar({
  isOpen,
  toggleState,
  children,
}: SidebarProps) {
  const sidebarRef = React.useRef<HTMLDivElement>(null);

  const handleClickOutside = (event: MouseEvent) => {
    if (
      sidebarRef.current &&
      !sidebarRef.current.contains(event.target as Node)
    ) {
      toggleState(false);
    }
  };

  React.useEffect(() => {
    document.addEventListener('mousedown', handleClickOutside);
    return () => {
      document.removeEventListener('mousedown', handleClickOutside);
    };
  }, []);
  return (
    <div ref={sidebarRef} className="h-vh relative">
      <div
        className={`dark:bg-chinese-black fixed top-0 right-0 z-50 h-full w-64 transform bg-white shadow-xl transition-all duration-300 sm:w-80 ${
          isOpen ? 'translate-x-[10px]' : 'translate-x-full'
        } border-l border-[#9ca3af]/10`}
      >
        <div className="flex w-full flex-row items-end justify-end px-4 pt-3">
          <button
            className="hover:bg-gray-1000 dark:hover:bg-gun-metal w-7 rounded-full p-2"
            onClick={() => toggleState(!isOpen)}
          >
            <img className="filter dark:invert" src={Exit} />
          </button>
        </div>
        <div className="flex h-full flex-col items-center gap-2 px-6 py-4 text-center">
          {children}
        </div>
      </div>
    </div>
  );
}
