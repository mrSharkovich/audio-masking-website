import { useEffect, useRef, useState } from 'react';
import { createDemoAdapters } from './adapters/demoAudio';
import { DemoControls } from './components/DemoControls';
import { ResultView } from './components/ResultView';
import { UploadForm } from './components/UploadForm';
import { useObjectUrl } from './hooks/useObjectUrl';
import { useTheme } from './hooks/useTheme';
import { useWorkspace } from './hooks/useWorkspace';
import type { AudioAdapters, DemoSettings } from './types/audio';

const defaultAdapters = createDemoAdapters();
const initialSettings: DemoSettings = { enabled: true, masking: 'success', quality: 'success', transcription: 'success' };

function Brand() {
  return <a className="brand" href="#processing" aria-label="AudioMask — к обработке"><svg viewBox="0 0 40 40" fill="none" aria-hidden="true"><rect x="2" y="2" width="36" height="36" rx="10" fill="currentColor" /><path d="M11 27 20 12l9 15M15 23h10M20 18v11" stroke="var(--on-accent)" strokeWidth="2.3" strokeLinecap="round" strokeLinejoin="round" /></svg><span>AudioMask</span></a>;
}

export function App({ adapters = defaultAdapters }: { adapters?: AudioAdapters }) {
  const { theme, toggle } = useTheme();
  const workspace = useWorkspace(adapters.masking);
  const [settings, setSettings] = useState(initialSettings);
  const sourceUrl = useObjectUrl(workspace.source);
  const resultUrl = useObjectUrl(workspace.result?.audio ?? null);
  const formHeading = useRef<HTMLHeadingElement>(null);
  const resultHeading = useRef<HTMLHeadingElement>(null);
  const previousView = useRef(workspace.view);
  useEffect(() => {
    if (previousView.current === workspace.view) return;
    (workspace.view === 'result' ? resultHeading : formHeading).current?.focus();
    previousView.current = workspace.view;
  }, [workspace.view]);

  return <>
    <a className="skip-link" href="#processing">К обработке аудио</a>
    <header className="site-header"><div className="header-inner"><Brand />
      <nav aria-label="Основная навигация"><a href="#processing">Обработка</a><a href="#how-it-works">Как это работает</a><a href="#about">О проекте</a></nav>
      <button type="button" className="theme-toggle" onClick={toggle} aria-label="Тёмная тема" aria-pressed={theme === 'dark'}><span aria-hidden="true">{theme === 'dark' ? '☾' : '☀'}</span><span>{theme === 'dark' ? 'Тёмная' : 'Светлая'}</span></button>
    </div></header>
    <main className="page-shell">
      <section className="workspace-section" id="processing" aria-labelledby="page-title">
        <div className="workspace-intro"><div><p className="studio-label"><span className="studio-dot" aria-hidden="true" />Аудиостудия</p><h1 id="page-title">Маскирование аудиозаписи</h1><p className="intro-copy">Загрузите запись, сравните звучание и исследуйте результат.</p></div><span className="workspace-label">Рабочая область</span></div>
        <div className="demo-banner" role="note"><span className="demo-icon" aria-hidden="true">i</span><div><strong>Демонстрация — реальные операции не выполняются</strong><span>Тестовые данные — обработка не выполнялась. Аудио не отправляется на сервер.</span></div></div>
        <div className="studio-frame"><div className="studio-topline"><span><span aria-hidden="true">●</span> AudioMask Studio</span><span>{settings.enabled ? 'Демонстрационный режим' : 'Сервис не подключён'}</span></div>
          <div className="workspace-content">
            {workspace.view === 'result' && workspace.result && workspace.source ? <ResultView result={workspace.result} source={workspace.source} sourceUrl={sourceUrl} resultUrl={resultUrl} adapters={adapters} settings={settings} headingRef={resultHeading} onForm={workspace.showForm} onNew={workspace.clear} /> :
              <UploadForm source={workspace.source} sourceUrl={sourceUrl} busy={workspace.busy} error={workspace.error} hasResult={Boolean(workspace.result)} demoEnabled={settings.enabled} headingRef={formHeading} onSelect={workspace.selectFiles} onClear={workspace.clear} onRun={() => { void workspace.run(settings); }} onShowResult={workspace.showResult} />}
          </div>
          <DemoControls settings={settings} locked={workspace.busy} onChange={(next) => { if (!workspace.busy) setSettings(next); }} />
        </div>
      </section>
      <section className="how-section" id="how-it-works" aria-labelledby="how-heading"><div className="info-heading"><h2 id="how-heading">Как это работает</h2><p>От исходной записи до сравнения результата — в одном пространстве.</p></div>
        <ol className="steps"><li><span className="step-number" aria-hidden="true">1</span><h3>Выберите запись</h3><p>Добавьте один аудиофайл и прослушайте оригинал.</p></li><li><span className="step-number" aria-hidden="true">2</span><h3>Запустите маскирование</h3><p>После подключения алгоритма здесь появится обработанный файл. Сейчас доступна демонстрация.</p></li><li><span className="step-number" aria-hidden="true">3</span><h3>Исследуйте результат</h3><p>Прослушайте записи. По желанию запросите оценку качества или транскрибацию.</p></li></ol>
      </section>
      <section className="about-section" id="about" aria-labelledby="about-heading"><div><h2 id="about-heading">О проекте</h2><p>AudioMask — курсовой проект для исследования эффективности алгоритма маскирования аудиозаписей. Интерфейс объединяет работу с записью, сравнение звучания и дополнительные инструменты оценки.</p></div><div className="about-note"><span className="studio-dot" aria-hidden="true" /><p>Сейчас работает только интерфейс. Маскирование, PESQ, ViSQOL и локальная LLM будут подключены отдельным этапом.</p></div></section>
    </main>
    <footer className="site-footer"><span>AudioMask</span><p>Исследование маскирования аудиозаписей</p><a href="#processing">К рабочей области</a></footer>
  </>;
}
