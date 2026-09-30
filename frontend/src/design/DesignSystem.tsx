import { Moon, Sun } from 'lucide-react';
import { useRef } from 'react';

import { Button } from '@/components/ui/button';
import { useDarkTheme } from '../hooks';
import TokensSection from './sections/TokensSection';
import TypographySection from './sections/TypographySection';
import ButtonSection from './sections/ButtonSection';
import BadgeSection from './sections/BadgeSection';
import CardSection from './sections/CardSection';
import FormSection from './sections/FormSection';
import DropzoneSection from './sections/DropzoneSection';
import FeedbackSection from './sections/FeedbackSection';
import AvatarSection from './sections/AvatarSection';
import NavigationSection from './sections/NavigationSection';
import TableSection from './sections/TableSection';
import OverlaySection from './sections/OverlaySection';
import PickerSection from './sections/PickerSection';

/**
 * Dev-only style guide, served at /design. It renders every component in
 * src/components/ui with the variants DESIGN.md documents as the defaults,
 * so the page doubles as a visual test of the theme tokens in both modes.
 * Nothing here is translated: the route is not registered in production.
 */

const SECTIONS = [
  ['tokens', 'Colour tokens'],
  ['typography', 'Typography'],
  ['buttons', 'Buttons'],
  ['badges', 'Badges & toasts'],
  ['cards', 'Cards'],
  ['forms', 'Forms'],
  ['dropzone', 'Dropzone'],
  ['feedback', 'Feedback & loading'],
  ['avatars', 'Avatars'],
  ['navigation', 'Navigation'],
  ['tables', 'Tables'],
  ['overlays', 'Overlays'],
  ['pickers', 'Pickers'],
] as const;

export default function DesignSystem() {
  const [isDark, toggleTheme] = useDarkTheme();
  const scrollRef = useRef<HTMLDivElement>(null);
  const jumpTo = (id: string) => (event: React.MouseEvent) => {
    event.preventDefault();
    const container = scrollRef.current;
    const target = document.getElementById(id);
    if (!container || !target) return;
    // Sections are offset from the scroll container; leave room for the
    // sticky header.
    container.scrollTo({ top: target.offsetTop - 88, behavior: 'smooth' });
    window.history.replaceState(null, '', `#${id}`);
  };

  return (
    <div
      ref={scrollRef}
      className="bg-background text-foreground relative h-full overflow-y-auto"
    >
      <header className="border-border bg-background/95 sticky top-0 z-20 border-b backdrop-blur">
        <div className="mx-auto flex max-w-6xl flex-wrap items-center gap-4 px-6 py-3">
          <div className="mr-auto">
            <h1 className="text-base font-semibold">DocsGPT design system</h1>
            <p className="text-muted-foreground text-xs">
              Defaults from frontend/DESIGN.md, rendered with the real
              components. Dev route only.
            </p>
          </div>
          <nav className="hidden flex-wrap gap-1 lg:flex">
            {SECTIONS.map(([id, label]) => (
              <Button key={id} asChild variant="ghost-muted" size="xs">
                <a href={`#${id}`} onClick={jumpTo(id)}>
                  {label}
                </a>
              </Button>
            ))}
          </nav>
          <Button
            variant="outline"
            size="sm"
            shape="pill"
            onClick={toggleTheme}
            aria-label="Toggle theme"
          >
            {isDark ? <Sun /> : <Moon />}
            {isDark ? 'Light' : 'Dark'}
          </Button>
        </div>
      </header>

      <main className="mx-auto flex max-w-6xl flex-col gap-16 px-6 py-10">
        <TokensSection isDark={isDark} />
        <TypographySection />
        <ButtonSection />
        <BadgeSection />
        <CardSection />
        <FormSection />
        <DropzoneSection />
        <FeedbackSection />
        <AvatarSection />
        <NavigationSection />
        <TableSection />
        <OverlaySection />
        <PickerSection />
      </main>
    </div>
  );
}
