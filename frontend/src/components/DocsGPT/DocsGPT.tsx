export default function DocsGPT({
  isMenuOpen,
  isMobile,
}: {
  isMenuOpen: boolean;
  isMobile: boolean;
}) {
  return (
    //Parent div for all content shown through App.tsx routing needs to have this styling. Might change when state management is updated.
    <div
      className={`${
        isMobile
          ? isMenuOpen
            ? 'mt-72'
            : 'mt-16'
          : isMenuOpen
          ? 'md:ml-72 lg:ml-96'
          : 'ml-16'
      } h-full w-full p-6 transition-all`}
    >
      Docs GPT Chat Placeholder
    </div>
  );
}
