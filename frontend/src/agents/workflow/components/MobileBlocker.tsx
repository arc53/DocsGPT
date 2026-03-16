import { Monitor } from 'lucide-react';

export default function MobileBlocker() {
  return (
    <div className="bg-lotion dark:bg-raisin-black flex min-h-screen flex-col items-center justify-center px-6 text-center md:hidden">
      <div className="bg-violets-are-blue/10 dark:bg-violets-are-blue/20 mb-6 flex h-20 w-20 items-center justify-center rounded-2xl">
        <Monitor className="text-violets-are-blue h-10 w-10" />
      </div>
      <h2 className="mb-2 text-xl font-bold text-gray-900 dark:text-white">
        Desktop Required
      </h2>
      <p className="max-w-sm text-sm leading-relaxed text-gray-500 dark:text-[#E0E0E0]">
        The Workflow Builder requires a larger screen for the best experience.
        Please open this page on a desktop or laptop computer.
      </p>
    </div>
  );
}
