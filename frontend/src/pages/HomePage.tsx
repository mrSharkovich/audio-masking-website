export function HomePage() {
  return <><section className="workspace-section" aria-labelledby="home-heading">
    <div className="workspace-intro"><div><p className="studio-label"><span className="studio-dot" aria-hidden="true" />Аудиостудия</p><h1 id="home-heading">Маскирование аудиозаписей</h1><p className="intro-copy">AudioMask — пространство для исследования маскирования аудио: от выбора записи до прослушивания и анализа результата.</p></div></div>
    <div className="demo-banner" role="note"><span className="demo-icon" aria-hidden="true">i</span><div><strong>Маскирование и оценка качества пока недоступны</strong><span>Для распознавания WAV отправляется локальному backend только по нажатию кнопки транскрибации.</span></div></div>
    <div className="form-actions"><a className="button primary" href="/process">Начать обработку</a><a className="text-button" href="/how-it-works">Как это работает</a></div>
  </section>
  <section className="how-section" aria-labelledby="features-heading">
    <div className="info-heading"><h2 id="features-heading">Возможности AudioMask</h2><p>Инструменты для работы с записью и изучения изменений после обработки.</p></div>
    <ul className="info-list">
      <li><strong>Маскирование аудио.</strong> Основной этап исследования — обработка записи алгоритмом маскирования. Сейчас маскирование недоступно.</li>
      <li><strong>Прослушивание и сравнение.</strong> Оригинал и результат представлены рядом, чтобы можно было последовательно сравнить их звучание.</li>
      <li><strong>Оценка качества PESQ и ViSQOL.</strong> Дополнительные оценки помогают исследовать изменения воспринимаемого качества относительно оригинала. Расчёт пока недоступен.</li>
      <li><strong>Транскрибация аудио.</strong> WAV отправляется локальному backend для распознавания. Если модель не подключена, показывается сообщение о недоступности.</li>
    </ul>
  </section>
  <section className="how-section" aria-labelledby="process-heading">
    <div className="info-heading"><h2 id="process-heading">Как устроен процесс</h2><p>Три шага в одной рабочей области.</p></div>
    <ol className="steps">
      <li><span className="step-number" aria-hidden="true">1</span><h3>Загрузите аудиофайл</h3><p>Выберите одну запись или перетащите её в рабочую область. Прослушайте оригинал перед запуском.</p></li>
      <li><span className="step-number" aria-hidden="true">2</span><h3>Запустите маскирование</h3><p>Маскирование станет доступно после подключения алгоритма. Пока можно прослушать оригинал и запросить транскрибацию.</p></li>
      <li><span className="step-number" aria-hidden="true">3</span><h3>Изучите результат</h3><p>После подключения обработки можно будет сравнить звучание и запросить оценку качества. Транскрибация доступна через локальный backend при подключённой модели.</p></li>
    </ol>
  </section>
  <section className="how-section" aria-labelledby="analysis-heading">
    <h2 id="analysis-heading">Анализ результата</h2>
    <p className="info-copy">Сравнение с оригиналом помогает услышать, как изменились звучание и разборчивость записи. Прослушивание дополняет числовые оценки и позволяет заметить искажения, которые одно число не описывает полностью.</p>
    <p className="info-copy">На экране результата можно отдельно запросить PESQ и ViSQOL или транскрибацию оригинала, результата либо обеих записей. Метрики описывают качество относительно эталона, но сами по себе не доказывают эффективность сокрытия информации.</p>
    <div className="form-actions"><a className="text-button" href="/how-it-works#quality">Подробнее об оценке качества</a></div>
  </section>
  <section className="how-section" aria-labelledby="start-heading">
    <h2 id="start-heading">Перейдите к работе с аудио</h2><p className="info-copy">Выберите запись, прослушайте оригинал и запросите транскрибацию через локальный backend AudioMask.</p>
    <div className="form-actions"><a className="button primary" href="/process">Перейти к обработке</a></div>
  </section></>;
}
