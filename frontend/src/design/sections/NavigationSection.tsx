import { useState } from 'react';
import {
  Breadcrumb,
  BreadcrumbEllipsis,
  BreadcrumbItem,
  BreadcrumbLink,
  BreadcrumbList,
  BreadcrumbPage,
  BreadcrumbSeparator,
} from '@/components/ui/breadcrumb';
import { Card } from '@/components/ui/card';
import { Collapsible, CollapsibleTrigger } from '@/components/ui/collapsible';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Example, Section } from '../shared';

export default function NavigationSection() {
  const [collapsibleOpen, setCollapsibleOpen] = useState(false);
  const [smallOpen, setSmallOpen] = useState(false);
  const [sectionOpen, setSectionOpen] = useState(false);
  return (
    <Section
      id="navigation"
      title="Navigation"
      intro="Tabs, disclosures and breadcrumbs as shipped."
    >
      <Example
        title="Tabs"
        code="<Tabs> · <TabsList> · <TabsTrigger> (underline is the only look)"
      >
        <Tabs defaultValue="sources">
          <TabsList>
            <TabsTrigger value="sources">Sources</TabsTrigger>
            <TabsTrigger value="tools">Tools</TabsTrigger>
            <TabsTrigger value="guardrails">Guardrails</TabsTrigger>
          </TabsList>
          <TabsContent value="sources">
            <p className="text-muted-foreground pt-4 text-sm">
              Connected sources and their indexing status.
            </p>
          </TabsContent>
          <TabsContent value="tools">
            <p className="text-muted-foreground pt-4 text-sm">
              Tools the agent may call.
            </p>
          </TabsContent>
          <TabsContent value="guardrails">
            <p className="text-muted-foreground pt-4 text-sm">
              Controls applied before and after each turn.
            </p>
          </TabsContent>
        </Tabs>
      </Example>
      <Example
        title="Collapsible"
        code='<CollapsibleTrigger open onOpenChange controls> (look="inline" = link sm) · chevron="sm" · <Collapsible id open>'
      >
        <div className="flex max-w-md flex-col gap-6">
          {/* Trigger + Collapsible in a plain div; the body's pt is the gap. */}
          <div>
            <CollapsibleTrigger
              open={collapsibleOpen}
              onOpenChange={setCollapsibleOpen}
              controls="ds-collapsible"
            >
              {collapsibleOpen
                ? 'Hide recent commands'
                : 'Show recent commands'}
            </CollapsibleTrigger>
            <Collapsible id="ds-collapsible" open={collapsibleOpen}>
              <p className="text-muted-foreground pt-3 text-sm">
                ls -la ~/Downloads/rate-sheets · python3 clean_rates.py Q3.xlsx
              </p>
            </Collapsible>
          </div>
          <div>
            <CollapsibleTrigger
              chevron="sm"
              open={smallOpen}
              onOpenChange={setSmallOpen}
              controls="ds-collapsible-sm"
            >
              3 older runs
            </CollapsibleTrigger>
            <Collapsible id="ds-collapsible-sm" open={smallOpen}>
              <p className="text-muted-foreground pt-3 text-sm">
                Sep 28 · Sep 21 · Sep 14
              </p>
            </Collapsible>
          </div>
        </div>
      </Example>
      <Example
        title="Section disclosure"
        code='<Card><h2><CollapsibleTrigger look="section" open onOpenChange controls></h2> · <Collapsible id open> (only inside a Card)'
      >
        <div className="max-w-md">
          <Card variant="subtle" padding="lg">
            <div>
              <h2>
                <CollapsibleTrigger
                  look="section"
                  open={sectionOpen}
                  onOpenChange={setSectionOpen}
                  controls="ds-collapsible-section"
                >
                  Advanced
                </CollapsibleTrigger>
              </h2>
              <Collapsible id="ds-collapsible-section" open={sectionOpen}>
                <p className="text-muted-foreground pt-5 text-sm">
                  Token limit, request limit and the default model.
                </p>
              </Collapsible>
            </div>
          </Card>
        </div>
      </Example>
      <Example title="Breadcrumb" code="<Breadcrumb> · <BreadcrumbEllipsis />">
        <div className="grid gap-8 md:grid-cols-2">
          <Breadcrumb>
            <BreadcrumbList>
              <BreadcrumbItem>
                <BreadcrumbLink href="#navigation">Agents</BreadcrumbLink>
              </BreadcrumbItem>
              <BreadcrumbSeparator />
              <BreadcrumbItem>
                <BreadcrumbLink href="#navigation">Renewal desk</BreadcrumbLink>
              </BreadcrumbItem>
              <BreadcrumbSeparator />
              <BreadcrumbItem>
                <BreadcrumbPage>Schedules</BreadcrumbPage>
              </BreadcrumbItem>
            </BreadcrumbList>
          </Breadcrumb>
          <Breadcrumb>
            <BreadcrumbList>
              <BreadcrumbItem>
                <BreadcrumbLink href="#navigation">Agents</BreadcrumbLink>
              </BreadcrumbItem>
              <BreadcrumbSeparator />
              <BreadcrumbItem>
                <BreadcrumbPage>
                  Quarterly renewal desk for key logistics accounts
                </BreadcrumbPage>
              </BreadcrumbItem>
            </BreadcrumbList>
          </Breadcrumb>
          <Breadcrumb>
            <BreadcrumbList>
              <BreadcrumbItem>
                <BreadcrumbLink href="#navigation">Sources</BreadcrumbLink>
              </BreadcrumbItem>
              <BreadcrumbSeparator />
              <BreadcrumbItem>
                <BreadcrumbEllipsis />
              </BreadcrumbItem>
              <BreadcrumbSeparator />
              <BreadcrumbItem>
                <BreadcrumbPage>Carrier contracts</BreadcrumbPage>
              </BreadcrumbItem>
            </BreadcrumbList>
          </Breadcrumb>
        </div>
      </Example>
    </Section>
  );
}
