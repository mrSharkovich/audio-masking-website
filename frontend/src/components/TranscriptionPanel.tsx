import { useEffect, useRef, useState } from 'react';
import type { AsrMaskedAudio, AudioLanguage, TranscriptSelection, TranscriptionAdapter, TranscriptionResult } from '../types/audio';

interface Props {
  source: File | null;
  maskedResult?: AsrMaskedAudio | null;
  adapter: TranscriptionAdapter;
  audioLanguage: AudioLanguage;
  onAudioLanguageChange: (language: AudioLanguage) => void;
}

export function TranscriptionPanel({ source, maskedResult, adapter, audioLanguage, onAudioLanguageChange }: Props) {
  const [selection, setSelection] = useState<TranscriptSelection>('original');
  const [state, setState] = useState<{ loading: boolean; value: TranscriptionResult | null; message: string }>({ loading: false, value: null, message: '' });
  const [copyMessage, setCopyMessage] = useState('');
  const request = useRef<AbortController | null>(null);
  useEffect(() => {
    setState({ loading: false, value: null, message: '' });
    setCopyMessage('');
    return () => { request.current?.abort(); request.current = null; };
  }, [source, maskedResult, adapter, audioLanguage, selection]);

  const run = async () => {
    if (request.current) return;
    const controller = new AbortController();
    request.current = controller;
    const current = () => request.current === controller && !controller.signal.aborted;
    setState({ loading: true, value: null, message: '' });
    setCopyMessage('');
    const value: TranscriptionResult = {};
    try {
      // Sequential requests respect the backend's shared ru/en concurrency limit.
      for (const item of selection === 'both' ? ['original', 'masked'] as const : [selection]) {
        if (!current()) return;
        const file = item === 'original' ? source
          : maskedResult?.demonstration === false ? new File([maskedResult.audio], maskedResult.fileName, { type: maskedResult.audio.type }) : null;
        if (!file) {
          value[item] = { status: 'unavailable', message: item === 'original' ? 'Выберите исходную аудиозапись.' : 'Реальная маскированная запись отсутствует. Распознавание этой записи недоступно.' };
        } else {
          value[item] = await adapter.transcribe(file, audioLanguage, controller.signal);
        }
        if (current()) setState({ loading: true, value: { ...value }, message: '' });
      }
      if (current()) setState({ loading: false, value, message: '' });
    } catch {
      if (current()) setState({ loading: false, value: null, message: 'Не удалось выполнить распознавание. Проверьте доступность локального backend.' });
    } finally {
      if (request.current === controller) request.current = null;
    }
  };
  const cancel = () => {
    request.current?.abort(); request.current = null;
    setState({ loading: false, value: null, message: 'Запрос распознавания отменён.' });
  };
  const copy = async (text: string) => {
    try { await navigator.clipboard.writeText(text); setCopyMessage('Текст скопирован.'); }
    catch { setCopyMessage('Не удалось скопировать автоматически. Выделите текст и скопируйте вручную.'); }
  };
  return <section className="auxiliary-panel" aria-labelledby="transcription-heading">
    <div className="panel-title"><span className="section-index" aria-hidden="true">04</span><h3 id="transcription-heading">Транскрибация</h3><span className="quiet-tag">Необязательно</span></div>
    <p>Текст отдельно для каждой записи. Аудиофайл отправляется локальному backend только при запуске распознавания.</p>
    <fieldset className="source-options" disabled={state.loading}><legend>Язык аудиозаписи</legend>
      {([{ value: 'ru', label: 'Русский' }, { value: 'en', label: 'English' }] as const).map((option) => <label key={option.value}><input type="radio" name="transcription-language" value={option.value} checked={audioLanguage === option.value} onChange={() => onAudioLanguageChange(option.value)} />{option.label}</label>)}
    </fieldset>
    <p className="small-note">Модель: {audioLanguage === 'ru' ? 'GigaAM-Multilingual CTC 220M' : 'Whisper small multilingual'}. Модель выбирает сервер по языку.</p>
    <p className="small-note">ASR принимает WAV PCM 8/16/24/32 бит, mono/stereo, 8–192 кГц. Backend подготавливает 16 кГц mono PCM16. MP3 и другие форматы пока не поддерживаются.</p>
    <fieldset className="source-options" disabled={state.loading}><legend>Какую запись распознать?</legend>
      {([{ value: 'original', label: 'Исходное аудио' }, { value: 'masked', label: 'Маскированное аудио' }, { value: 'both', label: 'Оба файла' }] as const).map((option) => <label key={option.value}><input type="radio" name="transcription-source" value={option.value} checked={selection === option.value} onChange={() => setSelection(option.value)} />{option.label}</label>)}
    </fieldset>
    <div className="form-actions">
      <button type="button" className="button secondary" disabled={state.loading} onClick={() => { void run(); }}>{state.loading ? 'Распознавание…' : 'Запустить транскрибацию'}</button>
      {state.loading ? <button type="button" className="button secondary" onClick={cancel}>Отменить запрос</button> : null}
    </div>
    <div role="status" aria-live="polite">{state.loading ? <p>Ожидание ответа локального ASR…</p> : state.message ? <p>{state.message}</p> : null}</div>
    {state.value ? <div className="transcripts">{(['original', 'masked'] as const).map((sourceName) => {
      const item = state.value?.[sourceName];
      if (!item) return null;
      return <article className="transcript" key={sourceName}><h4>{sourceName === 'original' ? 'Оригинал' : 'После маскирования'}</h4>
        {item.status === 'success' ? <><p className="transcript-text">{item.value}</p><button type="button" className="text-button" onClick={() => { void copy(item.value); }}>Копировать {sourceName === 'original' ? 'текст оригинала' : 'текст результата'}</button></> : <p role={item.status === 'error' ? 'alert' : 'status'}>{item.message}</p>}
      </article>;
    })}</div> : null}
    {copyMessage ? <p className="small-note" role="status">{copyMessage}</p> : null}
  </section>;
}
