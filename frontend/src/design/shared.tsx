/**
 * Building blocks shared by every /design gallery section: the section
 * shell (id anchor, heading, intro) and the titled example frame.
 */

/** One gallery section: an anchor target with a heading and an intro line. */
export function Section({
  id,
  title,
  intro,
  children,
}: {
  id: string;
  title: string;
  intro: string;
  children: React.ReactNode;
}) {
  return (
    <section id={id} className="scroll-mt-24">
      <h2 className="text-foreground text-xl font-semibold">{title}</h2>
      <p className="text-muted-foreground mt-1 max-w-2xl text-sm">{intro}</p>
      <div className="mt-6 flex flex-col gap-8">{children}</div>
    </section>
  );
}

/** A titled demo on a card, with the usage snippet on the right. */
export function Example({
  title,
  code,
  children,
}: {
  title: string;
  code?: string;
  children: React.ReactNode;
}) {
  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h3 className="text-foreground text-sm font-medium">{title}</h3>
        {code ? (
          <code className="text-muted-foreground font-mono text-xs">
            {code}
          </code>
        ) : null}
      </div>
      <div className="border-border bg-card rounded-xl border p-6">
        {children}
      </div>
    </div>
  );
}
