import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

import { composeAnswers, type Question, QuestionCards } from './QuestionCards';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const QUESTIONS: Question[] = [
  {
    id: 'q1',
    text: 'Where should refunds go?',
    note: 'No ticketing tool is connected.',
    multi: false,
    options: [
      { id: 'a', label: 'Email support' },
      { id: 'b', label: 'Stop' },
    ],
  },
  {
    id: 'q2',
    text: 'Which knowledge?',
    note: null,
    multi: true,
    options: [
      { id: 'h', label: 'Help Center' },
      { id: 's', label: 'Shipping' },
    ],
  },
];

const setValue = (el: HTMLInputElement, value: string) => {
  Object.getOwnPropertyDescriptor(
    HTMLInputElement.prototype,
    'value',
  )!.set!.call(el, value);
  el.dispatchEvent(new Event('input', { bubbles: true }));
};

describe('QuestionCards', () => {
  let container: HTMLDivElement;
  let root: Root;
  const onAnswer = vi.fn();

  const render = (active: boolean) =>
    act(async () =>
      root.render(
        <QuestionCards
          questions={QUESTIONS}
          active={active}
          onAnswer={onAnswer}
        />,
      ),
    );

  beforeEach(async () => {
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
    await render(true);
  });
  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
    onAnswer.mockReset();
  });

  const card = (id: string) =>
    container.querySelector<HTMLElement>(`[data-question="${id}"]`)!;
  const control = (id: string, label: string) => {
    const labelEl = Array.from(card(id).querySelectorAll('label')).find(
      (el) => el.textContent === label,
    )!;
    return document.getElementById(labelEl.htmlFor)!;
  };
  const sendButton = () =>
    Array.from(container.querySelectorAll('button')).find(
      (b) => b.textContent === 'questions.sendAnswers',
    );

  it('asks a one-pick question as radios and a pick-any one as checkboxes', () => {
    const radios = card('q1').querySelector('[role="radiogroup"]')!;
    expect(radios.getAttribute('aria-label')).toBe('Where should refunds go?');
    // The two options, then Something else last.
    expect(radios.querySelectorAll('[role="radio"]')).toHaveLength(3);
    const boxes = card('q2').querySelectorAll('[role="checkbox"]');
    expect(boxes).toHaveLength(3);
    const labels = Array.from(card('q2').querySelectorAll('label')).map(
      (el) => el.textContent,
    );
    expect(labels).toEqual([
      'Help Center',
      'Shipping',
      'questions.somethingElse',
    ]);
    expect(card('q1').textContent).toContain('No ticketing tool is connected.');
  });

  it('sends every answer as one message, free text included', async () => {
    expect(sendButton()!.disabled).toBe(true);
    await act(async () => control('q1', 'Email support').click());
    await act(async () => control('q1', 'Stop').click());
    expect(control('q1', 'Email support').getAttribute('aria-checked')).toBe(
      'false',
    );
    await act(async () => control('q2', 'Help Center').click());
    await act(async () => control('q2', 'Shipping').click());
    expect(card('q2').querySelector('input')).toBeNull();
    await act(async () => control('q2', 'questions.somethingElse').click());
    const input = card('q2').querySelector('input')!;
    // Indented under its row, in line with the label.
    expect(input.closest('.pl-7')).not.toBeNull();
    await act(async () => setValue(input, 'Returns policy'));
    await act(async () => sendButton()!.click());
    expect(onAnswer).toHaveBeenCalledWith(
      'Where should refunds go? → Stop\n' +
        'Which knowledge? → Help Center, Shipping, Returns policy',
    );
  });

  it('sends from the free-text field with Enter', async () => {
    await act(async () => control('q1', 'questions.somethingElse').click());
    const input = card('q1').querySelector('input')!;
    await act(async () => setValue(input, 'To the shop'));
    // Enter that picks an IME candidate (Japanese, Chinese) doesn't send.
    await act(async () =>
      input.dispatchEvent(
        new KeyboardEvent('keydown', {
          key: 'Enter',
          bubbles: true,
          isComposing: true,
        }),
      ),
    );
    expect(onAnswer).not.toHaveBeenCalled();
    await act(async () =>
      input.dispatchEvent(
        new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }),
      ),
    );
    expect(onAnswer).toHaveBeenCalledWith(
      'Where should refunds go? → To the shop',
    );
  });

  it('shows an answered card plainly, with what was picked', async () => {
    await act(async () => control('q1', 'Email support').click());
    await render(false);
    expect(sendButton()).toBeUndefined();
    expect(container.querySelector('[role="radio"]')).toBeNull();
    expect(container.querySelector('[disabled]')).toBeNull();
    expect(card('q1').textContent).toContain('Where should refunds go?');
    expect(card('q1').textContent).toContain('Email support');
    expect(card('q1').textContent).not.toContain('Stop');
    expect(card('q2').textContent).toContain('questions.notAnswered');
  });
});

describe('QuestionCards, a typed answer', () => {
  let container: HTMLDivElement;
  let root: Root;
  const onAnswer = vi.fn();
  const TYPED: Question[] = [
    {
      id: 'q1',
      text: 'Which company is it for?',
      note: null,
      multi: false,
      options: [],
      placeholder: 'e.g. Meridian Freight',
    },
    { ...QUESTIONS[0], id: 'q2' },
  ];

  beforeEach(async () => {
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
    await act(async () =>
      root.render(
        <QuestionCards questions={TYPED} active onAnswer={onAnswer} />,
      ),
    );
  });
  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
    onAnswer.mockReset();
  });

  it('asks a question with no options as a text field', async () => {
    const card = container.querySelector<HTMLElement>('[data-question="q1"]')!;
    expect(card.querySelector('[role="radio"]')).toBeNull();
    const input = card.querySelector('input')!;
    expect(input.getAttribute('aria-label')).toBe('Which company is it for?');
    expect(input.placeholder).toBe('e.g. Meridian Freight');
    // Not indented: there is no option row to line up with.
    expect(input.closest('.pl-7')).toBeNull();
    await act(async () => setValue(input, 'Meridian Freight Group'));
    await act(async () =>
      input.dispatchEvent(
        new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }),
      ),
    );
    expect(onAnswer).toHaveBeenCalledWith(
      'Which company is it for? → Meridian Freight Group',
    );
  });

  it('shows the typed answer once answered', async () => {
    const input = container.querySelector<HTMLInputElement>(
      '[data-question="q1"] input',
    )!;
    await act(async () => setValue(input, 'Meridian'));
    await act(async () =>
      root.render(
        <QuestionCards questions={TYPED} active={false} onAnswer={onAnswer} />,
      ),
    );
    expect(container.querySelector('input')).toBeNull();
    expect(
      container.querySelector('[data-question="q1"]')!.textContent,
    ).toContain('Meridian');
  });
});

describe('composeAnswers', () => {
  it('skips questions with no answer', () => {
    expect(
      composeAnswers(QUESTIONS, { q2: { picked: ['s'], other: '  ' } }),
    ).toBe('Which knowledge? → Shipping');
    expect(composeAnswers(QUESTIONS, {})).toBe('');
  });
});

describe('QuestionCards, as the chat draws them', () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
  });
  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
  });

  it("labels the skip button with the caller's words", async () => {
    const onSkip = vi.fn();
    await act(async () =>
      root.render(
        <QuestionCards
          questions={QUESTIONS}
          active
          onAnswer={vi.fn()}
          onSkip={onSkip}
          skipLabel="Just answer"
        />,
      ),
    );
    const skip = Array.from(container.querySelectorAll('button')).find(
      (b) => b.textContent === 'Just answer',
    )!;
    await act(async () => skip.click());
    expect(onSkip).toHaveBeenCalled();
  });

  it('shows answers given from outside, and a chosen empty line', async () => {
    await act(async () =>
      root.render(
        <QuestionCards
          questions={QUESTIONS}
          active={false}
          onAnswer={vi.fn()}
          answers={{ q2: 'Shipping' }}
          emptyLabel="Skipped"
        />,
      ),
    );
    const card = (id: string) =>
      container.querySelector(`[data-question="${id}"]`)!.textContent;
    expect(card('q1')).toContain('Skipped');
    expect(card('q2')).toContain('Shipping');
    await act(async () =>
      root.render(
        <QuestionCards
          questions={QUESTIONS}
          active={false}
          onAnswer={vi.fn()}
          answers={{}}
          emptyLabel={null}
        />,
      ),
    );
    expect(card('q1')).toBe('1. Where should refunds go?');
  });
});
