export function AboutPage() {
  return <section className="about-section" id="about" aria-labelledby="about-heading"><div><h1 id="about-heading">О проекте</h1><p>AudioMask — курсовой проект для исследования эффективности алгоритма маскирования аудиозаписей. Интерфейс объединяет работу с записью, сравнение звучания и дополнительные инструменты оценки.</p></div><div className="about-note"><span className="studio-dot" aria-hidden="true" /><p>Сейчас работает только интерфейс. Маскирование, PESQ, ViSQOL и локальная LLM будут подключены отдельным этапом.</p></div></section>;
}
