import { maskingTestNotice, matrixSizes } from '../types/audio';
import type { AudioResult, MaskingAdapter, MatrixSize, OperationValue } from '../types/audio';

const object = (value: unknown): value is Record<string, unknown> => typeof value === 'object' && value !== null;
const failure = (message: string): OperationValue<AudioResult> => ({ status: 'error', message });

function httpError(status: number, body: unknown): OperationValue<AudioResult> {
  const code = object(body) && object(body.error) ? body.error.code : undefined;
  if (status === 503) return { status: 'unavailable', message:
    code === 'masking_busy' ? 'Тестовая обработка занята. Повторите запрос позже.'
      : code === 'audio_preparation_unavailable' ? 'Преобразование WAV на сервере недоступно.'
        : 'Тестовая обработка недоступна.' };
  if (status === 413) return failure('Аудиофайл превышает допустимый размер загрузки.');
  if (status === 415) return failure('Выберите непустой WAV PCM допустимой длительности.');
  if (status === 422) return failure('Проверьте файл WAV, режим и размер матрицы.');
  if (status === 504) return failure('Истекло время тестовой обработки на сервере.');
  return failure('Не удалось выполнить тестовую обработку.');
}

async function readWav(value: unknown, name: string, signal: AbortSignal): Promise<Blob> {
  if (!object(value) || value.file_name !== name || value.media_type !== 'audio/wav' || typeof value.base64 !== 'string') {
    throw new Error('Invalid WAV response');
  }
  const header = atob(value.base64.slice(0, 60));
  if (header.length < 44 || header.slice(0, 4) !== 'RIFF' || header.slice(8, 12) !== 'WAVE') {
    throw new Error('Invalid WAV response');
  }
  const parts: BlobPart[] = [];
  const chunkSize = 256 * 1024; // Keep Base64 groups whole and yield between chunks.
  for (let offset = 0; offset < value.base64.length; offset += chunkSize) {
    if (offset > 0) await new Promise<void>((resolve) => setTimeout(resolve, 0));
    signal.throwIfAborted();
    const decoded = atob(value.base64.slice(offset, offset + chunkSize));
    const bytes = new Uint8Array(decoded.length);
    for (let index = 0; index < bytes.length; index++) bytes[index] = decoded.charCodeAt(index);
    parts.push(bytes);
  }
  return new Blob(parts, { type: 'audio/wav' });
}

export function createHttpMaskingAdapter({ timeoutMs = 45000, fetcher }: {
  timeoutMs?: number; fetcher?: typeof fetch;
} = {}): MaskingAdapter {
  return {
    async available(signal) {
      try {
        const response = await (fetcher ?? fetch)('/api/masking/status', { signal, cache: 'no-store' });
        const body: unknown = response.ok ? await response.json() : null;
        return object(body) && body.test_mode === true && body.notice === maskingTestNotice;
      } catch { return false; }
    },
    async run(source, _outcome, options = { mode: 'two-sided', matrix: 64 }, signal) {
      const controller = new AbortController();
      const abort = () => controller.abort();
      signal?.addEventListener('abort', abort, { once: true });
      if (signal?.aborted) abort();
      let timedOut = false;
      const timer = setTimeout(() => { timedOut = true; abort(); }, timeoutMs);
      try {
        const form = new FormData();
        form.append('file', source);
        form.append('mode', options.mode);
        form.append('matrix', String(options.matrix));
        const response = await (fetcher ?? fetch)('/api/masking/process', {
          method: 'POST', body: form, signal: controller.signal,
        });
        controller.signal.throwIfAborted();
        const body: unknown = await response.json().catch(() => null);
        controller.signal.throwIfAborted();
        if (!response.ok) return httpError(response.status, body);
        if (!object(body) || body.test_mode !== true || body.masking_performed !== false || body.notice !== maskingTestNotice
          || body.mode !== options.mode || body.selected_matrix !== options.matrix
          || typeof body.applied_matrix !== 'number' || !matrixSizes.some((size) => size === body.applied_matrix)
          || body.applied_matrix > options.matrix) return failure('Сервер вернул некорректный тестовый результат.');
        const fileName = 'test-masked.wav';
        const demaskedFileName = 'test-demasked.wav';
        const audio = await readWav(body.masked, fileName, controller.signal);
        const demasked = await readWav(body.demasked, demaskedFileName, controller.signal);
        return { status: 'success', value: { id: crypto.randomUUID(), audio, fileName, demonstration: true,
          testMasking: { options, appliedMatrix: body.applied_matrix as MatrixSize, demasked, demaskedFileName } } };
      } catch {
        if (timedOut) return failure('Истекло время ожидания тестовой обработки.');
        if (controller.signal.aborted) return failure('Запрос тестовой обработки отменён.');
        return failure('Не удалось получить тестовый результат от локального backend.');
      } finally {
        clearTimeout(timer);
        signal?.removeEventListener('abort', abort);
      }
    },
  };
}
