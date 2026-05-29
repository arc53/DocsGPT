import * as React from 'react';

import { cn } from '@/lib/utils';

type SvgComponent = React.FC<React.SVGProps<SVGSVGElement>>;

// Inline every tool icon via vite-plugin-svgr so the monochrome icons inherit
// `currentColor` and follow the active theme; branded icons keep their own colors.
const iconModules = import.meta.glob('../assets/toolIcons/tool_*.svg', {
  query: '?react',
  import: 'default',
  eager: true,
}) as Record<string, SvgComponent>;

const iconByToolName: Record<string, SvgComponent> = {};
for (const [filePath, Component] of Object.entries(iconModules)) {
  const match = filePath.match(/tool_(.+)\.svg$/);
  if (match) iconByToolName[match[1]] = Component;
}

type ToolIconProps = {
  /** Backend tool name, e.g. ``mcp_tool`` (resolves to ``tool_<name>.svg``). */
  name: string;
  className?: string;
  /** Accessible label. Omit for decorative icons paired with visible text. */
  title?: string;
};

/**
 * Renders a tool's icon inline so monochrome icons inherit ``currentColor`` and
 * adapt to light/dark themes. Branded icons keep their own colors.
 */
export default function ToolIcon({ name, className, title }: ToolIconProps) {
  const Icon = iconByToolName[name];
  if (!Icon) return null;
  const a11y = title
    ? { role: 'img' as const, 'aria-label': title }
    : { 'aria-hidden': true as const };
  return (
    <Icon
      className={cn(
        'h-6 w-6 text-neutral-700 dark:text-neutral-200',
        className,
      )}
      {...a11y}
    />
  );
}
