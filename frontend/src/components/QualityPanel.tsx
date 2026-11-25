import { useEffect, useRef, useState } from 'react';
import { httpQuality, qualityComparisons, qualityMetrics } from '../adapters/httpQuality';
import type { QualityAvailability, QualityComparison, QualityEvaluationAdapter, QualityRecordings, QualityScores } from '../adapters/httpQuality';

const pairTitles = {
  masked: 'Исходная ↔ Маскированная',
  demasked: 'Исходная ↔ Демаскированная',
  masked_demasked: 'Маскированная ↔ Демаскированная',
};
const labels = { PESQ: 'PESQ Wideband', ViSQOL: 'ViSQOL без lattice', ViSQOL_LATTICE: 'ViSQOL с lattice' };

export function QualityPanel({ recordings, testMode, adapter = httpQuality }: {
  recordings: QualityRecordings | null;
  testMode: boolean;
  adapter?: QualityEvaluationAdapter;
}) {
  const hasFiles = Boolean(recordings?.original.size && recordings.masked.size && recordings.demasked.size);
  const active = useRef<AbortController | null>(null);
  const [availability, setAvailability] = useState<QualityAvailability | null>(null);
  const [checking, setChecking] = useState(hasFiles);
  const [probeError, setProbeError] = useState(false);
  const [running, setRunning] = useState(false);
  const [selected, setSelected] = useState<QualityComparison[]>(['masked']);
  const [scores, setScores] = useState<QualityScores | null>(null);
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');

  useEffect(() => {
    if (!hasFiles) return;
    const controller = new AbortController();
    void adapter.status(controller.signal).then((result) => {
      if (!controller.signal.aborted) setAvailability(result);
    }).catch(() => {
      if (!controller.signal.aborted) setProbeError(true);
    }).finally(() => {
      if (!controller.signal.aborted) setChecking(false);
    });
    return () => {
      controller.abort();
      active.current?.abort();
      active.current = null;
    };
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
    <div className="panel-title"><h3 id="quality-heading">Оценка качества аудио</h3></div>
    <p>PESQ Wideband и ViSQOL Speech при 16 кГц оценивают качество звучания. Стойкость маскирования требует отдельной проверки.</p>
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
      {probeError && !scores ? <p>Не удалось проверить доступность метрик. Можно повторить запрос кнопкой оценки.</p> : null}
      {message ? <p>{message}</p> : null}
      {hasFiles ? selected.map((name) => <div className="quality-comparison" key={name}>
        <h4>{pairTitles[name]}</h4>
        <div className="metrics">
          {qualityMetrics.map((metric) => {
            const score = scores?.[name]?.[metric];
            const ready = availability?.[metric];
            return <div className="metric" key={metric}>
              <strong>{labels[metric]}</strong>
              <span className="metric-value">{score?.status === 'success'
                ? score.value.toLocaleString('ru-RU', { maximumFractionDigits: 3 }) : '—'}</span>
              <span>{running ? 'Вычисляется' : score?.status === 'success' ? 'Рассчитано'
                : score?.status === 'unavailable' || (!score && ready?.status === 'unavailable') ? 'Недоступно'
                  : score?.message ?? ready?.message ?? 'Не запрошено'}</span>
            </div>;
          })}
        </div>
      </div>) : null}
    </div>
    {error ? <p className="message error" role="alert">{error}</p> : null}
  </section>;
}
