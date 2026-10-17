import { guardUploadStall, UPLOAD_STALL_TIMEOUT_MS } from './uploadStallGuard';

class FakeXHR extends EventTarget {
  upload = new EventTarget();
  abort = vi.fn(() => {
    this.dispatchEvent(new Event('abort'));
    this.dispatchEvent(new Event('loadend'));
  });
}

const make = () => {
  const xhr = new FakeXHR();
  guardUploadStall(xhr as unknown as XMLHttpRequest);
  return xhr;
};

describe('guardUploadStall', () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it('aborts an upload that never reports progress', () => {
    const xhr = make();
    vi.advanceTimersByTime(UPLOAD_STALL_TIMEOUT_MS - 1);
    expect(xhr.abort).not.toHaveBeenCalled();
    vi.advanceTimersByTime(1);
    expect(xhr.abort).toHaveBeenCalledTimes(1);
  });

  it('lets a slow upload run while it keeps making progress', () => {
    const xhr = make();
    for (let i = 0; i < 5; i += 1) {
      vi.advanceTimersByTime(UPLOAD_STALL_TIMEOUT_MS - 1);
      xhr.upload.dispatchEvent(new Event('progress'));
    }
    expect(xhr.abort).not.toHaveBeenCalled();
  });

  it('gives the server a fresh window once the body is sent', () => {
    const xhr = make();
    vi.advanceTimersByTime(UPLOAD_STALL_TIMEOUT_MS - 1);
    xhr.upload.dispatchEvent(new Event('load'));
    vi.advanceTimersByTime(UPLOAD_STALL_TIMEOUT_MS - 1);
    expect(xhr.abort).not.toHaveBeenCalled();
    vi.advanceTimersByTime(1);
    expect(xhr.abort).toHaveBeenCalledTimes(1);
  });

  it('stops watching once the request settles', () => {
    const xhr = make();
    xhr.dispatchEvent(new Event('loadend'));
    vi.advanceTimersByTime(UPLOAD_STALL_TIMEOUT_MS * 2);
    expect(xhr.abort).not.toHaveBeenCalled();
  });
});
