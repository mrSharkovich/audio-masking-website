import { useAsyncAction } from '../hooks/useAsyncAction';
import type { DemoSettings, QualityAdapter, QualityResult } from '../types/audio';

export function QualityPanel({ resultId, adapter, settings }: { resultId: string; adapter: QualityAdapter; settings: DemoSettings }) {
  const action = useAsyncAction<QualityResult>();
  const run = () => action.run(() => settings.enabled ? adapter.evaluate(resultId, settings.quality) : Promise.resolve<QualityResult>({
    PESQ: { status: 'unavailable', message: 'Реальная оценка не подключена.' },
    ViSQOL: { status: 'unavailable', message: 'Реальная оценка не подключена.' },
  }));
  return <section className="auxiliary-panel" aria-labelledby="quality-heading">
    <div className="panel-title"><span className="section-index" aria-hidden="true">03</span><h3 id="quality-heading">Оценка качества</h3><span className="quiet-tag">По запросу</span></div>
    <p>Два показателя качества: PESQ и ViSQOL. Расчёт не запускается вместе с маскированием.</p>
    <button type="button" className="button secondary" disabled={action.loading} onClick={run}>{action.loading ? 'Ожидание примера…' : 'Оценить качество'}</button>
    <div className="metrics" role="status" aria-live="polite">
      {(['PESQ', 'ViSQOL'] as const).map((name) => {
        const item = action.value?.[name];
        return <div className="metric" key={name}><strong>{name}</strong>
          <span className="metric-value">{action.loading ? '…' : item?.status === 'success' ? item.value.toLocaleString('ru-RU') : '—'}</span>
          <span>{action.loading ? 'Ожидание тестового ответа' : !item ? 'Не запрошено' : item.status === 'success' ? 'Демонстрационное значение, не расчёт' : item.message}</span>
        </div>;
      })}
    </div>
    {action.error ? <p className="message error" role="alert">{action.error}</p> : null}
    <p className="small-note">Здесь показаны только примеры. Пара записей и условия реального расчёта пока не согласованы.</p>
  </section>;
}
