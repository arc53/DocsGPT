// Card surface rule (DESIGN.md "Card surfaces"): a tile is `filled`, and
// nothing on a tile repeats its muted fill, or it disappears into it. The
// neutral Badge and the muted Avatar are `bg-muted-foreground/15`, a tint
// that shows on muted, so they are fine; a literal `bg-muted` is not. These
// are `no-restricted-syntax` entries; they see children written in the same
// JSX tree as the `<Card variant="filled">`, not ones a child component
// renders.

// `variant="filled"` or `variant={'filled'}`.
const FILLED_VARIANT =
  'JSXAttribute[name.name="variant"]:matches([value.value="filled"], [value.expression.value="filled"])';

const FILLED_CARD = `JSXElement:has(> JSXOpeningElement[name.name="Card"]:has(> ${FILLED_VARIANT}))`;

// `bg-muted` or `bg-muted/NN`, with any variant prefix, but not
// `bg-muted-foreground`.
const BG_MUTED = '/(^|[\\s:])bg-muted([^-a-z]|$)/';

/** @type {{ selector: string, message: string }[]} */
export const cardSurfaceSelectors = [
  {
    selector: `${FILLED_CARD} JSXElement > JSXOpeningElement[name.name="Card"] > ${FILLED_VARIANT}`,
    message:
      'A filled Card inside a filled Card is a fill on a fill. A well inside a tile needs a panel around it, or none. See DESIGN.md "Card surfaces".',
  },
  ...[
    `${FILLED_CARD} JSXElement JSXAttribute[name.name="className"] Literal[value=${BG_MUTED}]`,
    `${FILLED_CARD} JSXElement JSXAttribute[name.name="className"] TemplateElement[value.raw=${BG_MUTED}]`,
  ].map((selector) => ({
    selector,
    message:
      'bg-muted inside a filled tile is a fill on a fill and disappears. Drop the fill (use a Separator or border-border for structure). See DESIGN.md "Card surfaces".',
  })),
  {
    selector: `${FILLED_CARD} JSXOpeningElement[name.name="Skeleton"]:not(:has(JSXAttribute[name.name="surface"]))`,
    message:
      'Skeleton bars on a filled tile need surface="muted", or they vanish into the fill. See DESIGN.md "Skeleton".',
  },
];
