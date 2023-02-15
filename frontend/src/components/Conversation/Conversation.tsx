import { useMediaQuery } from '../../hooks';
import { selectIsMenuOpen } from '../../store';
import { useSelector } from 'react-redux';

export default function Conversation() {
  const isMobile = useMediaQuery('(max-width: 768px)');
  const isMenuOpen = useSelector(selectIsMenuOpen);

  return (
    //Parent div for all content shown through App.tsx routing needs to have this styling.
    <div
      className={`${
        isMobile
          ? isMenuOpen
            ? 'mt-80'
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
