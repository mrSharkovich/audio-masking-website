import { qualityMinimum, qualityScales } from '../adapters/httpQuality';
import type { MetricName } from '../types/audio';

export function qualityInterpretation(metric: MetricName, score: unknown) {
  const { max, visualMax } = qualityScales[metric];
  if (typeof score !== 'number' || !Number.isFinite(score) || score < qualityMinimum || score > max) return null;
  return {
    label: score >= visualMax ? 'Максимальное качество'
      : score < 2.5 ? 'Низкое качество' : score < 3.5 ? 'Среднее качество' : 'Высокое качество',
    hue: Math.min(1, (score - qualityMinimum) / (visualMax - qualityMinimum)) * 140,
  };
}
