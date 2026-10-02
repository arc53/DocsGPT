import { FileText } from 'lucide-react';
import { useState } from 'react';
import { Dropzone } from '@/components/ui/dropzone';
import { Example, Section } from '../shared';

export default function DropzoneSection() {
  const [dropped, setDropped] = useState<string[]>([]);
  return (
    <Section
      id="dropzone"
      title="Dropzone"
      intro="Click-or-drag file target used by imports and uploads. Colours follow the drag state; pass accept and limits and describe them in the second line."
    >
      <Example
        title="Default, compact and tile"
        code='<Dropzone accept={…} description="…" size="compact | tile">'
      >
        <div className="grid gap-6 md:grid-cols-2">
          <Dropzone
            onDrop={(files) => setDropped(files.map((f) => f.name))}
            accept={{ 'application/x-yaml': ['.yaml', '.yml'] }}
            title="Click to upload or drag and drop a .yaml file"
            description="Agent definitions exported from DocsGPT"
          />
          <div className="flex flex-col gap-4">
            <Dropzone
              size="compact"
              multiple
              onDrop={(files) => setDropped(files.map((f) => f.name))}
              title="Attach files"
              description="PDF, Word, Markdown, up to 25 MB each"
              icon={<FileText />}
            />
            <Dropzone
              size="compact"
              disabled
              onDrop={() => undefined}
              title="Uploads paused"
              description="Indexing in progress"
            />
            <Dropzone
              size="compact"
              onDrop={() => undefined}
              title="With an error"
              error="Only .yaml or .yml files are supported"
            />
            <div className="flex items-center gap-3">
              <Dropzone
                size="tile"
                onDrop={(files) => setDropped(files.map((f) => f.name))}
                title="Avatar"
              />
              <span className="text-muted-foreground text-xs">
                size=&quot;tile&quot;: the agent&apos;s avatar beside its name
                and description.
              </span>
            </div>
            <div className="flex items-center gap-3">
              <Dropzone
                size="tile"
                tileSize="fixed"
                onDrop={(files) => setDropped(files.map((f) => f.name))}
                title="Avatar"
              />
              <span className="text-muted-foreground text-xs">
                tileSize=&quot;fixed&quot;: 64px and icon-only at every width,
                for a narrow drawer.
              </span>
            </div>
            <p className="text-muted-foreground text-xs">
              Last drop: {dropped.length ? dropped.join(', ') : 'nothing yet'}
            </p>
          </div>
        </div>
      </Example>
    </Section>
  );
}
