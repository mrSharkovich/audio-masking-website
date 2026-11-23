import { expect, it, vi } from 'vitest';
import { syntheticWav } from '../test/audio';
import { maskingTestNotice } from '../types/audio';
import { createHttpMaskingAdapter } from './httpMasking';

it('rejects an unmarked response and never substitutes the uploaded file', async () => {
  const fetcher = vi.fn<typeof fetch>(async () => Response.json({
    test_mode: true, masking_performed: true, notice: maskingTestNotice,
    mode: 'two-sided', selected_matrix: 64, applied_matrix: 64,
  }));
  const adapter = createHttpMaskingAdapter({ fetcher });
  expect(await adapter.run(syntheticWav(), 'success')).toEqual({
    status: 'error', message: 'Сервер вернул некорректный тестовый результат.',
  });
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
    expect(await pending).toEqual({ status: 'error', message: 'Истекло время ожидания тестовой обработки.' });
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
    status: 'error', message: 'Запрос тестовой обработки отменён.',
  });
});
