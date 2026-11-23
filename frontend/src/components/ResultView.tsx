import { useState } from 'react';
import type { RefObject } from 'react';
import type { AudioAdapters, AudioLanguage, AudioResult, DemoSettings } from '../types/audio';
import { maskingTestNotice } from '../types/audio';
import { useObjectUrl } from '../hooks/useObjectUrl';
import { AudioPlayer } from './AudioPlayer';
import { audioDownloadName } from './audioDownloadName';
import { QualityPanel } from './QualityPanel';
import { TranscriptionPanel } from './TranscriptionPanel';

interface Props {
  result: AudioResult;
  source: File;
  adapters: AudioAdapters;
  settings: DemoSettings;
  audioLanguage: AudioLanguage;
  onAudioLanguageChange: (language: AudioLanguage) => void;
  headingRef: RefObject<HTMLHeadingElement | null>;
  onForm: () => void;
  onNew: () => void;
}

const recordings = ['original', 'masked', 'demasked'] as const;
type Recording = typeof recordings[number];

function pauseOnDetach(audio: HTMLAudioElement | null) {
  if (audio) return () => audio.pause();
}

function ResultAudio({ source, result }: Pick<Props, 'source' | 'result'>) {
  const [selection, setSelection] = useState<Recording>('original');
  const test = result.testMasking;
  const details = test ?? result.masking;
  const demo = result.demonstration && !test;
  const tracks = {
    original: { title: 'Оригинал', file: source, note: undefined },
    masked: { title: demo ? 'Демонстрационный пример' : 'Маскированное аудио', file: result.audio,
      note: test ? 'Тестовая маскированная копия' : undefined },
    demasked: { title: 'Демаскированное аудио', file: details?.demasked,
      note: test ? 'Тестовая демаскированная копия' : undefined },
  };
  const track = tracks[selection];
  const available = Boolean(track.file?.size);
  const url = useObjectUrl(available ? track.file ?? null : null);
  const name = audioDownloadName(source.name, selection);
  return (
    <div className="audio-channel">
      <label className="recording-selector">Аудиозапись
        <select value={selection} onChange={(event) => setSelection(event.currentTarget.value as Recording)}>
          {recordings.map((recording) => <option key={recording} value={recording}>{tracks[recording].title}</option>)}
        </select>
      </label>
      {available && track.note ? <span className="channel-badge">{track.note}</span> : null}
      {url ? <AudioPlayer key={selection} label={track.title} url={url} mediaRef={pauseOnDetach}
        titleAction={<a className="button primary audio-download" href={url} download={name}
          title="Скачать аудио" aria-label="Скачать аудио">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor"
            strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" focusable="false">
            <path d="M12 3v12m-5-5 5 5 5-5M4 16v4a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-4" />
          </svg>
        </a>} /> : null}
      {available ? <p className="file-caption">{name}</p> : <p className="file-caption" role="status">Выбранная запись недоступна.</p>}
    </div>
  );
}

export function ResultView(props: Props) {
  const test = props.result.testMasking;
  const details = test ?? props.result.masking;
  return <div className="result-view">
    <div className="section-heading"><div><span className="section-index" aria-hidden="true">02</span><h2 ref={props.headingRef} tabIndex={-1}>{test ? 'Результат тестовой обработки' : props.result.demonstration ? 'Результат демонстрации' : 'Результат обработки'}</h2></div><span className="status-chip ready">Сценарий завершён</span></div>
    {test || props.result.demonstration ? <p className="result-notice">{test ? maskingTestNotice : 'Демонстрация — реальные операции не выполняются. Вместо обработанного файла представлен отдельный синтетический тон. Он не получен из вашей записи.'}</p> : null}
    {details ? <div className="small-note">
      <p>Режим: {details.options.mode === 'one-sided' ? 'Односторонний' : 'Двухсторонний'}. Выбранный размер матрицы: {details.options.matrix}. Применённый размер{test ? ' в тестовом режиме' : ''}: {details.appliedMatrix}.</p>
      {details.appliedMatrix < details.options.matrix ? <p role="status">Размер матрицы автоматически уменьшен с {details.options.matrix} до {details.appliedMatrix}{test ? ' по длине подготовленной записи' : ''}.</p> : null}
    </div> : null}
    <ResultAudio key={`audio-${props.result.id}`} source={props.source} result={props.result} />
    <div className="result-navigation">
      <button className="text-button" type="button" onClick={props.onForm}>Вернуться к форме</button>
      <button className="button secondary" type="button" onClick={props.onForm}>Обработать ещё раз</button>
      <button className="button secondary" type="button" onClick={props.onNew}>Загрузить другой файл</button>
    </div>
    <div className="additional-tools" key={props.result.id}>
      <QualityPanel resultId={props.result.id} adapter={props.adapters.quality} settings={props.settings} />
      <TranscriptionPanel source={props.source} maskedResult={props.result} adapter={props.adapters.transcription} audioLanguage={props.audioLanguage} onAudioLanguageChange={props.onAudioLanguageChange} />
    </div>
  </div>;
}
