import { act, useState } from 'react';
import { createRoot, type Root } from 'react-dom/client';

import { type DraftedFields, useDraftedFields } from './useDraftedFields';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

type Field = 'name' | 'tools';
type Form = Record<Field, unknown>;

const harness: {
  drafted: DraftedFields<Field> | null;
  form: Form;
  setForm: (next: (prev: Form) => Form) => void;
} = { drafted: null, form: { name: '', tools: [] }, setForm: () => undefined };

function Harness() {
  const [form, setForm] = useState<Form>({ name: 'Old', tools: ['a'] });
  harness.form = form;
  harness.setForm = setForm;
  harness.drafted = useDraftedFields<Field>(form, (field, previous) =>
    setForm((prev) => ({ ...prev, [field]: previous })),
  );
  return null;
}

// A form whose tools are objects, compared by their ids.
const shaped: {
  drafted: DraftedFields<'tools'> | null;
  tools: { id: string }[];
  setTools: (tools: { id: string }[]) => void;
} = { drafted: null, tools: [], setTools: () => undefined };

function ShapedHarness() {
  const [tools, setTools] = useState<{ id: string }[]>([{ id: 'a' }]);
  shaped.tools = tools;
  shaped.setTools = setTools;
  shaped.drafted = useDraftedFields<'tools'>(
    { tools: tools.map((tool) => tool.id) },
    (_field, previous) => setTools(previous as { id: string }[]),
  );
  return null;
}

describe('useDraftedFields', () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(async () => {
    container = document.createElement('div');
    root = createRoot(container);
    await act(async () => root.render(<Harness />));
  });
  afterEach(async () => {
    await act(async () => root.unmount());
  });

  /** Write a value the way a draft does, and mark it. */
  const draft = async (field: Field, value: unknown) =>
    act(async () => {
      const previous = harness.form[field];
      harness.setForm((prev) => ({ ...prev, [field]: value }));
      harness.drafted!.mark(field, previous, value);
    });

  it('undoes one field back to its value before the draft', async () => {
    await draft('name', 'New');
    await draft('tools', ['a', 'b']);
    expect(harness.drafted!.fields).toEqual(['name', 'tools']);
    await act(async () => harness.drafted!.undo('name'));
    expect(harness.form).toEqual({ name: 'Old', tools: ['a', 'b'] });
    expect(harness.drafted!.isDrafted('name')).toBe(false);
    expect(harness.drafted!.isDrafted('tools')).toBe(true);
  });

  it('undoes a field drafted twice back to before the first draft', async () => {
    await draft('name', 'New');
    await draft('name', 'Newer');
    await act(async () => harness.drafted!.undo('name'));
    expect(harness.form).toEqual({ name: 'Old', tools: ['a'] });
    expect(harness.drafted!.fields).toEqual([]);
  });

  it('keeps the first previous value when the form holds another shape than it compares', async () => {
    await act(async () => root.render(<ShapedHarness />));
    const draftTools = async (ids: string[]) =>
      act(async () => {
        const previous = shaped.tools;
        const next = ids.map((id) => ({ id }));
        shaped.setTools(next);
        shaped.drafted!.mark('tools', previous, ids);
      });
    await draftTools(['a', 'b']);
    await draftTools(['a', 'b', 'c']);
    await act(async () => shaped.drafted!.undo('tools'));
    // Back to before the first draft, in the form's own shape.
    expect(shaped.tools).toEqual([{ id: 'a' }]);
  });

  it('drops the mark of a field the user then edits by hand', async () => {
    await draft('name', 'New');
    await act(async () =>
      harness.setForm((prev) => ({ ...prev, name: 'Typed' })),
    );
    expect(harness.drafted!.isDrafted('name')).toBe(false);
    // Undo has nothing to put back for it any more.
    await act(async () => harness.drafted!.undo('name'));
    expect(harness.form.name).toBe('Typed');
  });

  it('keeps a mark through a step the drafter writes, and leaves an unmarked field alone', async () => {
    await draft('name', 'New');
    await act(async () => {
      harness.setForm((prev) => ({ ...prev, name: 'Step', tools: ['x'] }));
      harness.drafted!.follow('name', 'Step');
      harness.drafted!.follow('tools', ['x']);
    });
    expect(harness.drafted!.fields).toEqual(['name']);
    await draft('name', 'Newer');
    await act(async () => harness.drafted!.undo('name'));
    expect(harness.form.name).toBe('Old');
  });

  it('clears only the marks whose values went with a save', async () => {
    await draft('name', 'New');
    await draft('tools', ['b']);
    // The save sent these; tools was drafted again while it was out.
    const saved = { ...harness.form };
    await draft('tools', ['c']);
    await act(async () => harness.drafted!.clear(saved));
    expect(harness.drafted!.fields).toEqual(['tools']);
    await act(async () => harness.drafted!.undo('tools'));
    expect(harness.form.tools).toEqual(['a']);
  });

  it('clears every mark and keeps the values (a save)', async () => {
    await draft('name', 'New');
    await act(async () => harness.drafted!.clear());
    expect(harness.drafted!.fields).toEqual([]);
    expect(harness.form.name).toBe('New');
  });
});
