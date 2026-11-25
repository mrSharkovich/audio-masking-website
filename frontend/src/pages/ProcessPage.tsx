import { useEffect, useRef, useState } from 'react';
import { createDemoAdapters } from '../adapters/demoAudio';
import { createHttpMaskingAdapter } from '../adapters/httpMasking';
import { createHttpTranscriptionAdapter } from '../adapters/httpTranscription';
import { httpQuality, qualityMetrics } from '../adapters/httpQuality';
import type { QualityProbe } from '../adapters/httpQuality';
import { TranscriptionPanel } from '../components/TranscriptionPanel';
import { ResultView } from '../components/ResultView';
import { UploadForm } from '../components/UploadForm';
import { SaveFileButton } from '../components/SaveFileButton';
import { useObjectUrl } from '../hooks/useObjectUrl';
import { useWorkspace } from '../hooks/useWorkspace';
import type { AudioAdapters, AudioLanguage, DemoSettings, MaskingAvailability, MaskingOptions } from '../types/audio';

const defaultAdapters: AudioAdapters = { ...createDemoAdapters(), masking: createHttpMaskingAdapter(), transcription: createHttpTranscriptionAdapter() };
const settings: DemoSettings = { enabled: false, masking: 'unavailable', quality: 'unavailable', transcription: 'unavailable' };

export function ProcessPage({ adapters = defaultAdapters, audioLanguage, onAudioLanguageChange }: { adapters?: AudioAdapters; audioLanguage: AudioLanguage; onAudioLanguageChange: (language: AudioLanguage) => void }) {
  const workspace = useWorkspace(adapters.masking);
  const [availability, setAvailability] = useState<MaskingAvailability>('unavailable');
  const [quality, setQuality] = useState<QualityProbe>('checking');
  const mode = workspace.view === 'result' && workspace.result
    ? workspace.result.testMasking ? 'test' : workspace.result.masking ? 'real' : availability
    : availability;
  const [options, setOptions] = useState<MaskingOptions>({ mode: 'two-sided', matrix: 64 });
  const sourceUrl = useObjectUrl(workspace.view === 'form' ? workspace.source : null);
  const formHeading = useRef<HTMLHeadingElement>(null);
  const resultHeading = useRef<HTMLHeadingElement>(null);
  const previousView = useRef(workspace.view);
  useEffect(() => {
    const controller = new AbortController();
    setAvailability('unavailable');
    setQuality('checking');
    void adapters.masking.available?.(controller.signal).then((available) => {
      if (controller.signal.aborted) return;
      setAvailability(available);
      if (available !== 'unavailable') {
        void httpQuality.status(controller.signal).then((metrics) => {
          if (!controller.signal.aborted) setQuality(metrics);
        }).catch(() => {
          if (!controller.signal.aborted) setQuality('error');
        });
      }
    }).catch(() => {});
    return () => controller.abort();
  }, [adapters.masking]);
  useEffect(() => {
    if (previousView.current === workspace.view) return;
    (workspace.view === 'result' ? resultHeading : formHeading).current?.focus();
    previousView.current = workspace.view;
  }, [workspace.view]);

  const availableMetrics = typeof quality === 'object'
    ? qualityMetrics.filter((metric) => quality[metric].status === 'available').length : 0;
  const qualityNotice = availableMetrics === qualityMetrics.length ? 'Оценка качества доступна.'
    : availableMetrics > 0 ? 'Доступна часть метрик оценки качества.'
      : typeof quality === 'object' && qualityMetrics.every((metric) => quality[metric].status === 'unavailable')
        ? 'Метрики оценки качества недоступны.' : quality === 'checking' ? 'Проверяем доступность метрик.'
          : 'Не удалось подтвердить доступность метрик.';

  return <section className="workspace-section" id="processing" aria-labelledby="page-title">
        <div className="workspace-intro"><div><p className="studio-label"><span className="studio-dot" aria-hidden="true" />Аудиостудия</p><h1 id="page-title">Маскирование аудиозаписи</h1><p className="intro-copy">Загрузите запись, сравните звучание и исследуйте результат.</p></div></div>
        {mode !== 'real' ? <div className="demo-banner" role="note"><span className="demo-icon" aria-hidden="true">i</span><div>
          <strong>{mode === 'test' ? 'Маскирование работает в тестовом режиме' : 'Маскирование пока недоступно'}</strong>
          {mode === 'test' ? <span>{qualityNotice} Настоящее маскирование пока не выполняется.</span>
            : <span>Локальный backend недоступен или маскирование в нём не подключено.</span>}
        </div></div> : null}
        <div className="studio-frame"><div className="studio-topline"><span><span aria-hidden="true">●</span> AudioMask Studio</span><span>{mode === 'test' ? 'Тестовый режим' : mode === 'real' ? 'Маскирование подключено' : 'Сервис не подключён'}</span></div>
          <div className="workspace-content">
            {workspace.view === 'result' && workspace.result && workspace.source ? <>
              <div className="section-heading"><div><span className="section-index" aria-hidden="true">01</span><h2>Исходная запись</h2></div><span className="status-chip">Файл выбран</span></div>
              <ResultView result={workspace.result} source={workspace.source} qualityProbe={availability === 'unavailable' ? undefined : quality} headingRef={resultHeading} onForm={workspace.showForm} onNew={workspace.clear} />
            </> : <>
              <UploadForm source={workspace.source} sourceUrl={sourceUrl} busy={workspace.busy} error={workspace.error} hasResult={Boolean(workspace.result)} availability={availability} options={options} onOptionsChange={setOptions} headingRef={formHeading} onSelect={workspace.selectFiles} onClear={workspace.clear} onRun={() => { void workspace.run({ ...settings, enabled: availability !== 'unavailable' }, options); }} onCancel={workspace.cancel} onShowResult={workspace.showResult} />
              <section className="auxiliary-panel pending-stage" aria-labelledby="pending-result-heading">
                <div className="panel-title"><span className="section-index" aria-hidden="true">02</span><h2 id="pending-result-heading">Результат обработки</h2></div>
                <p>{workspace.result ? 'Откройте текущий результат.' : 'Результаты появятся после маскирования'}</p>
              </section>
              <section className="auxiliary-panel pending-stage" aria-labelledby="pending-quality-heading">
                <div className="panel-title"><span className="section-index" aria-hidden="true">03</span><h3 id="pending-quality-heading">Оценка качества аудио</h3>
                  <SaveFileButton label="Сохранить оценки качества" filename="audiomask-quality.md" extension=".md" />
                </div>
                <p>{workspace.result ? 'Оценка доступна в текущем результате.' : 'Сначала выполните маскирование'}</p>
              </section>
            </>}
            <TranscriptionPanel source={workspace.source} maskedResult={workspace.result} adapter={adapters.transcription} audioLanguage={audioLanguage} onAudioLanguageChange={onAudioLanguageChange} />
          </div>
        </div>
      </section>;
}
