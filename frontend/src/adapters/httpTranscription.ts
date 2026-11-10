import { asrConfigurations } from '../types/audio';
import type { OperationValue, TranscriptionAdapter } from '../types/audio';

const wavMessage = 'ASR принимает только WAV PCM 8/16/24/32 бит, mono/stereo, 8–192 кГц. MP3 и другие форматы пока не поддерживаются.';
const failure = (message: string): OperationValue<string> => ({ status: 'error', message });
const object = (value: unknown): value is Record<string, unknown> => typeof value === 'object' && value !== null;

function header(audio: Blob, signal: AbortSignal): Promise<ArrayBuffer> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    const abort = () => { reader.abort(); reject(new DOMException('Aborted', 'AbortError')); };
    reader.onload = () => { signal.removeEventListener('abort', abort); resolve(reader.result as ArrayBuffer); };
    reader.onerror = () => { signal.removeEventListener('abort', abort); reject(new Error('File read failed')); };
    reader.onabort = () => { signal.removeEventListener('abort', abort); reject(new DOMException('Aborted', 'AbortError')); };
    signal.addEventListener('abort', abort, { once: true });
    if (signal.aborted) { abort(); return; }
    reader.readAsArrayBuffer(audio.slice(0, 12));
  });
}

function httpError(status: number, body: unknown): OperationValue<string> {
  const code = object(body) && object(body.error) ? body.error.code : undefined;
  switch (status) {
    case 400: return failure('Некорректный запрос распознавания. Проверьте файл и язык.');
    case 413: return failure('Аудиофайл превышает допустимый размер загрузки.');
    case 415: return failure(wavMessage);
    case 422: return failure('Не удалось проверить аудиофайл или язык. Выберите непустой WAV и язык ru или en.');
    case 503:
      return { status: 'unavailable', message: code === 'asr_busy' ? 'Локальное распознавание занято. Повторите запрос позже.'
        : code === 'audio_preparation_unavailable' ? 'Преобразование WAV на сервере недоступно.'
          : 'Локальная ASR-модель пока не подключена или недоступна.' };
    case 504: return failure('Превышено время распознавания на сервере. Повторите запрос позже.');
    case 502: return failure('Не удалось получить результат локального распознавания. Проверьте доступность backend.');
    default: return failure('Сервер не смог выполнить распознавание. Повторите запрос позже.');
  }
}

export function createHttpTranscriptionAdapter({ timeoutMs = 180000, fetcher }: {
  timeoutMs?: number; fetcher?: typeof fetch;
} = {}): TranscriptionAdapter {
  return {
    async transcribe(audio, language, signal) {
      const controller = new AbortController();
      const abort = () => controller.abort();
      let timedOut = false;
      signal?.addEventListener('abort', abort, { once: true });
      if (signal?.aborted) controller.abort();
      const timer = setTimeout(() => { timedOut = true; controller.abort(); }, timeoutMs);
      let onAbort = () => {};
      const cancellation = new Promise<never>((_, reject) => {
        onAbort = () => reject(new DOMException('Aborted', 'AbortError'));
        controller.signal.addEventListener('abort', onAbort, { once: true });
        if (controller.signal.aborted) onAbort();
      });
      const send = async (): Promise<OperationValue<string>> => {
        if (!audio.size) return failure('Аудиофайл пуст. Выберите другую запись.');
        const bytes = new Uint8Array(await header(audio, controller.signal));
        const signature = String.fromCharCode(...bytes);
        if (bytes.length !== 12 || signature.slice(0, 4) !== 'RIFF' || signature.slice(8) !== 'WAVE') return failure(wavMessage);
        const form = new FormData();
        form.append('file', audio, audio instanceof File ? audio.name : 'audio.wav');
        form.append('language', language);
        const response = await (fetcher ?? fetch)('/api/asr/transcribe', {
          method: 'POST', body: form, signal: controller.signal,
        });
        let body: unknown;
        try { body = await response.json(); }
        catch { if (response.ok) return failure('Сервер вернул некорректный ответ распознавания.'); }
        if (!response.ok) return httpError(response.status, body);
        if (!object(body) || body.language !== language || body.model !== asrConfigurations[language].model || typeof body.text !== 'string') {
          return failure('Сервер вернул некорректный ответ распознавания.');
        }
        return body.text.trim() ? { status: 'success', value: body.text }
          : { status: 'empty', message: 'Распознавание завершено без текста.' };
      };
      try {
        return await Promise.race([send(), cancellation]);
      } catch {
        if (timedOut) return failure('Истекло время ожидания ответа backend. Повторите запрос позже.');
        if (controller.signal.aborted) return failure('Запрос распознавания отменён.');
        return failure('Не удалось связаться с локальным backend. Проверьте, что сервер запущен.');
      } finally {
        clearTimeout(timer);
        signal?.removeEventListener('abort', abort);
        controller.signal.removeEventListener('abort', onAbort);
      }
    },
  };
}
