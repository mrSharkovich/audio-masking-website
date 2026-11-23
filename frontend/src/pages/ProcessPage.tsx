import { useEffect, useRef, useState } from 'react';
import { createDemoAdapters } from '../adapters/demoAudio';
import { createHttpMaskingAdapter } from '../adapters/httpMasking';
import { createHttpTranscriptionAdapter } from '../adapters/httpTranscription';
import { TranscriptionPanel } from '../components/TranscriptionPanel';
import { ResultView } from '../components/ResultView';
import { UploadForm } from '../components/UploadForm';
import { useObjectUrl } from '../hooks/useObjectUrl';
import { useWorkspace } from '../hooks/useWorkspace';
import { maskingTestNotice } from '../types/audio';
import type { AudioAdapters, AudioLanguage, DemoSettings, MaskingOptions } from '../types/audio';

const defaultAdapters: AudioAdapters = { ...createDemoAdapters(), masking: createHttpMaskingAdapter(), transcription: createHttpTranscriptionAdapter() };
const settings: DemoSettings = { enabled: false, masking: 'unavailable', quality: 'unavailable', transcription: 'unavailable' };

export function ProcessPage({ adapters = defaultAdapters, audioLanguage, onAudioLanguageChange }: { adapters?: AudioAdapters; audioLanguage: AudioLanguage; onAudioLanguageChange: (language: AudioLanguage) => void }) {
  const workspace = useWorkspace(adapters.masking);
  const [testMode, setTestMode] = useState(false);
  const [options, setOptions] = useState<MaskingOptions>({ mode: 'two-sided', matrix: 64 });
  const sourceUrl = useObjectUrl(workspace.view === 'form' ? workspace.source : null);
  const formHeading = useRef<HTMLHeadingElement>(null);
  const resultHeading = useRef<HTMLHeadingElement>(null);
  const previousView = useRef(workspace.view);
  useEffect(() => {
    const controller = new AbortController();
    setTestMode(false);
    void adapters.masking.available?.(controller.signal).then((available) => {
      if (!controller.signal.aborted) setTestMode(available);
    }).catch(() => {});
    return () => controller.abort();
  }, [adapters.masking]);
  useEffect(() => {
    if (previousView.current === workspace.view) return;
    (workspace.view === 'result' ? resultHeading : formHeading).current?.focus();
    previousView.current = workspace.view;
  }, [workspace.view]);

  return <section className="workspace-section" id="processing" aria-labelledby="page-title">
        <div className="workspace-intro"><div><p className="studio-label"><span className="studio-dot" aria-hidden="true" />Аудиостудия</p><h1 id="page-title">Маскирование аудиозаписи</h1><p className="intro-copy">Загрузите запись, сравните звучание и исследуйте результат.</p></div></div>
        <div className="demo-banner" role="note"><span className="demo-icon" aria-hidden="true">i</span><div><strong>{testMode ? maskingTestNotice : 'Маскирование и оценка качества пока недоступны'}</strong><span>{testMode ? 'Backend подготавливает WAV 16 кГц mono PCM16 и возвращает две его копии.' : 'Для распознавания WAV отправляется локальному backend только по нажатию кнопки транскрибации.'}</span></div></div>
        <div className="studio-frame"><div className="studio-topline"><span><span aria-hidden="true">●</span> AudioMask Studio</span><span>{testMode ? 'Тестовый режим' : 'Сервис не подключён'}</span></div>
          <div className="workspace-content">
            {workspace.view === 'result' && workspace.result && workspace.source ? <ResultView result={workspace.result} source={workspace.source} adapters={adapters} settings={settings} audioLanguage={audioLanguage} onAudioLanguageChange={onAudioLanguageChange} headingRef={resultHeading} onForm={workspace.showForm} onNew={workspace.clear} /> :
              <><UploadForm source={workspace.source} sourceUrl={sourceUrl} busy={workspace.busy} error={workspace.error} hasResult={Boolean(workspace.result)} demoEnabled={testMode} options={options} onOptionsChange={setOptions} headingRef={formHeading} onSelect={workspace.selectFiles} onClear={workspace.clear} onRun={() => { void workspace.run({ ...settings, enabled: testMode }, options); }} onCancel={workspace.cancel} onShowResult={workspace.showResult} />
              <TranscriptionPanel source={workspace.source} adapter={adapters.transcription} audioLanguage={audioLanguage} onAudioLanguageChange={onAudioLanguageChange} /></>}
          </div>
        </div>
      </section>;
}
