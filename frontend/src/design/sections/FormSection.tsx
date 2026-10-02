import { Check, Search, X } from 'lucide-react';
import { useState } from 'react';
import { Checkbox } from '@/components/ui/checkbox';
import { FormField } from '@/components/ui/form-field';
import { IconButton } from '@/components/ui/icon-button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { MultiSelect } from '@/components/ui/multi-select';
import { SettingRow, SettingRows } from '@/components/ui/setting-row';
import { Textarea } from '@/components/ui/textarea';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { Switch } from '@/components/ui/switch';
import { Example, Section } from '../shared';

const MULTI_OPTIONS = [
  { value: 'pdf', label: 'PDF' },
  { value: 'docx', label: 'Word', description: 'Added by Lena' },
  { value: 'md', label: 'Markdown' },
  { value: 'html', label: 'HTML' },
  { value: 'csv', label: 'CSV' },
];

export default function FormSection() {
  const [switchOn, setSwitchOn] = useState(true);
  const [formats, setFormats] = useState<string[]>(['pdf', 'md']);
  const [toolbarFormats, setToolbarFormats] = useState<string[]>([
    'pdf',
    'docx',
    'md',
  ]);
  const [scopes, setScopes] = useState<string[]>(['agents:read']);
  const [tokenLimit, setTokenLimit] = useState(true);
  return (
    <Section
      id="forms"
      title="Forms"
      intro="Inputs and selects share the 38px form-row height (Input default; SelectTrigger and Button size field), the sm density and the pill shape. Every form field is labelled by a floating label (FormField, or the Input label shorthand)."
    >
      <Example title="Input sizes" code='<Input size="sm" | "default">'>
        <div className="grid gap-4 md:grid-cols-4">
          <div className="flex flex-col gap-2">
            <Label htmlFor="in-sm">Small</Label>
            <Input id="in-sm" size="sm" placeholder="Filter rows…" />
          </div>
          <div className="flex flex-col gap-2">
            <Label htmlFor="in-md">Default (38px form row)</Label>
            <Input id="in-md" placeholder="Agent name" />
          </div>
        </div>
      </Example>
      <Example
        title="Input shapes and states"
        code='shape="pill" · label · leftIcon · aria-invalid · disabled'
      >
        <div className="grid gap-6 md:grid-cols-2">
          <Input shape="pill" placeholder="Search the docs" />
          <Input
            shape="pill"
            leftIcon={<Search className="text-muted-foreground size-4" />}
            label="With icon"
          />
          <Input
            leftIcon={<Search className="text-muted-foreground size-4" />}
            placeholder="Search files (icon, no label)"
          />
          <Input label="Floating label" defaultValue="Renewal desk" />
          <Input label="Required" required />
          <Input label="Invalid" aria-invalid defaultValue="not-an-email" />
          <Input label="Disabled" disabled defaultValue="Read only" />
        </div>
      </Example>
      <Example
        title="Floating label on other surfaces"
        code='<Input label="…" labelSurface="card" | "background" | "muted">'
      >
        <div className="grid gap-4 md:grid-cols-3">
          {(['card', 'background', 'muted'] as const).map((surface) => (
            <div
              key={surface}
              className={
                surface === 'card'
                  ? 'bg-card rounded-lg border p-4'
                  : surface === 'background'
                    ? 'bg-background rounded-lg border p-4'
                    : 'bg-muted rounded-lg border p-4'
              }
            >
              <Input
                label={`On ${surface}`}
                labelSurface={surface}
                defaultValue="Renewal desk"
              />
            </div>
          ))}
        </div>
      </Example>
      <Example title="Bare field inside a host" code='<Input variant="bare">'>
        <div className="bg-sidebar w-64 rounded-lg border py-2">
          <div className="bg-sidebar-accent mx-2 flex h-9 items-center gap-1 rounded-3xl pr-1 pl-3">
            <Input
              variant="bare"
              aria-label="Conversation name"
              defaultValue="Q3 carrier renewals"
              className="flex-1"
            />
            <IconButton
              variant="ghost-muted"
              size="icon-xs"
              label="Save"
              icon={Check}
            />
            <IconButton
              variant="ghost-muted"
              size="icon-xs"
              label="Cancel"
              icon={X}
            />
          </div>
        </div>
      </Example>
      <Example
        title="Field on a muted panel"
        code='<Input variant="filled"> · <Textarea variant="filled">'
      >
        <div className="bg-muted flex max-w-sm flex-col gap-2 rounded-lg p-4">
          <Input
            variant="filled"
            aria-label="Base URL"
            defaultValue="https://api.meridianfreight.example/v2"
          />
          <Textarea
            variant="filled"
            size="sm"
            rows={3}
            aria-label="Banned terms"
            defaultValue={'competitor name\ninternal codename'}
          />
        </div>
      </Example>
      <Example
        title="Select"
        code='<SelectTrigger size="sm | field (default)" shape="pill">'
      >
        <div className="flex flex-wrap items-center gap-4">
          <Select defaultValue="finance">
            <SelectTrigger size="sm">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="finance">Small</SelectItem>
              <SelectItem value="legal">Legal</SelectItem>
            </SelectContent>
          </Select>
          <Select defaultValue="finance">
            <SelectTrigger>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="finance">Field (default)</SelectItem>
              <SelectItem value="legal">Legal</SelectItem>
            </SelectContent>
          </Select>
          <Select defaultValue="finance">
            <SelectTrigger shape="pill">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="finance">Field pill</SelectItem>
              <SelectItem value="legal">Legal</SelectItem>
            </SelectContent>
          </Select>
          <Select>
            <SelectTrigger>
              <SelectValue placeholder="Placeholder" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="a">Option A</SelectItem>
            </SelectContent>
          </Select>
        </div>
      </Example>
      <Example
        title="Textarea"
        code='<Textarea size="sm | default | lg" resize="none | vertical | both" variant="default | filled">'
      >
        <div className="grid items-start gap-4 md:grid-cols-3">
          <Textarea size="sm" placeholder="Short note…" />
          <Textarea placeholder="Describe what this agent does…" />
          <Textarea
            size="lg"
            resize="none"
            placeholder="System prompt…"
            defaultValue="You are a helpful assistant for Meridian Freight Group."
          />
        </div>
      </Example>
      <Example
        title="FormField"
        code="<FormField label required hint error disabled labelSurface float>{field}</FormField>"
      >
        <div className="grid items-start gap-6 md:grid-cols-3">
          <FormField label="Server name" required hint="Shown in the tool list">
            <Input placeholder="My MCP server" />
          </FormField>
          <FormField label="Authentication type">
            <Select defaultValue="none">
              <SelectTrigger size="field" className="w-full">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="none">No authentication</SelectItem>
                <SelectItem value="bearer">Bearer token</SelectItem>
              </SelectContent>
            </Select>
          </FormField>
          <FormField label="Server URL" required error="Server URL is required">
            <Input placeholder="https://" />
          </FormField>
          <FormField label="Description" hint="Optional">
            <Textarea rows={3} placeholder="What this server is for" />
          </FormField>
          <div className="bg-muted rounded-2xl p-4">
            <FormField label="Policy" labelSurface="muted">
              <Textarea rows={3} />
            </FormField>
          </div>
          <FormField label="Scopes" float={false}>
            <div className="flex flex-col gap-2 text-sm">
              <span>Agents: read</span>
              <span>Sources: read and write</span>
            </div>
          </FormField>
        </div>
      </Example>
      <Example
        title="SettingRow"
        code='<SettingRows><SettingRow label description htmlFor? after alignStart as="label | h2 | h3">{control}</SettingRow></SettingRows> · the control takes the row id and aria-describedby = description'
      >
        <SettingRows className="max-w-xl">
          <SettingRow
            label="Token limiting"
            description="Limit daily total tokens that can be used by this agent"
            htmlFor="ds-token-limiting"
            after={
              <Input placeholder="Enter token limit" disabled={!tokenLimit} />
            }
          >
            <Switch
              id="ds-token-limiting"
              checked={tokenLimit}
              onCheckedChange={setTokenLimit}
            />
          </SettingRow>
          {/* No ids: the row wires the Switch (label + description). */}
          <SettingRow
            label="Allow prompt override"
            description="Let v1 API callers replace this agent's system prompt"
          >
            <Switch />
          </SettingRow>
          <SettingRow
            as="h3"
            label="Guardrails"
            description="A heading title keeps the outline; the control names itself"
          >
            <Switch aria-label="Enable guardrails" />
          </SettingRow>
          <SettingRow
            alignStart
            label="Redact personal data"
            description="Mask names, email addresses, phone numbers and account ids in both the question and the answer before they are stored in the run log. Wrapped descriptions top-align the control."
            htmlFor="ds-redact"
          >
            <Switch id="ds-redact" />
          </SettingRow>
        </SettingRows>
      </Example>
      <Example
        title="Checkbox"
        code='<Checkbox size="sm | default" checked onCheckedChange>'
      >
        <div className="flex flex-col gap-3">
          {['agents:read', 'agents:write', 'agents:keys'].map((scope) => (
            <div key={scope} className="flex items-center gap-3">
              <Checkbox
                id={`ds-${scope}`}
                checked={scopes.includes(scope)}
                onCheckedChange={(checked) =>
                  setScopes((current) =>
                    checked === true
                      ? [...current, scope]
                      : current.filter((s) => s !== scope),
                  )
                }
              />
              <Label htmlFor={`ds-${scope}`} className="font-mono">
                {scope}
              </Label>
            </div>
          ))}
          <div className="flex items-center gap-3">
            <Checkbox id="ds-cb-sm" size="sm" defaultChecked />
            <Label htmlFor="ds-cb-sm">Small (table cells)</Label>
          </div>
          <div className="flex items-center gap-3">
            <Checkbox id="ds-cb-disabled" disabled defaultChecked />
            <Label htmlFor="ds-cb-disabled">Disabled</Label>
          </div>
        </div>
      </Example>
      <Example
        title="Switch and multi-select"
        code='<Switch> · <MultiSelect shape="default | pill"> (the first two picks, one on a pill, then "+N more"; no X in the trigger: unselect in the list)'
      >
        <div className="grid items-start gap-6 md:grid-cols-2">
          <div className="flex flex-col gap-4">
            <div className="flex items-center gap-3">
              <Switch
                id="sw-1"
                checked={switchOn}
                onCheckedChange={setSwitchOn}
              />
              <Label htmlFor="sw-1">
                Notify on failed runs{' '}
                <span className="text-muted-foreground">
                  ({switchOn ? 'on' : 'off'})
                </span>
              </Label>
            </div>
            <div className="flex items-center gap-3">
              <Switch id="sw-2" disabled />
              <Label htmlFor="sw-2">Disabled</Label>
            </div>
          </div>
          <div className="flex flex-col gap-4">
            <MultiSelect
              options={MULTI_OPTIONS}
              selected={formats}
              onChange={setFormats}
              placeholder="Allowed formats"
            />
            <MultiSelect
              options={MULTI_OPTIONS}
              selected={toolbarFormats}
              onChange={setToolbarFormats}
              placeholder="Allowed formats"
              shape="pill"
            />
          </div>
        </div>
      </Example>
    </Section>
  );
}
