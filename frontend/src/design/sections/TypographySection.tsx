import { Button } from '@/components/ui/button';
import { Card, CardDescription, CardTitle } from '@/components/ui/card';
import { SectionHeader } from '@/components/ui/section-header';
import { Separator } from '@/components/ui/separator';
import { Example, Section } from '../shared';

export default function TypographySection() {
  return (
    <Section
      id="typography"
      title="Typography"
      intro="Two text tones cover the app: foreground for content and muted-foreground for everything secondary. Lighter tiers use an opacity modifier, not a lighter grey."
    >
      <Example
        title="Tones"
        code="text-foreground · text-muted-foreground · text-muted-foreground/70"
      >
        <div className="flex flex-col gap-2 text-sm">
          <p className="text-foreground">
            Foreground: titles, body copy, values in tables.
          </p>
          <p className="text-muted-foreground">
            Muted foreground: descriptions, labels, timestamps, icons.
          </p>
          <p className="text-muted-foreground/70">
            Muted at 70%: placeholders and de-emphasised metadata.
          </p>
          <p className="text-primary">Primary: links and the selected state.</p>
          <p className="text-destructive">Destructive: errors.</p>
        </div>
      </Example>
      <Example
        title="Scale"
        code="text-xs · text-sm · text-base · text-lg · text-xl · font-mono"
      >
        <div className="flex flex-col gap-2">
          <p className="text-xs">Extra small, 12px, badges and hints</p>
          <p className="text-sm">Small, 14px, the default UI size</p>
          <p className="text-base">Base, 16px, inputs on mobile and prose</p>
          <p className="text-lg font-semibold">Large, 18px, section titles</p>
          <p className="text-xl leading-tight font-semibold">
            Extra large, 20px, dialog, sheet and detail-page titles
          </p>
          <p className="font-mono text-xs">Mono 12px: ids, keys, code</p>
        </div>
      </Example>
      <Example
        title="Roles"
        code='<SectionHeader size="default | sm | xs" tone="destructive"> · CardTitle + CardDescription size="xs"'
      >
        <div className="flex max-w-md flex-col gap-6">
          <SectionHeader
            title="Prompts"
            description="System prompts your agents can use."
          />
          <div className="flex flex-col gap-3">
            <SectionHeader as="h3" size="sm" title="Recurring" />
            <SectionHeader as="h3" size="xs" title="Connection" />
            <SectionHeader
              as="h3"
              size="xs"
              tone="destructive"
              title="Danger zone"
            />
          </div>
          <Card variant="filled">
            <CardTitle>Vendor Due Diligence</CardTitle>
            <CardDescription size="xs">
              Checks new carriers against sanctions lists and insurance
              certificates before onboarding.
            </CardDescription>
          </Card>
        </div>
      </Example>
      <Example
        title="Separator"
        code='<Separator /> · <Separator orientation="vertical" />'
      >
        <div className="flex flex-col gap-6">
          <div className="flex max-w-md flex-col gap-3 text-sm">
            <p>Carrier network: 42 carriers across 18 lanes.</p>
            <Separator />
            <p className="text-muted-foreground">
              Last synced from SharePoint 12 minutes ago.
            </p>
          </div>
          <div className="flex h-8 items-center gap-2">
            <Button variant="ghost" size="sm">
              Export
            </Button>
            <Separator orientation="vertical" />
            <Button variant="ghost" size="sm">
              Share
            </Button>
          </div>
        </div>
      </Example>
    </Section>
  );
}
