import { Monitor } from 'lucide-react';

export default function MobileBlocker() {
  return (
    <div className="bg-background flex min-h-screen flex-col items-center justify-center px-6 text-center md:hidden">
      <div className="bg-primary/10 dark:bg-primary/20 mb-6 flex h-20 w-20 items-center justify-center rounded-2xl">
        <Monitor className="text-primary h-10 w-10" />
      </div>
      <h2 className="text-foreground mb-2 text-xl font-bold">
        Desktop Required
      </h2>
      <p className="text-muted-foreground max-w-sm text-sm leading-relaxed">
        The Workflow Builder requires a larger screen for the best experience.
        Please open this page on a desktop or laptop computer.
      </p>
    </div>
  );
}
