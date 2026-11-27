import { DRAFTER_STARTERS, starterQuestions } from './starters';

const t = (key: string) => key;

describe('starterQuestions', () => {
  it('asks every starting point something, shaped as a drafter round', () => {
    for (const { key } of DRAFTER_STARTERS) {
      const questions = starterQuestions(key, t);
      expect(questions.length).toBeGreaterThan(0);
      for (const question of questions) {
        expect(question.text).toBe(
          `drafter.starters.${key}.ask.${question.id}.text`,
        );
        expect(question.note).toBeNull();
        // A typed answer has a placeholder and is never pick-any.
        if (question.options.length === 0) {
          expect(question.placeholder).toBeTruthy();
          expect(question.multi).toBe(false);
        }
      }
    }
  });

  it('asks a website chat for the company as a typed answer', () => {
    expect(starterQuestions('website', t)).toEqual([
      {
        id: 'company',
        text: 'drafter.starters.website.ask.company.text',
        note: null,
        multi: false,
        options: [],
        placeholder: 'drafter.starters.website.ask.company.placeholder',
      },
    ]);
  });

  it('offers a helpdesk its areas as pick-any options', () => {
    const [areas] = starterQuestions('helpdesk', t);
    expect(areas.multi).toBe(true);
    expect(areas.options.map((option) => option.id)).toEqual([
      'hr',
      'it',
      'policies',
      'office',
    ]);
  });
});
