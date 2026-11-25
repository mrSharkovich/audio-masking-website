import { useEffect, useRef, useState } from 'react';
import type { CSSProperties } from 'react';
import { httpQuality, qualityComparisons, qualityMetrics, qualityScales } from '../adapters/httpQuality';
import type { QualityComparison, QualityEvaluationAdapter, QualityProbe, QualityRecordings, QualityScores } from '../adapters/httpQuality';
import { QualityInfo } from './QualityInfo';
import { qualityInterpretation } from './qualityInterpretation';
import { SaveFileButton } from './SaveFileButton';

const pairTitles = {
  masked: 'Исходная ↔ Маскированная',
  demasked: 'Исходная ↔ Демаскированная',
  masked_demasked: 'Маскированная ↔ Демаскированная',
};
const exportPairs = {
  masked: ['original', 'masked'],
  demasked: ['original', 'demasked'],
  masked_demasked: ['masked', 'demasked'],
} as const;
type RecordingNames = Partial<Record<keyof QualityRecordings, string>>;
const formatScore = (value: number) => value.toLocaleString('ru-RU', { maximumFractionDigits: 3 });

function markdownCell(value: string) {
  return value.replace(/[\r\n]+/g, ' ').replaceAll('&', '&amp;').replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;').replace(/[\\|`*_[\]~]/g, '\\$&');
}

function qualityReport(scores: QualityScores, names: RecordingNames | undefined, testMode: boolean) {
  const titles = {
    original: 'Исходная',
    masked: testMode ? 'Тестовая маскированная копия' : 'Маскированная',
    demasked: testMode ? 'Тестовая демаскированная копия' : 'Демаскированная',
  };
  const rows = qualityComparisons.map((pair) => {
    const comparison = exportPairs[pair].map((key) => names?.[key] ? `${titles[key]} (${names[key]})` : titles[key]).join(' — ');
    const cells = qualityMetrics.map((metric) => {
      const score = scores[pair]?.[metric];
      if (!score) return 'Не рассчитано';
      if (score.status === 'success') {
        return qualityInterpretation(metric, score.value) ? formatScore(score.value) : 'Ошибка: некорректная оценка';
      }
      return `${score.status === 'unavailable' ? 'Недоступно' : 'Ошибка'}: ${score.message}`;
    });
    return `| ${[comparison, ...cells].map(markdownCell).join(' | ')} |`;
  });
  return ['| Сравнение | PESQ | ViSQOL | ViSQOL с lattice |', '| --- | --- | --- | --- |', ...rows, ''].join('\n');
}

export function QualityPanel({ recordings, recordingNames, testMode, adapter = httpQuality, probe }: {
  recordings: QualityRecordings | null;
  recordingNames?: RecordingNames;
  testMode: boolean;
  adapter?: QualityEvaluationAdapter;
  probe?: QualityProbe;
}) {
  const hasFiles = Boolean(recordings?.original.size && recordings.masked.size && recordings.demasked.size);
  const active = useRef<AbortController | null>(null);
  const [localProbe, setLocalProbe] = useState<QualityProbe>('checking');
  const status = probe ?? localProbe;
  const checking = hasFiles && status === 'checking';
  const availability = typeof status === 'object' ? status : null;
  const [running, setRunning] = useState(false);
  const [selected, setSelected] = useState<QualityComparison[]>(['masked']);
  const [scores, setScores] = useState<QualityScores | null>(null);
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');

  useEffect(() => {
    if (!hasFiles || probe !== undefined) return;
    const controller = new AbortController();
    void adapter.status(controller.signal).then((result) => {
      if (!controller.signal.aborted) setLocalProbe(result);
    }).catch(() => {
      if (!controller.signal.aborted) setLocalProbe('error');
    });
    return () => controller.abort();
  }, [adapter, hasFiles, probe]);

  useEffect(() => () => {
    active.current?.abort();
    active.current = null;
  }, [adapter, hasFiles]);

  async function run() {
    if (!recordings || active.current || !selected.length) return;
    const controller = new AbortController();
    active.current = controller;
    setScores(null);
    setError('');
    setMessage('');
    setRunning(true);
    try {
      const result = await adapter.evaluate(recordings, selected, controller.signal);
      if (!controller.signal.aborted) setScores(result);
    } catch (failure) {
      if (!controller.signal.aborted) {
        setError(failure instanceof Error ? failure.message : 'Сервис оценки качества недоступен.');
      }
    } finally {
      if (active.current === controller) {
        active.current = null;
        setRunning(false);
      }
    }
  }

  function cancel() {
    active.current?.abort();
    active.current = null;
    setRunning(false);
    setMessage('Оценка отменена.');
  }

  return <section className="auxiliary-panel" aria-labelledby="quality-heading">
    <div className="panel-title"><span className="section-index" aria-hidden="true">03</span><h3 id="quality-heading">Оценка качества аудио</h3><QualityInfo />
      <SaveFileButton label="Сохранить оценки качества" filename="audiomask-quality.md" extension=".md"
        disabled={running} content={scores && Object.keys(scores).length ? () => qualityReport(scores, recordingNames, testMode) : undefined} />
    </div>
    <p>Метрики при 16 кГц оценивают качество звучания. Стойкость маскирования требует отдельной проверки.</p>
    {testMode ? <p className="result-notice">В тестовом режиме сравниваются копии аудио. Оценки не характеризуют работу настоящего алгоритма маскирования.</p> : null}
    {hasFiles ? <>
      <div className="quality-pairs" role="group" aria-label="Пары аудиозаписей">
        {qualityComparisons.map((pair) => <label key={pair}>
          <input type="checkbox" checked={selected.includes(pair)} disabled={running} onChange={(event) => {
            const checked = event.currentTarget.checked;
            setSelected((current) => qualityComparisons.filter((name) => name === pair ? checked : current.includes(name)));
            setScores(null);
            setError('');
            setMessage('');
          }} />
          {pairTitles[pair]}
        </label>)}
      </div>
      <div className="result-navigation">
        <button type="button" className="button secondary" disabled={checking || running || !selected.length} onClick={() => void run()}>
          {running ? 'Вычисляем оценки…' : 'Оценить качество'}
        </button>
        {running ? <button type="button" className="button secondary" onClick={cancel}>Отменить оценку</button> : null}
      </div>
    </> : <p>Для оценки нужны исходная, маскированная и демаскированная записи.</p>}
    <div role="status" aria-live="polite" aria-atomic="true">
      {checking ? <p>Проверяем доступность метрик…</p> : null}
      {status === 'error' && !scores ? <p>Не удалось проверить доступность метрик. Можно повторить запрос кнопкой оценки.</p> : null}
      {message ? <p>{message}</p> : null}
      {hasFiles ? selected.map((name) => <div className="quality-comparison" key={name}>
        <h4>{pairTitles[name]}</h4>
        <div className="metrics">
          {qualityMetrics.map((metric) => {
            const score = scores?.[name]?.[metric];
            const ready = availability?.[metric];
            const interpretation = !running && score?.status === 'success'
              ? qualityInterpretation(metric, score.value) : null;
            return <div className="metric" key={metric}>
              <strong>{qualityScales[metric].label}</strong>
              <span className="metric-value">{interpretation && score?.status === 'success'
                ? formatScore(score.value) : '—'}</span>
              {interpretation ? <span className="metric-interpretation" style={{ '--quality-hue': interpretation.hue } as CSSProperties}>
                <span className="metric-dot" aria-hidden="true" style={{ backgroundColor: 'currentColor' }} />
                {interpretation.label}
              </span> : <span>{running ? 'Вычисляется' : score?.status === 'success' ? 'Сервер вернул некорректный результат.'
                : score?.status === 'unavailable' || (!score && ready?.status === 'unavailable') ? 'Недоступно'
                  : score?.message ?? ready?.message ?? 'Не запрошено'}</span>}
            </div>;
          })}
        </div>
      </div>) : null}
    </div>
    {error ? <p className="message error" role="alert">{error}</p> : null}
  </section>;
}
