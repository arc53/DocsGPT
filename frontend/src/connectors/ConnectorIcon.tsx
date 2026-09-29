import { Plug } from 'lucide-react';
import * as React from 'react';

import { cn } from '@/lib/utils';
import ConfluenceIcon from '../assets/confluence.svg?react';
import DriveIcon from '../assets/drive.svg?react';
import RedditIcon from '../assets/reddit.svg?react';
import S3Icon from '../assets/s3.svg?react';
import SharePointIcon from '../assets/sharepoint.svg?react';

type SvgComponent = React.FC<React.SVGProps<SVGSVGElement>>;

// Preset logos live in assets/connectors; built-in tool services reuse the
// tool icons. Every asset draws in currentColor unless it is a multi-colour
// brand mark (Brave), so the icon follows the theme through `text-*`.
const presetModules = import.meta.glob('../assets/connectors/*.svg', {
  query: '?react',
  import: 'default',
  eager: true,
}) as Record<string, SvgComponent>;
const toolModules = import.meta.glob('../assets/toolIcons/tool_*.svg', {
  query: '?react',
  import: 'default',
  eager: true,
}) as Record<string, SvgComponent>;

const ICONS: Record<string, SvgComponent> = {
  drive: DriveIcon,
  sharepoint: SharePointIcon,
  confluence: ConfluenceIcon,
  s3: S3Icon,
  reddit: RedditIcon,
};
for (const [path, Component] of Object.entries(presetModules)) {
  const match = path.match(/connectors\/(.+)\.svg$/);
  if (match) ICONS[match[1]] = Component;
}
for (const [path, Component] of Object.entries(toolModules)) {
  const match = path.match(/(tool_.+)\.svg$/);
  if (match) ICONS[match[1]] = Component;
}

type ConnectorIconProps = {
  /** Catalog `icon` key, e.g. `drive`, `tool_telegram` or `notion`. */
  icon: string;
  className?: string;
  /** Accessible name. Omit when the connector's name is next to the icon. */
  title?: string;
};

/**
 * A connector's logo. Unknown keys (a custom MCP server) fall back to a plug,
 * the same glyph the Connectors page uses in the navigation.
 */
export default function ConnectorIcon({
  icon,
  className,
  title,
}: ConnectorIconProps) {
  const Icon = ICONS[icon];
  const a11y = title
    ? { role: 'img' as const, 'aria-label': title }
    : { 'aria-hidden': true as const };
  if (!Icon) {
    return (
      <Plug className={cn('text-foreground size-6', className)} {...a11y} />
    );
  }
  return <Icon className={cn('text-foreground size-6', className)} {...a11y} />;
}
