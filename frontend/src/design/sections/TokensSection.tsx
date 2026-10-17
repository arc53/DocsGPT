import { useEffect, useState } from 'react';
import { Example, Section } from '../shared';

const SURFACE_TOKENS = [
  { name: 'background', bg: 'bg-background', fg: 'text-foreground' },
  { name: 'card', bg: 'bg-card', fg: 'text-card-foreground' },
  { name: 'popover', bg: 'bg-popover', fg: 'text-popover-foreground' },
  { name: 'muted', bg: 'bg-muted', fg: 'text-muted-foreground' },
  { name: 'accent', bg: 'bg-accent', fg: 'text-accent-foreground' },
  { name: 'sidebar', bg: 'bg-sidebar', fg: 'text-foreground' },
  { name: 'sidebar-accent', bg: 'bg-sidebar-accent', fg: 'text-foreground' },
  { name: 'answer-surface', bg: 'bg-answer-surface', fg: 'text-foreground' },
] as const;

const BRAND_TOKENS = [
  { name: 'primary', bg: 'bg-primary', fg: 'text-primary-foreground' },
  { name: 'secondary', bg: 'bg-secondary', fg: 'text-secondary-foreground' },
  {
    name: 'destructive',
    bg: 'bg-destructive',
    fg: 'text-destructive-foreground',
  },
  { name: 'success', bg: 'bg-success', fg: 'text-success-foreground' },
  { name: 'warning', bg: 'bg-warning', fg: 'text-warning-foreground' },
  { name: 'info', bg: 'bg-info', fg: 'text-info-foreground' },
] as const;

const LINE_TOKENS = [
  { name: 'border', cls: 'border-border' },
  { name: 'input', cls: 'border-input' },
  { name: 'ring', cls: 'border-ring' },
] as const;

const CHART_TOKENS = [
  'bg-chart-1',
  'bg-chart-2',
  'bg-chart-3',
  'bg-chart-4',
  'bg-chart-5',
] as const;

/** Reads a CSS custom property after the theme class has been applied. */
function useCssVar(name: string, isDark: boolean): string {
  const [value, setValue] = useState('');
  useEffect(() => {
    const frame = requestAnimationFrame(() => {
      setValue(
        getComputedStyle(document.documentElement)
          .getPropertyValue(name)
          .trim(),
      );
    });
    return () => cancelAnimationFrame(frame);
  }, [name, isDark]);
  return value;
}

function Swatch({
  name,
  bg,
  fg,
  isDark,
}: {
  name: string;
  bg: string;
  fg: string;
  isDark: boolean;
}) {
  const value = useCssVar(`--${name}`, isDark);
  return (
    <div className="border-border flex flex-col overflow-hidden rounded-lg border">
      <div className={`${bg} ${fg} flex h-16 items-end px-3 pb-2 text-xs`}>
        Aa
      </div>
      <div className="bg-card px-3 py-2">
        <div className="text-foreground text-xs font-medium">{name}</div>
        <div className="text-muted-foreground font-mono text-xs">{value}</div>
      </div>
    </div>
  );
}

export default function TokensSection({ isDark }: { isDark: boolean }) {
  return (
    <Section
      id="tokens"
      title="Colour tokens"
      intro="Every colour in the UI resolves to one of these variables from src/index.css. The value shown is the one currently applied, so toggle the theme to compare."
    >
      <Example title="Surfaces" code="bg-card text-card-foreground">
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4 lg:grid-cols-6">
          {SURFACE_TOKENS.map((t) => (
            <Swatch key={t.name} {...t} isDark={isDark} />
          ))}
        </div>
      </Example>
      <Example
        title="Brand and status"
        code="bg-success text-success-foreground"
      >
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
          {BRAND_TOKENS.map((t) => (
            <Swatch key={t.name} {...t} isDark={isDark} />
          ))}
        </div>
      </Example>
      <Example title="Lines and charts" code="border-border · bg-chart-1">
        <div className="flex flex-wrap items-center gap-6">
          {LINE_TOKENS.map((t) => (
            <div key={t.name} className="flex items-center gap-2">
              <div className={`${t.cls} size-10 rounded-md border-2`} />
              <span className="text-muted-foreground text-xs">{t.name}</span>
            </div>
          ))}
          <div className="flex items-center gap-1">
            {CHART_TOKENS.map((cls) => (
              <div key={cls} className={`${cls} h-10 w-6 rounded-sm`} />
            ))}
            <span className="text-muted-foreground ml-2 text-xs">
              chart-1 to chart-5: primary, info, success, warning, destructive
            </span>
          </div>
        </div>
      </Example>
    </Section>
  );
}
