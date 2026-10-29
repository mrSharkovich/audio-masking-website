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
  demonstration: true;
}

export type MetricName = 'PESQ' | 'ViSQOL';
export type QualityResult = Record<MetricName, OperationValue<number>>;
export type TranscriptSource = 'original' | 'masked';
export type TranscriptSelection = TranscriptSource | 'both';
export type TranscriptionResult = Partial<Record<TranscriptSource, OperationValue<string>>>;

export interface MaskingAdapter {
  run(source: File, outcome: DemoOutcome): Promise<OperationValue<AudioResult>>;
}
export interface QualityAdapter {
  evaluate(resultId: string, outcome: DemoOutcome): Promise<QualityResult>;
}
export interface TranscriptionAdapter {
  transcribe(resultId: string, selection: TranscriptSelection, outcome: DemoOutcome): Promise<TranscriptionResult>;
}
export interface AudioAdapters {
  masking: MaskingAdapter;
  quality: QualityAdapter;
  transcription: TranscriptionAdapter;
}
