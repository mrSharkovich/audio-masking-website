import type { DemoOutcome, DemoSettings } from '../types/audio';

interface Props {
  settings: DemoSettings;
  locked: boolean;
  onChange: (settings: DemoSettings) => void;
}
const outcomes: { value: DemoOutcome; label: string }[] = [
  { value: 'success', label: 'Успех' },
  { value: 'error', label: 'Ошибка' },
  { value: 'unavailable', label: 'Недоступность' },
  { value: 'partial', label: 'Частичный результат' },
  { value: 'empty', label: 'Пустой текст' },
];

export function DemoControls({ settings, locked, onChange }: Props) {
  const fields = [
    { key: 'masking', label: 'Маскирование', values: outcomes.slice(0, 3) },
    { key: 'quality', label: 'Оценка качества', values: outcomes.slice(0, 4) },
    { key: 'transcription', label: 'Транскрибация', values: outcomes },
  ] as const;
  return <details className="demo-controls">
    <summary>Демонстрационные сценарии</summary>
    <p>Меняют только ответы для проверки интерфейса. Реальный алгоритм и сервисы не подключены.</p>
    <fieldset disabled={locked}>
      <legend className="visually-hidden">Настройки демонстрации</legend>
      <label className="check-label"><input type="checkbox" checked={settings.enabled} onChange={(event) => onChange({ ...settings, enabled: event.target.checked })} />Включить демонстрационный режим</label>
      <div className="demo-fields">
        {fields.map(({ key, label, values }) => <label key={key}>{label}
          <select value={settings[key]} onChange={(event) => onChange({ ...settings, [key]: event.target.value as DemoOutcome })}>
            {values.map((option) => <option value={option.value} key={option.value}>{option.label}</option>)}
          </select>
        </label>)}
      </div>
    </fieldset>
  </details>;
}
