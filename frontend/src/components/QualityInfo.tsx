import { useEffect, useId, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { qualityMinimum, qualityScales } from '../adapters/httpQuality';
import type { MetricName } from '../types/audio';

function metricRange(metric: MetricName) {
  const { label, max } = qualityScales[metric];
  return `${label} (${qualityMinimum}–${max.toLocaleString('ru-RU')})`;
}

export function QualityInfo() {
  const [open, setOpen] = useState(false);
  const id = useId();
  const trigger = useRef<HTMLButtonElement>(null);
  const popup = useRef<HTMLDivElement>(null);

  function close() {
    setOpen(false);
    trigger.current?.focus();
  }

  useEffect(() => {
    if (!open) return;
    popup.current?.focus();
    function dismissOutside(event: PointerEvent) {
      if (event.target instanceof Node && !trigger.current?.contains(event.target) && !popup.current?.contains(event.target)) {
        setOpen(false);
      }
    }
    function dismissOnEscape(event: KeyboardEvent) {
      if (event.key === 'Escape') close();
    }
    document.addEventListener('pointerdown', dismissOutside);
    document.addEventListener('keydown', dismissOnEscape);
    return () => {
      document.removeEventListener('pointerdown', dismissOutside);
      document.removeEventListener('keydown', dismissOnEscape);
    };
  }, [open]);

  return <>
    <button type="button" className="demo-icon quality-info-trigger" ref={trigger}
      aria-label="Как интерпретировать оценки" aria-haspopup="dialog" aria-expanded={open}
      aria-controls={open ? id : undefined} onClick={() => setOpen(!open)}>i</button>
    {open ? createPortal(
      <div className="quality-info" id={id} role="dialog" aria-labelledby={`${id}-title`} tabIndex={-1} ref={popup}>
        <div className="panel-title">
          <h4 id={`${id}-title`}>Как интерпретировать оценки</h4>
          <button type="button" className="text-button" aria-label="Закрыть описание метрик" onClick={close}>×</button>
        </div>
        <dl>
          <dt>{metricRange('PESQ')}</dt>
          <dd>Воспринимаемое качество речи относительно эталона.</dd>
          <dt>{metricRange('ViSQOL')}</dt>
          <dd>Воспринимаемое качество аудио относительно эталона.</dd>
          <dt>{metricRange('ViSQOL_LATTICE')}</dt>
          <dd>Оценка качества с использованием lattice-модели.</dd>
        </dl>
        <h4>Условная шкала качества</h4>
        <ul>
          <li>1–2,5 — низкое.</li>
          <li>2,5–3,5 — среднее.</li>
          <li>От 3,5 — высокое.</li>
          <li>При достижении максимума метрики — максимальное.</li>
        </ul>
        <p>Для PESQ практический максимум — около 4,644.</p>
        <p>Границы 2,5 и 3,5 относятся к следующей категории.</p>
        <p>Для маскированной записи предпочтительны низкие оценки, для демаскированной — высокие.</p>
        <p>Метрики не доказывают стойкость маскирования или точность восстановления сигнала.</p>
      </div>,
      document.body,
    ) : null}
  </>;
}
