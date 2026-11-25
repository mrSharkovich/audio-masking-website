import type { MetricName, QualityResult } from '../types/audio';

export const qualityMetrics = ['PESQ', 'ViSQOL', 'ViSQOL_LATTICE'] as const;
export const qualityMinimum = 1;
export const qualityScales = {
  PESQ: { max: 4.65, visualMax: 4.643888, label: 'PESQ' },
  ViSQOL: { max: 5, visualMax: 5, label: 'ViSQOL' },
  ViSQOL_LATTICE: { max: 5, visualMax: 5, label: 'ViSQOL с lattice' },
} as const;
export const qualityComparisons = ['masked', 'demasked', 'masked_demasked'] as const;
export type QualityComparison = typeof qualityComparisons[number];
const pairRecordings = {
  masked: ['original', 'masked'],
  demasked: ['original', 'demasked'],
  masked_demasked: ['masked', 'demasked'],
} as const;
export type QualityRecordings = Record<'original' | 'masked' | 'demasked', Blob>;
export type QualityScores = Partial<Record<QualityComparison, QualityResult>>;
export type QualityAvailability = Record<MetricName, { status: 'available' | 'unavailable' | 'error'; message?: string }>;
export type QualityProbe = QualityAvailability | 'checking' | 'error';

export interface QualityEvaluationAdapter {
  status(signal: AbortSignal): Promise<QualityAvailability>;
  evaluate(recordings: QualityRecordings, pairs: readonly QualityComparison[], signal: AbortSignal): Promise<QualityScores>;
}

function object(value: unknown): Record<string, unknown> {
  return typeof value === 'object' && value !== null ? value as Record<string, unknown> : {};
}

const invalidResult = { status: 'error', message: 'Сервер вернул некорректный результат.' } as const;

function score(value: unknown, metric: MetricName): QualityResult[MetricName] {
  const item = object(value);
  if (item.status === 'success' && typeof item.value === 'number' && Number.isFinite(item.value)
      && item.value >= qualityMinimum && item.value <= qualityScales[metric].max) {
    return { status: 'success', value: item.value };
  }
  if ((item.status === 'error' || item.status === 'unavailable') && typeof item.message === 'string' && item.message) {
    return { status: item.status, message: item.message };
  }
  return invalidResult;
}

async function request(path: string, init: RequestInit) {
  let response: Response;
  try {
    response = await fetch(`/api/quality/${path}`, { ...init, cache: 'no-store' });
  } catch {
    throw new Error('Не удалось связаться с локальным сервисом оценки качества.');
  }
  const body: unknown = await response.json().catch(() => null);
  if (!response.ok) {
    const failure = object(object(body).error);
    throw new Error(typeof failure.message === 'string' ? failure.message : 'Сервис оценки качества недоступен.');
  }
  return object(body);
}

export const httpQuality: QualityEvaluationAdapter = {
  async status(signal) {
    const body = await request('status', { signal });
    const metrics = object(body.metrics);
    const read = (metric: MetricName): QualityAvailability[MetricName] => {
      const item = object(metrics[metric]);
      return item.status === 'available' ? { status: 'available' } : {
        status: item.status === 'unavailable' ? 'unavailable' : 'error',
        message: typeof item.message === 'string' ? item.message : 'Не удалось проверить доступность метрики.',
      };
    };
    return { PESQ: read('PESQ'), ViSQOL: read('ViSQOL'), ViSQOL_LATTICE: read('ViSQOL_LATTICE') };
  },
  async evaluate(recordings, pairs, signal) {
    const form = new FormData();
    for (const pair of pairs) form.append('pairs', pair);
    for (const name of new Set(pairs.flatMap((pair) => pairRecordings[pair]))) {
      form.append(name, recordings[name], `${name}.wav`);
    }
    const body = await request('evaluate', { method: 'POST', body: form, signal });
    const comparisons = object(body.comparisons);
    const read = (name: QualityComparison): QualityResult => {
      const pair = object(comparisons[name]);
      return { PESQ: score(pair.PESQ, 'PESQ'), ViSQOL: score(pair.ViSQOL, 'ViSQOL'),
        ViSQOL_LATTICE: score(pair.ViSQOL_LATTICE, 'ViSQOL_LATTICE') };
    };
    return Object.fromEntries(pairs.map((pair) => [pair, read(pair)]));
  },
};
