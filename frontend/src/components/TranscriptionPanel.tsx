import { useLayoutEffect, useRef, useState } from 'react';
import type { AsrMaskedAudio, AudioLanguage, OperationValue, TranscriptSource, TranscriptionAdapter } from '../types/audio';
import { emptyTranscriptionTitle } from '../types/audio';
import { SaveFileButton } from './SaveFileButton';

const sources = ['original', 'masked', 'demasked'] as const;
const labels = { original: 'Исходная запись', masked: 'Маскированная запись', demasked: 'Демаскированная запись' };
const languages = { ru: 'Русский', en: 'English' } as const;
const languageOrder = ['ru', 'en'] as const;
const modelLabels = { ru: 'GigaAM-Multilingual CTC 220M', en: 'Whisper small multilingual' };
const emptyDescription = 'Модель не смогла распознать текст в данной аудиозаписи';
type Results = Partial<Record<TranscriptSource, { language: AudioLanguage; response: OperationValue<string> }>>;

interface Props {
  source: File | null;
  maskedResult?: AsrMaskedAudio | null;
  adapter: TranscriptionAdapter;
  audioLanguage: AudioLanguage;
  onAudioLanguageChange: (language: AudioLanguage) => void;
}

export function TranscriptionPanel({ source, maskedResult, adapter, audioLanguage, onAudioLanguageChange }: Props) {
  const test = maskedResult?.testMasking;
  const details = test ?? maskedResult?.masking;
  const masked = maskedResult?.audio.size && (test || !maskedResult.demonstration) ? maskedResult.audio : null;
  const demasked = details?.demasked.size ? details.demasked : null;
  const available = { original: Boolean(source?.size), masked: Boolean(masked), demasked: Boolean(demasked) };
  const [selection, setSelection] = useState<TranscriptSource[]>(['original']);
  const selected = sources.filter((item) => selection.includes(item) && available[item]);
  const [operation, setOperation] = useState({ loading: false, message: '' });
  const [results, setResults] = useState<Results>({});
  const [copyMessage, setCopyMessage] = useState('');
  const request = useRef<AbortController | null>(null);
  const previous = useRef({ source, masked, demasked });
  const titles = { original: 'Оригинал', masked: test ? 'Тестовая маскированная копия' : 'После маскирования',
    demasked: test ? 'Тестовая демаскированная копия' : 'Демаскированное аудио' };
  const entries = sources.flatMap((item) => {
    const entry = results[item];
    return entry ? [{ item, ...entry }] : [];
  });

  function report() {
    return entries.map(({ item, language, response }) => {
      const body = response.status === 'success' ? response.value : response.status === 'empty' ? emptyDescription
        : `${response.status === 'unavailable' ? 'Недоступно' : 'Ошибка'}: ${response.message}`;
      return [titles[item], `Язык: ${languages[language]}`, `Модель: ${modelLabels[language]}`, body].join('\n');
    }).join('\n\n') + '\n';
  }

  useLayoutEffect(() => {
    const old = previous.current;
    previous.current = { source, masked, demasked };
    if (old.source !== source) {
      setSelection(['original']);
      setResults({});
    } else {
      if (old.masked !== masked || old.demasked !== demasked) {
        setResults((current) => {
          const next = { ...current };
          if (old.masked !== masked) delete next.masked;
          if (old.demasked !== demasked) delete next.demasked;
          return next;
        });
        setSelection((items) => items.filter((item) => item === 'original'
          || (item === 'masked' ? masked : demasked)));
      }
    }
    setOperation({ loading: false, message: '' });
    setCopyMessage('');
    return () => { request.current?.abort(); request.current = null; };
  }, [source, masked, demasked, adapter]);

  const run = async () => {
    if (request.current || !selected.length) return;
    const controller = new AbortController();
    request.current = controller;
    const current = () => request.current === controller && !controller.signal.aborted;
    setOperation({ loading: true, message: '' });
    setResults({});
    setCopyMessage('');
    try {
      // Sequential requests respect the backend's shared ru/en concurrency limit.
      for (const item of selected) {
        if (!current()) return;
        const file = item === 'original' ? source
          : item === 'demasked' ? (details?.demasked.size ? new File([details.demasked], details.demaskedFileName, { type: 'audio/wav' }) : null)
            : maskedResult && (test || !maskedResult.demonstration)
              ? new File([maskedResult.audio], maskedResult.fileName, { type: maskedResult.audio.type }) : null;
        if (!file) continue;
        let response: OperationValue<string>;
        try {
          response = await adapter.transcribe(file, audioLanguage, controller.signal);
        } catch {
          response = { status: 'error', message: 'Не удалось выполнить распознавание. Проверьте доступность локального backend.' };
        }
        if (!current()) return;
        setResults((saved) => ({ ...saved, [item]: { language: audioLanguage, response } }));
      }
      if (current()) setOperation({ loading: false, message: '' });
    } finally {
      if (request.current === controller) request.current = null;
    }
  };
  const cancel = () => {
    request.current?.abort(); request.current = null;
    setOperation({ loading: false, message: 'Запрос распознавания отменён.' });
  };
  const copy = async (text: string) => {
    try { await navigator.clipboard.writeText(text); setCopyMessage('Текст скопирован.'); }
    catch { setCopyMessage('Не удалось скопировать автоматически. Выделите текст и скопируйте вручную.'); }
  };
  return <section className="auxiliary-panel" aria-labelledby="transcription-heading">
    <div className="panel-title"><span className="section-index" aria-hidden="true">04</span><h3 id="transcription-heading">Транскрибация</h3><span className="quiet-tag">Необязательно</span>
      <SaveFileButton label="Сохранить транскрипции" filename="audiomask-transcripts.txt" extension=".txt"
        disabled={operation.loading} content={entries.length ? report : undefined} />
    </div>
    <p>Текст отдельно для каждой записи. Аудиофайл отправляется локальному backend только при запуске распознавания.</p>
    <fieldset className="source-options" disabled={operation.loading}><legend>Язык аудиозаписи</legend>
      {languageOrder.map((language) => <label key={language}><input type="radio" name="transcription-language" value={language} checked={audioLanguage === language} onChange={() => onAudioLanguageChange(language)} />{languages[language]}</label>)}
    </fieldset>
    <p className="small-note">Модель: {modelLabels[audioLanguage]}. Модель выбирает сервер по языку.</p>
    <p className="small-note">Backend подготавливает аудио в WAV 16 кГц mono PCM16. Для MP3, M4A, FLAC, OGG и других поддерживаемых сжатых форматов нужен FFmpeg.</p>
    <fieldset className="quality-pairs transcription-sources" disabled={operation.loading}><legend>Какие записи распознать?</legend>
      {sources.map((item) => <label key={item}><input type="checkbox" disabled={!available[item]}
        checked={selection.includes(item)} onChange={(event) => {
          const checked = event.currentTarget.checked;
          setSelection((items) => checked ? [...items, item] : items.filter((name) => name !== item));
        }} />{labels[item]}</label>)}
    </fieldset>
    <div className="form-actions">
      <button type="button" className="button secondary" disabled={operation.loading || !selected.length} onClick={() => { void run(); }}>{operation.loading ? 'Распознавание…' : 'Запустить транскрибацию'}</button>
      {operation.loading ? <button type="button" className="button secondary" onClick={cancel}>Отменить запрос</button> : null}
    </div>
    <div role="status" aria-live="polite">{operation.loading ? <p>Ожидание ответа локального ASR…</p> : operation.message ? <p>{operation.message}</p> : null}</div>
    {entries.length > 0 ? <div className="transcripts">{entries.map(({ item, language, response }) =>
      <article className="transcript" key={item}><h4>{titles[item]} · {languages[language]}</h4>
        {response.status === 'success' ? <><p className="transcript-text">{response.value}</p><button type="button" className="text-button" onClick={() => { void copy(response.value); }}>Копировать {item === 'original' ? 'текст оригинала' : 'текст результата'}</button></> : null}
        {response.status === 'empty' ? <p className="transcript-empty" role="status"><strong>{emptyTranscriptionTitle}</strong><br />
          {emptyDescription}.<br />
          <span className="small-note">{modelLabels[language]}</span>
        </p> : null}
        {response.status === 'error' || response.status === 'unavailable'
          ? <p role={response.status === 'error' ? 'alert' : 'status'}>{response.message}</p> : null}
      </article>
    )}</div> : null}
    {copyMessage ? <p className="small-note" role="status">{copyMessage}</p> : null}
  </section>;
}
