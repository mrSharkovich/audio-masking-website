export type DemoOutcome = 'success' | 'error' | 'unavailable' | 'partial' | 'empty';
export type OperationValue<T> =
  | { status: 'success'; value: T }
  | { status: 'error' | 'unavailable' | 'empty'; message: string };

export interface DemoSettings {
  enabled: boolean;
  masking: DemoOutcome;
  quality: DemoOutcome;
  transcription: DemoOutcome;
}

export interface AudioResult {
  id: string;
  audio: Blob;
  fileName: string;
  demonstration: boolean;
  testMasking?: MaskingDetails;
  masking?: MaskingDetails;
}

interface MaskingDetails {
  options: MaskingOptions;
  appliedMatrix: MatrixSize;
  demasked: Blob;
  demaskedFileName: string;
}

export const matrixSizes = [4, 8, 16, 32, 64, 128, 256, 512] as const;
export type MatrixSize = typeof matrixSizes[number];
export interface MaskingOptions {
  mode: 'one-sided' | 'two-sided';
  matrix: MatrixSize;
}
export const maskingTestNotice = 'Тестовый режим. Маскирование не выполняется. Аудиофайлы возвращаются без изменения звучания';

export type MetricName = 'PESQ' | 'ViSQOL';
export type QualityResult = Record<MetricName, OperationValue<number>>;
export type TranscriptSource = 'original' | 'masked' | 'demasked';
export type TranscriptSelection = TranscriptSource | 'both';
export type AudioLanguage = 'ru' | 'en';
export type AsrConfiguration =
  | { language: 'ru'; model: 'gigaam-multi' }
  | { language: 'en'; model: 'whisper' };
export const asrConfigurations = {
  ru: { language: 'ru', model: 'gigaam-multi' },
  en: { language: 'en', model: 'whisper' },
} as const satisfies Record<AudioLanguage, AsrConfiguration>;
export type TranscriptionResult = Partial<Record<TranscriptSource, OperationValue<string>>>;

export interface MaskingAdapter {
  available?(signal: AbortSignal): Promise<boolean>;
  run(source: File, outcome: DemoOutcome, options?: MaskingOptions, signal?: AbortSignal): Promise<OperationValue<AudioResult>>;
}
export interface QualityAdapter {
  evaluate(resultId: string, outcome: DemoOutcome): Promise<QualityResult>;
}
export interface TranscriptionAdapter {
  transcribe(audio: Blob, language: AudioLanguage, signal?: AbortSignal): Promise<OperationValue<string>>;
}
export interface AsrMaskedAudio {
  audio: Blob;
  fileName: string;
  demonstration: boolean;
  testMasking?: AudioResult['testMasking'];
}
export interface DemoTranscriptionAdapter {
  transcribe(resultId: string, selection: TranscriptSelection, outcome: DemoOutcome, configuration: AsrConfiguration): Promise<TranscriptionResult>;
}
export type DemoAudioAdapters = Omit<AudioAdapters, 'transcription'> & { transcription: DemoTranscriptionAdapter };
export interface AudioAdapters {
  masking: MaskingAdapter;
  quality: QualityAdapter;
  transcription: TranscriptionAdapter;
}
