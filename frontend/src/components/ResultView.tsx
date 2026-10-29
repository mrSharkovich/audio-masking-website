import { useState } from 'react';
import type { RefObject } from 'react';
import type { AudioAdapters, AudioResult, DemoSettings } from '../types/audio';
import { AudioPlayer } from './AudioPlayer';
import { QualityPanel } from './QualityPanel';
import { TranscriptionPanel } from './TranscriptionPanel';

interface Props {
  result: AudioResult;
  source: File;
  sourceUrl?: string;
  resultUrl?: string;
  adapters: AudioAdapters;
  settings: DemoSettings;
  headingRef: RefObject<HTMLHeadingElement | null>;
  onForm: () => void;
  onNew: () => void;
}

export function ResultView(props: Props) {
  const [downloadError, setDownloadError] = useState('');
  const download = () => {
    if (!props.resultUrl) { setDownloadError('Демонстрационный файл ещё не готов. Повторите попытку.'); return; }
    try {
      const link = document.createElement('a');
      link.href = props.resultUrl; link.download = props.result.fileName;
      document.body.appendChild(link); link.click(); link.remove();
      setDownloadError('');
    } catch { setDownloadError('Не удалось начать скачивание демонстрационного файла. Проверьте разрешения браузера.'); }
  };
  return <div className="result-view">
    <div className="section-heading"><div><span className="section-index" aria-hidden="true">02</span><h2 ref={props.headingRef} tabIndex={-1}>Результат демонстрации</h2></div><span className="status-chip ready">Сценарий завершён</span></div>
    <p className="result-notice">Демонстрация — реальные операции не выполняются. Вместо обработанного файла представлен отдельный синтетический тон. Он не получен из вашей записи.</p>
    <div className="player-comparison">
      <div className="audio-channel"><span className="channel-badge">Вход</span><AudioPlayer label="Оригинал" url={props.sourceUrl} /><p className="file-caption">{props.source.name}</p></div>
      <div className="audio-channel demo-channel"><span className="channel-badge">Тестовый пример</span><AudioPlayer label="После маскирования" url={props.resultUrl} /><p className="file-caption">Демонстрационный синтетический тон, не результат маскирования</p></div>
    </div>
    <div className="result-actions">
      <button className="button primary" type="button" disabled={!props.resultUrl} onClick={download}>Скачать демонстрационный файл<span aria-hidden="true">↓</span></button>
      <button className="button secondary" type="button" disabled title="Настоящий обработанный файл отсутствует">Скачать обработанное аудио</button>
    </div>
    <p className="small-note">Настоящее скачивание результата станет доступно после подключения обработки. Исходная запись не подменяет обработанный файл.</p>
    {downloadError ? <p className="message error" role="alert">{downloadError}</p> : null}
    <div className="result-navigation">
      <button className="text-button" type="button" onClick={props.onForm}>Вернуться к форме</button>
      <button className="button secondary" type="button" onClick={props.onForm}>Обработать ещё раз</button>
      <button className="button secondary" type="button" onClick={props.onNew}>Загрузить другой файл</button>
    </div>
    <div className="additional-tools" key={props.result.id}>
      <QualityPanel resultId={props.result.id} adapter={props.adapters.quality} settings={props.settings} />
      <TranscriptionPanel resultId={props.result.id} adapter={props.adapters.transcription} settings={props.settings} />
    </div>
  </div>;
}
