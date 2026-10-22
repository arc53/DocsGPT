import { downloadBlob } from './browserUtils';

describe('downloadBlob', () => {
  afterEach(() => vi.restoreAllMocks());

  it('saves the blob under its file name through a link it then removes', () => {
    const blob = new Blob(['a,b'], { type: 'text/csv' });
    const create = vi
      .spyOn(URL, 'createObjectURL')
      .mockReturnValue('blob:mock');
    const revoke = vi
      .spyOn(URL, 'revokeObjectURL')
      .mockImplementation(() => {});
    const clicked: { href: string; download: string; attached: boolean }[] = [];
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function (
      this: HTMLAnchorElement,
    ) {
      clicked.push({
        href: this.href,
        download: this.download,
        attached: document.body.contains(this),
      });
    });

    downloadBlob(blob, 'docs-gaps.csv');

    expect(create).toHaveBeenCalledWith(blob);
    expect(clicked).toEqual([
      { href: 'blob:mock', download: 'docs-gaps.csv', attached: true },
    ]);
    expect(document.querySelector('a')).toBeNull();
    expect(revoke).toHaveBeenCalledWith('blob:mock');
  });

  it('lets the URL go even when the click throws', () => {
    vi.spyOn(URL, 'createObjectURL').mockReturnValue('blob:mock');
    const revoke = vi
      .spyOn(URL, 'revokeObjectURL')
      .mockImplementation(() => {});
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {
      throw new Error('blocked');
    });
    expect(() => downloadBlob(new Blob(['x']), 'x.txt')).toThrow('blocked');
    expect(revoke).toHaveBeenCalledWith('blob:mock');
    expect(document.querySelector('a')).toBeNull();
  });
});
