# DocsGPT frontend design system

The UI is Tailwind v4 plus the shadcn-style components in
`src/components/ui/`. `@shadcn/lint` enforces the rules below through
`npm run lint`; its messages point here. Everything in this file is either a
token in `src/index.css` or a variant in a `ui/` component, so an agent or a
contributor can always find the concrete thing to use.

## Rules in one paragraph

Pages compose `ui/` components and choose their look through props
(`variant`, `size`, `shape`). `className` on a component is for placement
only: margin, width, flex and grid, positioning. Colours come from the theme
tokens, never from the raw Tailwind palette. Spacing, type and radii come
from the Tailwind scale, never from arbitrary `[...]` values. Runtime values
go in CSS custom properties or, when unavoidable, an inline style with a
disable comment.

## Colour tokens

Defined in `src/index.css` (`:root` for light, `.dark` for dark) and exposed
through `@theme inline`, so `bg-`, `text-`, `border-`, `ring-`, `fill-` and
`stroke-` all accept them, including opacity modifiers such as
`bg-success/10`. One token class replaces a light + dark pair.

| Token                                   | Use for                                                                           | Replaces                                                            |
| --------------------------------------- | --------------------------------------------------------------------------------- | ------------------------------------------------------------------- |
| `background`, `foreground`              | page surface and primary text                                                     | `bg-white`, `text-gray-700/800/900`, `dark:text-gray-200/300`       |
| `card`, `card-foreground`               | raised surfaces (cards, dialogs, dropdowns)                                       | `bg-white dark:bg-[#2b2c31]`                                        |
| `popover`, `popover-foreground`         | floating menus and popovers                                                       | same as card                                                        |
| `muted`, `muted-foreground`             | quiet fills and secondary text, icons, placeholders, timestamps                   | `bg-gray-100/200`, `text-gray-400/500/600`, `dark:text-gray-400`    |
| `accent`, `accent-foreground`           | hover and selected fills                                                          | `hover:bg-gray-100`, `dark:hover:bg-gray-700`                       |
| `border`, `input`, `ring`               | dividers, field borders, focus rings                                              | `border-gray-200/300`, `dark:border-gray-600/700`                   |
| `primary`, `primary-foreground`         | brand purple: primary actions, links, selected states                             | `bg-purple-*`, `text-purple-*`, `#7D54D1`, `#A076F6`                |
| `secondary`, `secondary-foreground`     | pressed and active toggles (a brand tint), secondary buttons, the question bubble | `bg-accent` on an active icon button                                |
| `destructive`, `destructive-foreground` | errors, failed states, dangerous actions                                          | `text-red-*`, `bg-red-50/100`, `#B42318`, `#E60000`                 |
| `success`, `success-foreground`         | completed, active, healthy                                                        | `text-green-*`, `text-emerald-*`, `bg-green-50/100`                 |
| `warning`, `warning-foreground`         | paused, pending review, degraded                                                  | `text-amber-*`, `text-yellow-*`, `text-orange-*`, `bg-amber-50/100` |
| `info`, `info-foreground`               | running, informational                                                            | `text-blue-*`, `bg-blue-50/100`                                     |
| `sidebar-*`                             | the navigation rail                                                               |                                                                     |
| `chart-1` to `chart-5`                  | data series only, never UI chrome (see below)                                     |                                                                     |
| `answer-bubble`                         | assistant message background                                                      |                                                                     |

Status colours are tuned to stay vivid rather than turning brown or olive,
so their contrast is low. Against white in light mode, `destructive` and
`success` are about 3.8:1, `warning` is 2.9:1 and `info` is 5.2:1. On the
dark card, `destructive` is 2.9:1 and the others are 5.5:1 or more. Do not
use them for long body text; they are for badges, icons, short labels and
fills.

Chart colours are not a separate palette. `chart-1` to `chart-5` alias
`primary`, `info`, `success`, `warning` and `destructive`, in that order,
so the charts use the same colours as the rest of the app in both themes.
A single series uses `chart-1`, the brand colour. When a series has a
meaning, use the token for that meaning, not the next one in order:
failed tool calls use `destructive`, succeeded ones `success`, pending
ones `warning`. Series with no meaning (models, agents, sources) take
`chart-1` to `chart-5` in order. When there are more than five, the four
largest keep `chart-1` to `chart-4` and the rest are summed into one
"Other" series in `chart-5`, so no colour repeats (`settings/foldSeries.ts`).
`secondary` is never a chart colour.

Patterns:

- Status pill: `<Badge variant="success">`. Status box: `<Alert variant="warning">`.
  Reach for `bg-success/10 text-success` directly only on dots and borders.
- Solid status fill: `bg-warning text-warning-foreground`.
- Guardrail outcomes: block `destructive`, flag `warning`, redact `info`,
  not evaluated `neutral`.
- Status border: `border-destructive/50`.
- De-emphasised text: `text-muted-foreground`; go lighter with an opacity
  modifier (`text-muted-foreground/70`) rather than a lighter grey.
- Text on the brand colour is `text-primary-foreground`, not `text-white`.
- `secondary` is a brand tint, not a grey: primary at 10% (light) or 15%
  (dark) over whatever sits behind it, with `primary` text in light and a
  lighter purple (#b89cf8) in dark. So a pressed toggle (CopyButton's copied
  state, text-to-speech while speaking) shows on card, background and muted
  alike, and never reads as the neutral ghost hover. Use it as
  `variant={active ? 'secondary' : 'ghost-muted'}`.
- The user's question bubble is `bg-secondary text-foreground`: the brand
  tint as the fill, with body text in `foreground` (15.7:1 light, 12.4:1
  dark) rather than `secondary-foreground`, which is only 4.5:1 in light.
  Controls on it (the collapse chevron) are plain `ghost` with a lucide icon
  in `currentColor`.
- `white`, `black`, `transparent`, `current` and `inherit` are allowed; use
  them only for overlays and imagery, not for text or surfaces.

## Components and their variants

### Button (`ui/button.tsx`)

| Prop      | Values                                                                                                                                                                                                                                                 |
| --------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `variant` | `default`, `secondary`, `outline`, `outline-primary`, `ghost`, `ghost-muted`, `ghost-destructive`, `ghost-on-accent`, `ghost-destructive-on-accent`, `link`, `destructive`, `destructive-outline`, `combobox`, `sidebar-item`, `tab`, `section-toggle` |
| `size`    | `xs`, `sm`, `default`, `lg`, `field`, `icon-xs`, `icon-sm`, `icon`, `icon-lg`, `inline`                                                                                                                                                                |
| `shape`   | `default` (rounded-md), `pill` (rounded-full, wider padding)                                                                                                                                                                                           |

- Round brand buttons (`rounded-3xl px-5`, `rounded-full px-6`): `shape="pill"`,
  plus `size="lg"` if they were `px-6`.
- Muted icon buttons (`text-muted-foreground hover:text-foreground`):
  `variant="ghost-muted"`.
- Icon actions that remove something (a trash can on a member or shared
  resource row) are `variant="ghost-destructive"`: muted at rest, red on
  hover, so the warning shows even where the click deletes without asking.
- Icon buttons on a row that is already `bg-accent` or `bg-sidebar-accent`
  while you point at it (a highlighted Command item, a card or tile with
  `hover:bg-accent`, a hovered sidebar row) are `variant="ghost-on-accent"`
  (delete: `ghost-destructive-on-accent`). They hover with a
  `foreground/15` (`destructive/15`) tint, which shows on accent where
  ghost's accent square would not.
- Icons are `lucide-react` at the default stroke (2). Don't pass
  `strokeWidth`, and don't use an `<img>` for a glyph lucide has.
- Bordered purple buttons (`border-primary text-primary hover:bg-primary`):
  `variant="outline-primary"`.
- Tiny inline actions (`h-auto px-2 py-1 text-xs`): `size="xs"`.
- A link inside running text (an artifact link in an answer) is
  `variant="link" size="inline"`: no height or padding, so it wraps with the
  sentence. Standalone links (toggles, crumbs) keep a normal size.
- The composer controls under the chat field (Attach, Voice, Tools,
  Sources) are `size="sm" shape="pill"`. Their icons are `size-3.5 sm:size-4`
  with no margin; the size's `gap-1.5` spaces them, and the label span keeps
  `text-xs sm:text-sm` so the row still fits on a phone.
- Popover comboboxes (`role="combobox"` + `Command`) use `variant="combobox"`,
  which matches `SelectTrigger`: card fill, normal weight, and muted text
  while `data-placeholder` is set (`data-placeholder={value ? undefined : ''}`).
  Pass only layout (`w-full justify-between`) and keep the chevron as the
  last child.
- A button or picker that sits in a row of fields is `size="field"`: 42px.
  `Input` and `SelectTrigger` take `size="field"` too (the same 42px as
  Input `default` and SelectTrigger `lg`), so a form column has one name for
  one height; prefer `field` in new form rows. With `shape="pill"` its text starts 21px in, like
  the Input and Select pills beside it. The agent form's pickers are
  `combobox field pill`, its Add button `outline-primary field pill`.
- Rows in the navigation sidebar (`hover:bg-sidebar-accent … pl-3 gap-2.5
rounded-3xl`) are `variant="sidebar-item"`: left-aligned, full-radius, normal
  weight, `bg-sidebar-accent` on hover and while `aria-current="page"`. Use it
  with `asChild` around a `<Link>` for navigation rows.
- Inline disclosure toggles ("Advanced settings", "Show advanced options")
  are `variant="link" size="sm"` with only `-ml-3 w-fit justify-start`;
  a chevron, when the toggle has one, is a lucide `ChevronRight` (so it
  takes the link colour) as the first child.
- Underline tabs (FilePicker's My Files / Shared with Me, the agent page
  sub-nav) are `variant="tab"`: muted text on a transparent 2px bottom border,
  square corners, no hover fill. Mark the current tab with `data-active`, which
  gives it `foreground` text and a `primary` underline. Padding-free tabs (a
  sub-nav with `gap-6`) add `size="inline"`, which keeps 4px above the line;
  the row draws the 1px baseline, and `-mb-px` lays the underline over it.
  Use them for a row of route links (the agent sub-nav: a `<nav>` whose
  current link carries `aria-current="page"`). Tabs that switch a panel in
  place are `ui/tabs` with `variant="underline"` on `TabsList` and each
  `TabsTrigger`: the same pixels, plus `role="tablist"`/`"tab"`,
  `aria-selected` and arrow-key focus; wrap the panel in `TabsContent`
  (FilePicker's My Files / Shared with Me). The `default` variant is a pill
  tab, unused in the app.
- A section panel's disclosure header (NewAgent's Advanced and Guardrails
  panels) is `variant="section-toggle" size="sm"` with `-ml-3 w-fit
justify-start` and `aria-expanded`: a lucide `ChevronRight` first
  (`rotate-90` while open) in primary, then the foreground title, with a
  primary underline on hover. The button draws no focus ring; the panel does,
  so keyboard focus outlines the whole white block:
  `has-[[data-variant=section-toggle]:focus-visible]:ring-3 …:ring-ring/50
…:ring-inset` on the panel `<div>` (inset, because a scrolling column clips
  an outset ring). Status badges go beside the button, not inside it, or the
  hover underline runs under them.
- Drop `text-white` on default and destructive buttons; the foreground token
  already provides it. Drop `disabled:cursor-not-allowed` on buttons; the
  base disables pointer events. Fields are the other way round (see Focus,
  elevation and stacking: "Disabled").
- A button that is busy (saving, creating, testing) takes `loading`: it
  disables itself, sets `aria-busy`, and draws a 16px spinner over the label,
  which stays in the layout (invisible) so the width doesn't jump. Keep the
  idle label; never hand-place a `Spinner` in a button, swap the label for
  "Saving…", or pin a fixed width to stop the jump. The one exception is a
  button whose busy state says something the user needs: a progress figure
  (a connector's Sync shows "42%") or a mode (the composer's Voice button shows
  "Transcribing"). It keeps its busy label with a spinning mark where its
  icon was: Sync uses `Spinner size="sm"` at icon size (`size-4`); Voice still
  spins lucide's `LoaderCircle`.

### Card (`ui/card.tsx`)

| Prop          | Values                                                                                                                                                        |
| ------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `variant`     | `outline` (border + card surface, the default), `filled` (muted fill, no border, for tiles on a card-coloured page), `subtle` (border on the page background) |
| `padding`     | `none`, `sm` (p-3, stat tiles and panels), `default` (p-4), `lg` (p-6)                                                                                        |
| `interactive` | whole card is the target: hover, focus ring and `selected` highlight; pair with `asChild` around a `<button>` or `<Link>`                                     |

Parts: `CardHeader` (title left, `CardAction` top-right), `CardTitle`,
`CardDescription`, `CardContent`, `CardFooter` (meta row, sticks to the
bottom). One radius for every card (`rounded-2xl`); pass only layout and
`gap-*` on `Card`. Replaces every hand-rolled
`rounded-(md|lg|xl|2xl|3xl|4xl) border bg-(card|muted) p-*` box: source and
tool tiles, team and agent cards, analytics stat tiles and chart panels,
source-type and agent-type picker tiles.

### OptionCard (`ui/option-card.tsx`)

The picker tile: a whole-card `<button>` with an icon in a tinted square, a
title and an optional description; `selected` fills the icon square and
outlines the card. Use it wherever the user picks one of several ways to
proceed (agent type, source type). Title-only tiles keep the same layout.
Pass `selected` (true or false) only in a
single-select picker inside a `role="radiogroup"`; the tile is then a radio.
Tiles that advance a step or navigate (Upload's source types, the agent-type
modal) leave it out and stay plain buttons. Only layout classes on it.

### Badge (`ui/badge.tsx`)

`variant`: `default` (brand), `neutral`, `success`, `warning`, `destructive`,
`info`, `outline`. Replaces every hand-rolled
`rounded-full bg-<colour>-100 px-2 py-0.5 text-xs text-<colour>-700 dark:...`
pill, including schedule and run status pills. HTTP method pills take their variant from
`getMethodBadgeVariant` (`utils/httpMethodColors.ts`): GET `success`, POST
`info`, PUT `warning`, DELETE `destructive`, PATCH `default`, anything else
`neutral`. `MultiSelect` (`ui/multi-select.tsx`) shows its first two picks as
`default` Badges with a remove X, then "+N more", on a `Button
variant="combobox" size="field"` trigger that grows past 42px when the chips
wrap.

### Input (`ui/input.tsx`)

| Prop      | Values                                                                                                |
| --------- | ----------------------------------------------------------------------------------------------------- |
| `size`    | `sm` (h-8), `default` (h-10.5, the historical 42px), `lg` (h-12), `field` (h-10.5, the form-row name) |
| `shape`   | `default`, `pill`                                                                                     |
| `variant` | `default`, `bare` (no border, padding, radius, shadow or ring), `filled` (card fill)                  |

Text alignment classes (`text-right`) and `font-mono` (code fields) are
allowed on Input and Textarea. A floating
`label` sits on the field's border, so its background must match the surface
behind the field: `labelSurface` is `card` (default, forms in cards and
modals), `background` (fields straight on a page) or `muted` (fields on a
muted panel). Never pass a background class for it. The chat and hero
fields (`rounded-3xl px-5 py-3`) are `size="lg" shape="pill"`. A
default-size pill (42px, the form-row height) pads `px-5` like the large
one, so its text lines up with the Select pills. Compact table
filters (`h-auto px-2 py-1 text-sm`) are `size="sm"`. An inset icon (a
search glass) is `leftIcon`, with or without a `label`; it pads the field
`pl-10`, so never hand-place an icon over an Input. A field inside a host
that already draws the frame (the renaming sidebar row, a search strip in a
bordered panel) is `variant="bare"`; the host shows focus, and any inset
padding goes on the host, not the field. A field on a muted panel (the
ImportSpec Base URL box) is `variant="filled"`, so it keeps the card fill
instead of showing the panel through; never pass `bg-card` for it.

### SelectTrigger (`ui/select.tsx`)

`size`: `sm` (32px), `default` (36px), `lg` (42px), `field` (42px, the
form-row name); `variant`: `default`, `ghost`; `shape`: `default`, `pill`.
Pills pad `px-5` at every size but `sm` (`px-3`), so their text starts 21px
in like the Input and Button field pills. The large rounded selects
(`rounded-3xl px-5 py-3`) are `size="lg" shape="pill"`.

### Textarea (`ui/textarea.tsx`)

`size`: `sm`, `default`, `lg` (rounded-2xl, for prompt editors); `resize`:
`none`, `vertical` (default), `both`. Same border, ring and invalid styling
as Input. `variant`: `default` (transparent), `filled` (card fill), with
the same rule as Input: a textarea on a muted panel is `variant="filled"`,
never `bg-card`. Three raw `<textarea>` elements stay, because each sits
under an overlay it must line up with: the chat composer, PromptTextArea's
variable highlighter and the chunk editor behind its line-number gutter.

### FormField (`ui/form-field.tsx`)

A labelled field is `<FormField label required hint error disabled>` with
the field as its only child. It stacks `Label`, the field, a muted `text-xs`
hint and a red `text-xs` error (`role="alert"`) 6px apart (`gap-1.5`), puts
the required star 4px after the label (`aria-hidden`; the field gets
`aria-required`, not native `required`), and dims the label while
`disabled`. `Input`, `Textarea`, `SelectTrigger` (even nested in `Select`),
`MultiSelect` and `Checkbox` read their `id`, `aria-invalid`, `aria-describedby`,
`aria-required` and `disabled` from it, so don't set those by hand; an id
the field already has wins. Any other control: pass `id` to FormField and
the same id to the control. One FormField holds one control: a second
field inside it (an "Add ref" box under a picker) needs its own `id`, or it
takes the field's. Popovers reset the wiring (`FormFieldBoundary`), so a
picker's search box is safe. There is one size: labels are `text-sm`
everywhere, also in dense panels (Guardrails). `className` is layout only.
Floating-label Inputs (`<Input label>`) label themselves and don't go in a
FormField. Never hand-build a `<label className="mb-2 block …">` or a
`div.flex-col` + `Label` + `<p>` stack.

### SettingRow (`ui/setting-row.tsx`)

A setting with a control on the right (a Switch, a short Input) is
`<SettingRow label description htmlFor alignStart as after>{control}</SettingRow>`,
grouped in `<SettingRows>`, which splits rows with `divide-border/50` and pads
each 12px (none at the group's ends). The title is a `Label` for the control
(`htmlFor` = the control's id), so every switch has a name and clicking the
title toggles it; `as="h2" | "h3"` keeps a heading tag, and the control then
needs its own `aria-label`. `alignStart` top-aligns the control for wrapping
descriptions. `after` holds a field that belongs to the row, 8px under it
(the agent form's limit Inputs). Inline "switch + label" pairs (a filter
toggle) are not SettingRows.

### Checkbox (`ui/checkbox.tsx`)

`<Checkbox checked onCheckedChange>` (Radix), never `<input type="checkbox">`:
native boxes take the OS accent and ignore dark mode. `size`: `default`
(16px, option rows), `sm` (14px, table cells). Unchecked it is an
`border-input` box; checked, `primary` with a `primary-foreground` check.
Name it with a `Label htmlFor` or `aria-label`. For an on/off setting with a
description use a Switch in a SettingRow instead.

### Tooltip (`ui/tooltip.tsx`)

`Tooltip` + `TooltipTrigger asChild` + `TooltipContent side`. Each tooltip
carries its own provider. Use it on every icon-only button and wherever a
`title=` attribute was standing in for a hint; keep `aria-label` on the
button as well.

### Spinner and Skeleton (`ui/spinner.tsx`, `ui/skeleton.tsx`)

`Spinner size="sm | default | lg"` draws in `currentColor`, so colour it
with a `text-*` token on it or its parent. `Skeleton` is a pulsing muted
block sized with layout classes and rounded as needed. Never put one inside
an element that pulses itself; the two animations multiply.

### Progress (`ui/progress.tsx`)

`value` 0 to 100, `variant`: `default`, `success`, `warning`,
`destructive`, `info`; `size`: `sm`, `default`, `lg`. Replaces the
width-percent divs in quota, indexing and guardrail views.

### Avatar (`ui/avatar.tsx`)

`size`: `none` (image decides, the default), `sm`, `default`, `lg`, `xl`;
`shape`: `none`, `circle`, `square`; `variant`: `default`, `primary` (brand
initials), `muted` (grey initials). Initials boxes pass the letters as
children.

### Dropzone (`ui/dropzone.tsx`)

`size`: `default` (tall target), `compact` (one row, for forms and modals).
Props: `onDrop`, `accept`, `multiple`, `maxFiles`, `maxSize`, `disabled`,
`title`, `description`, `icon`, `error`. Border and fill follow the drag
state through `data-drag-active` and `data-drag-reject`. Replaces every
hand-rolled `border-2 border-dashed rounded-3xl` target around
`useDropzone`; `components/FileUpload.tsx` keeps its preview and validation
logic and should render this underneath.

### Toast (`ui/toast.tsx`)

Feedback on anything the user did (uploads, runs, approvals, team events)
is a toast in the bottom-right stack, never an inline box. The app has one
`ToastViewport`, mounted in `App.tsx`; it is the live region
(`role="status"`, `aria-live="polite"`) and the fixed stack, so `Toast`
cards carry no role and no toast renders its own rail or positioning. Top
to bottom it holds `TeamNotificationToast`, `ToolApprovalToast`,
`UploadToast` and `ActionToast`, and it moves to the bottom-left while the
workflow Preview drawer is open. A new toast component returns only its
`Toast` cards and is added to that viewport. A page that reports the result
of an action (the admin Users actions) dispatches
`showActionToast({ variant: 'success' | 'destructive', message })` from
`notifications/actionToastSlice.ts`; `ActionToast` shows it and dismisses
it after 4.5s, and a new result replaces the previous one.

Compose `Toast` > `ToastHeader variant` (`default`, `success`, `warning`,
`destructive`, `info`) with `ToastTitle` and `ToastActions` (collapse and
close as `Button variant="ghost-muted" size="icon-sm"`), then
`ToastContent` (add `scrollable` for long lists) with `ToastItem label meta`
rows (optional `icon` before the label), a `ToastStatus status` circle per
row (`pending`, `success`, `warning`, `destructive`, `info`),
`ToastMessage variant` for an explanation and `ToastFooter` for action
buttons. `ToastTitle` truncates to one line; `wrap` lets a long title (a
localised string, a team name) wrap instead. `ToastMessage size` is `xs`
(default, the note under a row) or `sm` (`text-sm leading-4.5`, the whole
body of a notice). A message that is the only content under the header
gets its top padding on its own, and a message right after a `ToastItem`
shares that row's divider. Toasts own their width, radius and shadow; pass
no width or colour to them.

### Alert (`ui/alert.tsx`)

Inline notice inside a form or modal only, for something the user must
read before acting (an expiring token above the field, a warning in a
settings panel). Not for feedback on an action; that is a Toast.
`variant`: `default`, `success`, `warning`, `info`, `destructive`. Every
coloured variant is the same shape: `border-<role>/50 bg-<role>/10
text-<role>`, icon in the role colour; `default` sits on `bg-background`.
Icon first, then `AlertTitle` and `AlertDescription`. Every variant is
`role="alert"` except `success`, which is `role="status"` so a confirmation
is announced politely; pass `role` only to override that. Replaces the hand-rolled
`rounded-lg border bg-amber-50 text-amber-800` boxes.

### Breadcrumb (`ui/breadcrumb.tsx`)

`BreadcrumbPage`, the current crumb, is always one line and truncates with
an ellipsis. Pages pass only its width (`w-[16ch]`, `max-w-[32ch]`) and a
`title` with the full text; never `truncate` or typography. Give every
current crumb a width cap so a long name cannot push the row past the
screen. A crumb that runs a handler instead of navigating is
`BreadcrumbLink asChild` around a `<button type="button">`; the link carries
the focus ring. The current crumb is never a disabled button.

### Accordion (`ui/accordion.tsx`)

`AccordionTrigger` carries its own inset and type (`px-4 py-3 text-sm
font-medium`) and an inset focus ring, since `AccordionItem` clips anything
outside it. Pages pass nothing to the trigger; put the frame (a bordered,
rounded box) on a wrapper around `Accordion`.

### Modal, not Dialog

`ui/dialog.tsx` is the Radix primitive and is private to `ui/`; ESLint
rejects imports of it elsewhere. App code uses `Modal` (sizes `sm` to
`full`, `mobileVariant="sheet"`) or `CommandDialog`.

A modal's heading is its `title` (20px, `text-xl leading-tight
font-semibold`) and `description` (muted `text-sm`, 8px under the title).
Don't pass `hideTitle` to draw your own `<h2>`; `hideTitle` is only for
dialogs whose top line is not a title (MoveToFolderModal's breadcrumb,
Upload's step headings, ScheduleFormModal's editable name, the search
palette).

Buttons go in `footer`, never in `children`. The footer stacks full width on
phones (primary on top) and sits in a right-aligned row from `sm` up. The
standard pair is `footer={<ModalActions cancelLabel onCancel submitLabel
onSubmit pending disabled destructive />}`: a ghost Cancel and a primary
(or `destructive`) submit, both `size="lg" shape="pill"`; `pending` shows
the submit's `loading` spinner. A left-hand extra (Test connection) is
`footerStart`, and `submitProps` / `cancelProps` carry `type="submit"`,
`form` or a test id. A lone button is a `size="lg" shape="pill"` Button.

A search palette is `CommandDialog` on desktop. Pass cmdk options to its
inner `Command` through `commandProps` (`shouldFilter={false}` when results
come from a server search, a controlled `value`). On phones the same palette
goes in `Modal mobileVariant="sheet"` as `<Command variant="palette">`, which
gives it the dialog's 48px input row and row spacing, so both widths look
the same (`modals/SearchConversationsModal.tsx`). `CommandDialog` sits on
`DialogContent`, which has Modal's surface (`bg-card rounded-2xl
shadow-modal`, no border) and the same blurred overlay.

Every phone bottom sheet has one shape: `bg-card`, 16px top corners, no top
border, at most 90% of the viewport, and bottom padding that clears the iPhone
home indicator. `SheetContent side="bottom"` gives it with `pb-safe-0` (the
bare inset); pass `handle` for the grab bar, and `showCloseButton={false}`
when the handle is the only dismiss affordance besides the overlay.
`Modal mobileVariant="sheet"` shares the shape and the `SheetHandle`, with
`pb-safe` (the inset, at least 1rem) under its footer. `pb-safe` and
`pb-safe-0` are the `index.css` utilities for `env(safe-area-inset-bottom)`;
never spell `env()` in a class.

In a picker list, mark the item that is currently chosen with
`CommandItem checked` (a `secondary` brand tint through `data-checked`), not
with `bg-accent`: cmdk's own `data-selected` highlight is `bg-accent` and
follows the pointer and arrow keys, so an accent fill would look like hover.
While a checked item is also highlighted it keeps its tint and text and gains
a 1px inset `primary` ring, so the chosen row never turns plain grey.

### ActionMenu (`ui/dropdown-menu.tsx`)

The three-dots menu on a card, tile or row. Pass `options: MenuOption[]`
(`label`, `onClick`, optional lucide `icon`, `variant: 'destructive'`,
`disabled`) and a `triggerLabel`. It renders a `ghost-on-accent` `icon-xs`
trigger with `EllipsisVertical`, and stops clicks and keys on the trigger and
the menu from reaching the host, so it can sit inside a clickable card.
`className` takes layout only (position, margin) and lands on the trigger;
the menu is at least 144px wide and grows with its labels. `open`/`onOpenChange` make it controlled. Don't hand-build
this menu from `DropdownMenu`, and don't declare a local option type.

### Table, Label, dialog text

`TableCell` and `TableHeader` accept typography and alignment classes and
`text-muted-foreground`. `Label`, `DialogTitle`, `DialogDescription`,
`SheetTitle` and `SheetDescription` accept typography plus
`text-foreground` and `text-muted-foreground`. `DialogContent`,
`PopoverContent`, `SheetContent`, `DropdownMenuContent` and `Modal` accept
`p-0` for edge-to-edge content (MoveToFolderModal's banded folder picker);
Modal merges it after its own `p-8`, so no `!` is needed. Everything else on these components is layout only.
`MessageScrollerViewport` and `MessageScrollerContent` accept layout and
spacing: the primitive measures Content's padding-block for its scroll and
spacer math, and the Viewport's top gap must scroll with the messages, so
padding there cannot move to a margin or a wrapper.

## Spacing, type and radii

Use the Tailwind scale. Tailwind v4 accepts fractional steps, so
`h-10.5` is 42px and `ring-3` is a 3px ring; neither needs brackets. Layout
values (`h-[calc(100dvh-64px)]`, `max-w-[520px]`) and motion values
(`transition-[color,box-shadow]`, custom easings) are allowed. Font sizes,
padding, colours and radii in brackets are not; pick the nearest scale step
or add a token.

## Focus, elevation and stacking

- **Focus ring**: `focus-visible:ring-3 focus-visible:ring-ring/50` plus
  `focus-visible:border-ring` on fields. Never `focus:` (mouse users see it)
  and never `ring-2` or `ring-[3px]`; the `ui/` components already carry it,
  so plain elements should become components rather than copy the classes.
  Inside `ui/`, spell it with the `focusRing` constant from `lib/utils.ts`
  (with `invalidState` and `fieldFrame` for fields) rather than retyping it.
- **Close buttons** on Modal, Sheet and DialogContent are a `ghost-muted`
  `size="icon-sm"` Button (32px, accent square on hover) at `top-2 right-2`.
- **Disabled**: buttons (Button, Accordion, Tabs) use
  `disabled:pointer-events-none disabled:opacity-50`, so the pointer passes
  through. Fields (Input, SelectTrigger, Switch, Textarea, CommandInput,
  Label) use `disabled:cursor-not-allowed disabled:opacity-50` and never
  `pointer-events-none`, which would hide the cursor.
- **Elevation**: cards have no shadow; fields and outline buttons
  `shadow-xs`; popovers, menus and select lists `shadow-md`; sheets
  `shadow-lg`; modals (Modal and DialogContent) `shadow-modal`; toasts
  `shadow-toast`. The one exception is the Switch thumb, `shadow-lg`: a white
  knob on a white card needs the lift to read as raised. Nothing else uses
  a shadow class; accordions are panels and have none.
- **Stacking**: `z-10` sticky headers and table heads inside a page;
  `z-20` in-page floating chrome (banners, scroll-to-bottom, drag
  handles); `z-50` everything portalled (overlay, modal, sheet, popover,
  menu, tooltip); `z-200` only for select lists that must open above a
  modal. Do not invent values in between.

## Inline styles

Allowed without comment in `src/components/MermaidRenderer.tsx` and
`src/agents/workflow/nodes/**` (third-party renderers and canvas
positions). Elsewhere, prefer a CSS custom property
(`style={{ '--progress': pct }}` with `w-(--progress)`), and when a value
truly is computed at runtime, keep the inline style and add
`// eslint-disable-next-line shadcn/no-inline-styles -- <reason>`.

## Approved exceptions

Places where a rule is knowingly disabled. Each one carries the same reason
as a comment at the call site; add a row here when you add a disable so the
list stays reviewable.

| Where                                                               | Rule                            | Why                                                                                                                                                                                                                                                                                                                                                                                                                                                                                             |
| ------------------------------------------------------------------- | ------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `components/Notification.tsx`                                       | `shadcn/no-restyle`             | The promo banner's close X (`ghost icon-xs`) sits on the purple gradient. Any fill would be a grey square on it, so hover dims the icon instead (`hover:bg-transparent hover:opacity-70`, plus `dark:hover:bg-transparent` to beat ghost's dark hover), and `text-primary-foreground` keeps it white, because the button inherits the page colour. One user, so it isn't a variant.                                                                                                             |
| `components/ui/calendar.tsx`                                        | `shadcn/require-static-classes` | The day button merges `defaultClassNames.day`, which react-day-picker returns from `getDefaultClassNames()` at runtime; no static form exists.                                                                                                                                                                                                                                                                                                                                                  |
| `navigation/SidebarLevel.tsx`                                       | `shadcn/no-arbitrary-values`    | The incoming sidebar panel casts a strong shadow off its left edge while it slides (`shadow-[-12px_0_24px_-6px_rgba(0,0,0,0.45)]`); no scale shadow is horizontal, and the container clips it once the panel comes to rest.                                                                                                                                                                                                                                                                     |
| `components/MessageInput.tsx`                                       | `shadcn/no-restyle`             | The empty composer's send button is a grey circle (`bg-muted`, `dark:bg-accent`), not a faded brand one; no variant is neutral while disabled, and `secondary` is the brand-tinted pressed state.                                                                                                                                                                                                                                                                                               |
| `Hero.tsx`                                                          | `shadcn/no-restyle`             | The landing page's model picker keeps its hero look: a borderless muted pill at 16px (`rounded-4xl px-6 py-4 text-base`) whose menu hangs from it as one shape. Three disables: `SelectTrigger`, `SelectContent`, `SelectItem`.                                                                                                                                                                                                                                                                 |
| `agents/AgentsList.tsx`                                             | `shadcn/no-restyle`             | Inside a folder, the breadcrumb trail replaces the section `<h2>`, so its `BreadcrumbList` keeps heading typography (`text-foreground text-lg font-semibold gap-2`). It's the only breadcrumb that does.                                                                                                                                                                                                                                                                                        |
| `conversation/MarkdownAnswer.tsx`, `components/ArtifactSidebar.tsx` | `shadcn/no-inline-styles`       | SyntaxHighlighter's `style` prop is its Prism theme object (`oneLight` / `vscDarkPlus`), picked by theme at runtime. It is not CSS, so no class or custom property can replace it. One disable per file.                                                                                                                                                                                                                                                                                        |
| `agents/workflow/WorkflowPreview.tsx`                               | `shadcn/no-restyle`             | The Preview minimap's node rows are status tiles: the fill, border and ring follow the step (success, primary running + pulse, destructive, muted pending; a ring on the active row) and stay pinned on hover, pending and running rows stay unfaded while disabled, and clickable rows dim to 80% on hover. No Button variant is status-tinted. The rule reports each string inside `cn(...)`, so it's a `/* eslint-disable */` … `/* eslint-enable */` pair around the `className` attribute. |
| `agents/schedules/ScheduleFormModal.tsx`                            | `shadcn/no-restyle`             | The schedule's name is the dialog's editable title: a `bare` Input with title type (`text-xl font-semibold`), so the dialog passes `hideTitle`. One disable.                                                                                                                                                                                                                                                                                                                                    |
| `components/MermaidRenderer.tsx`                                    | `shadcn/no-restyle`             | The zoom − / + buttons sit on the diagram's `bg-black/70` overlay, where ghost's accent hover paints a light square with dark text; they hover to `white/20` with white text instead (`dark:hover:bg-white/20` too, to beat ghost's dark hover). Two disables.                                                                                                                                                                                                                                  |

Note that a multi-line reason has to be a `/* ... */` block comment;
consecutive `//` lines only disable the next comment line, not the code.

## Known dead classes

The lint reports classes Tailwind cannot generate. In this codebase they are
bugs, not missing configuration:

- `xs:` has never been a breakpoint here (not in the old Tailwind v3 config
  either), so `xs:px-3`, `xs:text-xs` never applied. Remove them rather than
  declaring the breakpoint, which would change layouts that were never seen.
- `text-s`, `dark:text-gray`, `w-inherit` are typos for `text-sm`,
  `dark:text-gray-*` and `w-[inherit]`.
- `agents-container`, `conversations-container`, `loader` and `mermaid` are
  unused hooks; nothing selects them. Before deleting a class like these,
  grep for it in `querySelector` and `classList` calls too. `star` was
  defined at runtime by a `<style>` element in `components/Notification.tsx`;
  it is now the `notification-star` utility in `src/index.css`. `msc-spacer`
  was a lookup hook for `ConversationMessages`' `querySelector`; the lookup
  now uses the primitive's `[data-message-scroller-spacer]` attribute.

## Live style guide

`npm run dev`, then open `/design`. The page (`src/design/DesignSystem.tsx`)
renders every `ui/` component with the variants above, shows the resolved
value of each colour token and has a theme toggle. It is registered only
when Vite runs in development mode, so it never ships. When you add a
variant or token, add it there too.

## Cleanup playbook

The design lint is at `warn` while the app is migrated. Work one file at a
time, smallest first, and keep every step green.

1. **See the state.** `npm run lint:design` prints warnings by rule and the
   worst files. `npm run lint:design -- --file src/settings/Teams.tsx` lists
   every warning in one file with the fix the message proposes;
   `-- --rule no-raw-colors` lists files for one rule.
2. **Pick a file, read it whole**, then fix all of its design warnings in
   one pass. Map raw colours to tokens (table above), replace hand-rolled
   boxes, pills, tiles, spinners and dropzones with the `ui/` components,
   and move Button/Input/Select overrides onto `variant`, `size`, `shape`.
   Delete the `dark:` twin of every class you tokenise. Remove classes the
   lint calls unknown (`xs:*`, `text-s`, `dark:text-gray`, unused hooks).
3. **Do not restyle `ui/` components from a page.** If a treatment is used
   in more than one place and no variant fits, add the variant in the
   component file, add it to `src/design/DesignSystem.tsx`, and document it
   here. A one-off gets `// eslint-disable-next-line shadcn/<rule> -- reason`.
4. **Keep behaviour identical.** Same DOM order, same handlers, same
   translations (`t(...)` keys stay). Only classes and component choice
   change. Prettier with the Tailwind plugin reorders classes; run
   `npm run lint-fix` rather than fighting it.
5. **Verify per file**: `npx eslint <file>` (zero `shadcn/*` warnings),
   `npx tsc --noEmit -p tsconfig.json`, `npm test`, and look at the screen
   in the running app (`npm run dev`, then the page that renders the file)
   in both themes.
6. **Promote rules** in `eslint.config.js` from `warn` to `error` when
   `npm run lint:design -- --rule <rule>` reports zero, in this order:
   `no-unknown-classes`, `require-static-classes`, `no-inline-styles`,
   `no-arbitrary-values`, `no-raw-colors`, `no-restyle`.

Known traps:

- `npm run lint` also reports 187 pre-existing Prettier errors in nine
  files unrelated to design; `npm run lint-fix` clears them.
- Port 5173 may be held by another checkout; check the Vite banner shows
  this repo's path before trusting what you see.
- `components/SkeletonLoader.tsx` renders `Skeleton` in its table, logs,
  default and files layouts. Its analysis, dropdown, chunk-card and
  connected-state layouts, and the four tile mirrors, pulse their own
  surface, so they wait for the Card work. `components/FileUpload.tsx`
  keeps its logic but should render `Dropzone`. (`agents/schedules/StatusBadge.tsx`
  is a status→variant map over `Badge`, not a wrapper; keep it.)

## Working with the lint

```bash
cd frontend && npm run lint
```

All `shadcn/*` rules are `warn` while the backlog is cleaned up. Promote a
rule to `error` in `eslint.config.js` once `npm run lint` reports zero
warnings for it; the intended order is `no-unknown-classes`,
`require-static-classes`, `no-inline-styles`, `no-arbitrary-values`,
`no-raw-colors`, `no-restyle`. Add a variant or token only when a treatment
is used in more than one place and none of the existing ones fits; a single
special case gets a disable comment with a reason.
