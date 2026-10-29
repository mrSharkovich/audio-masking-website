import { useState } from 'react';
import { useAsyncAction } from '../hooks/useAsyncAction';
import type { DemoSettings, TranscriptSelection, TranscriptionAdapter, TranscriptionResult } from '../types/audio';

export function TranscriptionPanel({ resultId, adapter, settings }: { resultId: string; adapter: TranscriptionAdapter; settings: DemoSettings }) {
  const [selection, setSelection] = useState<TranscriptSelection>('original');
  const [copyMessage, setCopyMessage] = useState('');
  const action = useAsyncAction<TranscriptionResult>();
  const run = () => {
    setCopyMessage('');
    return action.run(() => {
      if (settings.enabled) return adapter.transcribe(resultId, selection, settings.transcription);
      const unavailable = { status: 'unavailable' as const, message: 'Локальная транскрибация пока не подключена.' };
      return Promise.resolve(selection === 'both' ? { original: unavailable, masked: unavailable } : { [selection]: unavailable });
    });
  };
  const copy = async (text: string) => {
    try { await navigator.clipboard.writeText(text); setCopyMessage('Демонстрационный текст скопирован.'); }
    catch { setCopyMessage('Не удалось скопировать автоматически. Выделите текст и скопируйте вручную.'); }
  };
  return <section className="auxiliary-panel" aria-labelledby="transcription-heading">
    <div className="panel-title"><span className="section-index" aria-hidden="true">04</span><h3 id="transcription-heading">Транскрибация</h3><span className="quiet-tag">Необязательно</span></div>
    <p>Текст отдельно для каждой записи. Реальное распознавание будет выполняться локально после подключения модели.</p>
    <fieldset className="source-options" disabled={action.loading}><legend>Какую запись распознать?</legend>
      {([{ value: 'original', label: 'Исходное аудио' }, { value: 'masked', label: 'Маскированное аудио' }, { value: 'both', label: 'Оба файла' }] as const).map((option) => <label key={option.value}><input type="radio" name="transcription-source" value={option.value} checked={selection === option.value} onChange={() => { setSelection(option.value); setCopyMessage(''); }} />{option.label}</label>)}
    </fieldset>
    <button type="button" className="button secondary" disabled={action.loading} onClick={run}>{action.loading ? 'Ожидание примера…' : 'Запустить транскрибацию'}</button>
    <div role="status" aria-live="polite">{action.loading ? <p>Ожидание демонстрационного текста. LLM не запускается.</p> : null}</div>
    {action.value ? <div className="transcripts">{(['original', 'masked'] as const).map((source) => {
      const item = action.value?.[source];
      if (!item) return null;
      return <article className="transcript" key={source}><h4>{source === 'original' ? 'Оригинал' : 'После маскирования'} — демонстрационный ответ</h4>
        {item.status === 'success' ? <><p className="transcript-text">{item.value}</p><button type="button" className="text-button" onClick={() => copy(item.value)}>Копировать {source === 'original' ? 'текст оригинала' : 'текст результата'}</button></> : <p>{item.message}</p>}
      </article>;
    })}</div> : null}
    {action.error ? <p className="message error" role="alert">{action.error}</p> : null}
    <p className="small-note" role="status">{copyMessage || 'Примеры текста не являются транскрипцией выбранных файлов.'}</p>
  </section>;
}
