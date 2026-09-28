// Class and markup rules from DESIGN.md that a `no-restricted-syntax`
// selector can check. `everywhereSelectors` apply to ui/ too; `pageSelectors`
// are about app code composing ui/ parts, so ui/ (which defines those parts)
// is exempt from them.

// A class token in a string: start of string, a space or a variant colon
// before it; a space or the end after it.
const cls = (body) => `/(^|[\\s:])${body}(\\s|$)/`;

const inStrings = (regex, message) =>
  [`Literal[value=${regex}]`, `TemplateElement[value.raw=${regex}]`].map(
    (selector) => ({ selector, message }),
  );

/** @type {{ selector: string, message: string }[]} */
export const everywhereSelectors = [
  ...inStrings(
    cls('break-all'),
    'break-all splits ordinary words mid-word. Use wrap-break-word for prose and wrap-anywhere for a long token (URL, id, email). See DESIGN.md "Typography roles".',
  ),
  ...inStrings(
    cls('rounded'),
    'Bare `rounded` is a fixed 4px, outside the radius scale. Use rounded-sm (6px, bars), rounded-md (8px) or the role radius in DESIGN.md "Radius by role".',
  ),
  ...inStrings(
    '/(^|[\\s:])(min|max)-\\[|\\[@media/',
    'No custom breakpoints (min-[…], max-[…], [@media…]). Phone / desktop is lg; sm and md only reflow content. See DESIGN.md "Breakpoints".',
  ),
  ...inStrings(
    '/(^|[\\s:])-?z-(?!(0|10|20|50|200|auto)(\\s|$))/',
    'z-index comes from the stacking layers: z-10 sticky headers, z-20 in-page floating chrome, z-50 overlays, z-200 portalled floating lists. See DESIGN.md "Stacking".',
  ),
  ...inStrings(
    '/(^|[\\s:-])(focus|focus-visible|focus-within):ring-2(\\s|$)/',
    'The focus ring is ring-3 ring-ring/50 on focus-visible (fields: focus-within on a frame the same way). ring-2 is only for selection rings. See DESIGN.md "Focus ring".',
  ),
  {
    selector:
      'ImportDeclaration[source.value="lucide-react"] > ImportSpecifier[imported.name=/^(Loader|Loader2|LoaderCircle)$/]',
    message:
      'A loader is <Spinner> (ui/spinner) or <LoadingState>, never a lucide loader icon. See DESIGN.md "Spinner and Skeleton".',
  },
];

/** @type {{ selector: string, message: string }[]} */
export const pageSelectors = [
  ...inStrings(
    cls('transition-all'),
    'Transition only the property that changes: transition-colors by default, transition-transform for chevrons, transition-shadow for a ring. See DESIGN.md "Motion".',
  ),
  ...inStrings(
    '/(^|[\\s:-])hover:scale-(?!x-|y-)/',
    'Hover is a fill, border or text-colour change, never a scale. See DESIGN.md "Motion".',
  ),
  ...inStrings(
    '/(^|[\\s:])bg-primary\\u002f10(\\s|$)/',
    'The brand soft fill is bg-secondary text-secondary-foreground, not bg-primary/10. See DESIGN.md "Colour tokens".',
  ),
  {
    selector:
      'JSXOpeningElement[name.name="input"] > JSXAttribute[name.name="type"][value.value="checkbox"]',
    message:
      'A checkbox is <Checkbox> (ui/checkbox); native boxes take the OS accent and ignore dark mode. See DESIGN.md "Checkbox".',
  },
  {
    selector:
      'JSXOpeningElement[name.name="Button"] > JSXAttribute[name.name="title"]',
    message:
      'An icon-only button is <IconButton label> (its tooltip is the label); a labelled Button needs no title. See DESIGN.md "Tooltip and IconButton".',
  },
  ...[
    'JSXOpeningElement[name.name="SheetContent"] > JSXAttribute[name.name="className"] Literal[value=/(^|[\\s:])(max-)?w-/]',
    'JSXOpeningElement[name.name="SheetContent"] > JSXAttribute[name.name="className"] TemplateElement[value.raw=/(^|[\\s:])(max-)?w-/]',
  ].map((selector) => ({
    selector,
    message:
      'A drawer\'s width comes from SheetContent size (default 384px, detail 576px, wide 800px), never a w-* or max-w-* class. See DESIGN.md "Modal, not Dialog".',
  })),
  {
    selector: 'JSXOpeningElement[name.name="table"]',
    message:
      'Every table is ui/table (Table, TableHead, TableRow…), never a raw <table>. See DESIGN.md "Table".',
  },
  ...[
    'JSXOpeningElement[name.name="a"] > JSXAttribute[name.name="className"] Literal[value=/(^|[\\s:])(underline|text-primary)(\\s|$)/]',
    'JSXOpeningElement[name.name="a"] > JSXAttribute[name.name="className"] TemplateElement[value.raw=/(^|[\\s:])(underline|text-primary)(\\s|$)/]',
  ].map((selector) => ({
    selector,
    message:
      'A link is <Button variant="link" size="inline" asChild> around the <a>, never a raw <a> styled as a link. See DESIGN.md "Button".',
  })),
];
