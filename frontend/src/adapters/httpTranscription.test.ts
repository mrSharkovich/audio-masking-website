import { expect, it, vi } from 'vitest';
import { waitFor } from '@testing-library/react';
import { createHttpTranscriptionAdapter } from './httpTranscription';
import { readBytes, syntheticWav } from '../test/audio';

const response = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });

it.each([['ru', 'gigaam-multi'], ['en', 'whisper']] as const)('sends file and %s only, validates server model', async (language, model) => {
  const fetcher = vi.fn().mockResolvedValue(response({ language, model, text: 'HTTP test text' }));
  const audio = syntheticWav();
  expect(await createHttpTranscriptionAdapter({ fetcher }).transcribe(audio, language)).toEqual({ status: 'success', value: 'HTTP test text' });
  const [url, options] = fetcher.mock.calls[0];
  expect(url).toBe('/api/asr/transcribe');
  expect(options.method).toBe('POST');
  expect([...options.body.keys()]).toEqual(['file', 'language']);
  expect(options.body.get('file').name).toBe(audio.name);
  expect(await readBytes(options.body.get('file'))).toEqual(await readBytes(audio));
  expect(options.body.get('language')).toBe(language);
  expect(options.headers).toBeUndefined();
});

it.each([400, 413, 415, 422, 503, 504, 502, 500])('handles HTTP %s without trusting error text or fake transcripts', async (status) => {
  const fetcher = vi.fn().mockResolvedValue(response({ error: { code: 'asr_unavailable', message: 'private/server/path' }, text: 'FAKE TEXT' }, status));
  const result = await createHttpTranscriptionAdapter({ fetcher }).transcribe(syntheticWav(), 'ru');
  expect(result.status).toBe(status === 503 ? 'unavailable' : 'error');
  expect(JSON.stringify(result)).not.toMatch(/private|FAKE/);
  expect(result).not.toHaveProperty('value');
});

it.each([['asr_busy', 'занято'], ['audio_preparation_unavailable', 'Преобразование'], ['asr_unavailable', 'ASR-модель']])('explains 503 %s', async (code, message) => {
  const fetcher = vi.fn().mockResolvedValue(response({ error: { code } }, 503));
  expect(await createHttpTranscriptionAdapter({ fetcher }).transcribe(syntheticWav(), 'en')).toMatchObject({ status: 'unavailable', message: expect.stringContaining(message) });
});

it('rejects missing text, wrong language/model and invalid JSON', async () => {
  for (const body of [{ language: 'ru', model: 'gigaam-multi' }, { language: 'en', model: 'whisper', text: 'Wrong' }, { language: 'ru', model: 'arbitrary', text: 'Wrong' }]) {
    const fetcher = vi.fn().mockResolvedValue(response(body));
    expect(await createHttpTranscriptionAdapter({ fetcher }).transcribe(syntheticWav(), 'ru')).toMatchObject({ status: 'error' });
  }
  const fetcher = vi.fn().mockResolvedValue(new Response('not JSON'));
  expect(await createHttpTranscriptionAdapter({ fetcher }).transcribe(syntheticWav(), 'ru')).toMatchObject({ status: 'error' });
});

it('preserves empty recognition as an empty answer', async () => {
  const fetcher = vi.fn().mockResolvedValue(response({ language: 'ru', model: 'gigaam-multi', text: '' }));
  expect(await createHttpTranscriptionAdapter({ fetcher }).transcribe(syntheticWav(), 'ru')).toMatchObject({ status: 'empty' });
});

it('checks actual WAV signature, rejects MP3 disguised as WAV and empty uploads', async () => {
  const fetcher = vi.fn();
  const adapter = createHttpTranscriptionAdapter({ fetcher });
  for (const file of [new File(['ID3 test'], 'looks.wav', { type: 'audio/wav' }), new File([], 'empty.wav')]) {
    expect(await adapter.transcribe(file, 'ru')).toMatchObject({ status: 'error' });
  }
  expect(fetcher).not.toHaveBeenCalled();
});

it('handles network errors without exposing exceptions', async () => {
  const fetcher = vi.fn().mockRejectedValue(new Error('private/network/path'));
  expect(await createHttpTranscriptionAdapter({ fetcher }).transcribe(syntheticWav(), 'ru')).toMatchObject({ status: 'error', message: expect.stringContaining('сервер запущен') });
});

it('times out and aborts a pending HTTP request', async () => {
  const fetcher = vi.fn(() => new Promise<Response>(() => {}));
  const result = await createHttpTranscriptionAdapter({ fetcher, timeoutMs: 100 }).transcribe(syntheticWav(), 'ru');
  expect(result).toMatchObject({ status: 'error', message: expect.stringContaining('Истекло время') });
  expect(fetcher.mock.calls).toHaveLength(1);
  expect((fetcher.mock.calls[0] as unknown as [string, RequestInit])[1].signal?.aborted).toBe(true);
});

it('propagates caller cancellation and supports pre-cancelled requests', async () => {
  const fetcher = vi.fn<typeof fetch>(() => new Promise<Response>(() => {}));
  const controller = new AbortController();
  const adapter = createHttpTranscriptionAdapter({ fetcher });
  const pending = adapter.transcribe(syntheticWav(), 'ru', controller.signal);
  await waitFor(() => expect(fetcher).toHaveBeenCalledOnce());
  controller.abort();
  expect(await pending).toMatchObject({ status: 'error', message: expect.stringContaining('отменён') });
  expect(fetcher.mock.calls[0][1]?.signal?.aborted).toBe(true);
  expect(await adapter.transcribe(syntheticWav(), 'ru', controller.signal)).toMatchObject({ status: 'error' });
  expect(fetcher).toHaveBeenCalledOnce();
});
