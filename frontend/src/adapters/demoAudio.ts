import type {
  AudioAdapters, AudioResult, DemoOutcome, OperationValue,
  QualityResult, TranscriptSelection, TranscriptionResult,
} from '../types/audio';

// Independent synthetic fixture. No input audio bytes are read or transformed.
export function createDemoTone(): Blob {
  const sampleRate = 8000;
  const samples = sampleRate;
  const buffer = new ArrayBuffer(44 + samples * 2);
  const view = new DataView(buffer);
  const label = (offset: number, value: string) => {
    for (let i = 0; i < value.length; i++) view.setUint8(offset + i, value.charCodeAt(i));
  };
  label(0, 'RIFF'); view.setUint32(4, 36 + samples * 2, true);
  label(8, 'WAVE'); label(12, 'fmt '); view.setUint32(16, 16, true);
  view.setUint16(20, 1, true); view.setUint16(22, 1, true);
  view.setUint32(24, sampleRate, true); view.setUint32(28, sampleRate * 2, true);
  view.setUint16(32, 2, true); view.setUint16(34, 16, true);
  label(36, 'data'); view.setUint32(40, samples * 2, true);
  for (let i = 0; i < samples; i++) {
    const envelope = Math.min(i / 400, (samples - i) / 400, 1);
    view.setInt16(44 + i * 2, Math.sin(2 * Math.PI * 440 * i / sampleRate) * 1800 * envelope, true);
  }
  return new Blob([buffer], { type: 'audio/wav' });
}

const wait = (delay: number) => new Promise<void>((resolve) => setTimeout(resolve, delay));

export function createDemoAdapters(delay = 700): AudioAdapters {
  return {
    masking: {
      async run(_source: File, outcome: DemoOutcome): Promise<OperationValue<AudioResult>> {
        await wait(delay);
        if (outcome === 'unavailable') return { status: 'unavailable', message: 'Демонстрационный сценарий: маскирование недоступно.' };
        if (outcome === 'error') return { status: 'error', message: 'Демонстрационная ошибка. Исходник сохранён; попробуйте другой сценарий.' };
        return { status: 'success', value: {
          id: crypto.randomUUID(), audio: createDemoTone(),
          fileName: 'audiomask-demo-tone-not-masked.wav', demonstration: true,
        } };
      },
    },
    quality: {
      async evaluate(_resultId: string, outcome: DemoOutcome): Promise<QualityResult> {
        await wait(delay);
        if (outcome === 'error') return {
          PESQ: { status: 'error', message: 'Демонстрационная ошибка оценки.' },
          ViSQOL: { status: 'error', message: 'Демонстрационная ошибка оценки.' },
        };
        if (outcome === 'unavailable') return {
          PESQ: { status: 'unavailable', message: 'PESQ недоступен в выбранном сценарии.' },
          ViSQOL: { status: 'unavailable', message: 'ViSQOL недоступен в выбранном сценарии.' },
        };
        return {
          PESQ: { status: 'success', value: 3.2 },
          ViSQOL: outcome === 'partial'
            ? { status: 'unavailable', message: 'ViSQOL недоступен в демонстрационном примере.' }
            : { status: 'success', value: 3.8 },
        };
      },
    },
    transcription: {
      async transcribe(_resultId: string, selection: TranscriptSelection, outcome: DemoOutcome): Promise<TranscriptionResult> {
        await wait(delay);
        const sources = selection === 'both' ? ['original', 'masked'] as const : [selection];
        const response: TranscriptionResult = {};
        for (const source of sources) {
          if (outcome === 'unavailable' || (outcome === 'partial' && source === 'masked')) {
            response[source] = { status: 'unavailable', message: 'Транскрибация недоступна в демонстрационном сценарии.' };
          } else if (outcome === 'error') {
            response[source] = { status: 'error', message: 'Демонстрационная ошибка транскрибации.' };
          } else if (outcome === 'empty') {
            response[source] = { status: 'empty', message: 'Демонстрационный ответ без текста.' };
          } else {
            response[source] = { status: 'success', value: 'Демонстрационный текст для проверки интерфейса. Это не результат распознавания выбранной записи.' };
          }
        }
        return response;
      },
    },
  };
}
