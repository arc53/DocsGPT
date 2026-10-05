import { Database, FileText, Users } from 'lucide-react';
import { Avatar, avatarSizeNames } from '@/components/ui/avatar';
import { Example, Section } from '../shared';

// Initials boxes need a size; `none` is for images that size themselves.
const AVATAR_SIZES = avatarSizeNames.filter((size) => size !== 'none');

export default function AvatarSection() {
  return (
    <Section
      id="avatars"
      title="Avatars"
      intro="Image avatars keep their own size. Initials boxes take size, shape and a tone."
    >
      <Example
        title="Sizes, shapes, tones"
        code={`<Avatar size="${AVATAR_SIZES.join(' | ')}" shape="circle" variant="primary">LK</Avatar>`}
      >
        <div className="flex flex-wrap items-end gap-8">
          <div className="flex items-end gap-3">
            {AVATAR_SIZES.map((size) => (
              <Avatar key={size} size={size} shape="circle" variant="primary">
                LK
              </Avatar>
            ))}
          </div>
          <div className="flex items-end gap-3">
            {AVATAR_SIZES.map((size) => (
              <Avatar key={size} size={size} shape="square" variant="muted">
                MF
              </Avatar>
            ))}
          </div>
          <div className="flex items-end gap-3">
            <Avatar size="lg" shape="circle" imgClassName="size-full" />
            <Avatar size="default" shape="square" imgClassName="size-full" />
            <span className="text-muted-foreground self-center text-xs">
              image, robot fallback
            </span>
          </div>
        </div>
      </Example>
      <Example
        title="Icon tiles"
        code='<Avatar size="xs | sm | xl" shape="square" variant="icon"><Icon className="size-4" /></Avatar>'
      >
        <div className="flex flex-wrap items-end gap-8">
          <div className="flex flex-col items-center gap-2">
            <Avatar size="xs" shape="square" variant="icon">
              <Users className="size-4" />
            </Avatar>
            <span className="text-muted-foreground text-xs">
              xs · team switcher
            </span>
          </div>
          <div className="flex flex-col items-center gap-2">
            <Avatar size="sm" shape="square" variant="icon">
              <FileText className="size-4" />
            </Avatar>
            <span className="text-muted-foreground text-xs">
              sm · ListRow leading
            </span>
          </div>
          <div className="flex flex-col items-center gap-2">
            <Avatar size="xl" shape="square" variant="icon">
              <Database className="size-6" />
            </Avatar>
            <span className="text-muted-foreground text-xs">
              xl · drawer or wizard header
            </span>
          </div>
        </div>
      </Example>
    </Section>
  );
}
