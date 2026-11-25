import { expect, it, vi } from 'vitest';
import { syntheticWav } from '../test/audio';
import { maskingTestNotice } from '../types/audio';
import { createHttpMaskingAdapter } from './httpMasking';

it.each([
  { test_mode: true, masking_performed: true, notice: maskingTestNotice },
  { test_mode: false, masking_performed: false, notice: null },
  { test_mode: false, masking_performed: true, notice: maskingTestNotice },
  { masking_performed: true, notice: null },
])('rejects conflicting or incomplete result markers %j', async (flags) => {
  const fetcher = vi.fn<typeof fetch>(async () => Response.json({
    ...flags, mode: 'two-sided', selected_matrix: 64, applied_matrix: 64,
  }));
  const adapter = createHttpMaskingAdapter({ fetcher });
  expect(await adapter.run(syntheticWav(), 'success')).toEqual({
    status: 'error', message: 'Сервер вернул некорректный результат обработки.',
  });
});

it.each([
  [{ available: true, test_mode: false, notice: null }, 'real'],
  [{ available: true, test_mode: true, notice: maskingTestNotice }, 'test'],
  [{ test_mode: true, notice: maskingTestNotice }, 'test'],
  [{ available: false, test_mode: false, notice: null }, 'unavailable'],
  [{ available: false, test_mode: true, notice: maskingTestNotice }, 'unavailable'],
  [{ available: true, test_mode: false, notice: maskingTestNotice }, 'unavailable'],
  [{ test_mode: false, notice: null }, 'unavailable'],
])('interprets masking status %j as %s', async (body, expected) => {
  const fetcher = vi.fn<typeof fetch>(async () => Response.json(body));
  const adapter = createHttpMaskingAdapter({ fetcher });
  expect(await adapter.available?.(new AbortController().signal)).toBe(expected);
});

it('rejects an otherwise successful real result without both WAVs', async () => {
  const fetcher = vi.fn<typeof fetch>(async () => Response.json({
    test_mode: false, masking_performed: true, notice: null,
    mode: 'two-sided', selected_matrix: 64, applied_matrix: 16,
    masked: { file_name: 'masked.wav', media_type: 'audio/wav', base64: btoa('RIFF0000WAVE' + '\0'.repeat(44)) },
  }));
  expect((await createHttpMaskingAdapter({ fetcher }).run(syntheticWav(), 'success')).status).toBe('error');
});

it('aborts fetch when its timeout expires', async () => {
  vi.useFakeTimers();
  try {
    const fetcher = vi.fn<typeof fetch>((_input, init) => new Promise((_resolve, reject) => {
      init?.signal?.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')));
    }));
    const adapter = createHttpMaskingAdapter({ fetcher, timeoutMs: 20 });
    const pending = adapter.run(syntheticWav(), 'success');
    await vi.advanceTimersByTimeAsync(20);
    expect(fetcher.mock.calls[0][1]?.signal?.aborted).toBe(true);
    expect(await pending).toEqual({ status: 'error', message: 'Истекло время ожидания обработки.' });
  } finally {
    vi.useRealTimers();
  }
});

it('yields during a large WAV decode so cancellation can interrupt it', async () => {
  const controller = new AbortController();
  const data = {
    test_mode: true, masking_performed: false, notice: maskingTestNotice,
    mode: 'two-sided', selected_matrix: 64, applied_matrix: 64,
    masked: { file_name: 'test-masked.wav', media_type: 'audio/wav', base64: btoa('RIFF0000WAVE' + '\0'.repeat(300000)) },
    demasked: { file_name: 'test-demasked.wav', media_type: 'audio/wav', base64: btoa('RIFF0000WAVE' + '\0'.repeat(300000)) },
  };
  const response = Response.json(data);
  const parse = response.json.bind(response);
  vi.spyOn(response, 'json').mockImplementation(async () => {
    const body = await parse();
    setTimeout(() => controller.abort(), 0);
    return body;
  });
  const fetcher = vi.fn<typeof fetch>().mockResolvedValue(response);
  const adapter = createHttpMaskingAdapter({ fetcher });
  expect(await adapter.run(syntheticWav(), 'success', undefined, controller.signal)).toEqual({
    status: 'error', message: 'Запрос обработки отменён.',
  });
});
