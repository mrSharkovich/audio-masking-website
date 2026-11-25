import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { readBytes } from '../test/audio';
import userEvent from '@testing-library/user-event';
import { expect, it, vi } from 'vitest';
import { QualityPanel } from './QualityPanel';
import { qualityInterpretation } from './qualityInterpretation';
import type { QualityEvaluationAdapter, QualityScores } from '../adapters/httpQuality';

const audio = new Blob(['test']);
const recordings = { original: audio, masked: audio, demasked: audio };
const lattice = { status: 'unavailable', message: 'Модель недоступна.' } as const;
const scores: QualityScores = {
  masked: { PESQ: { status: 'success', value: 4.321 }, ViSQOL: { status: 'success', value: 3.7 }, ViSQOL_LATTICE: lattice },
  demasked: { PESQ: { status: 'error', message: 'Ошибка расчёта.' }, ViSQOL: { status: 'success', value: 3.2 }, ViSQOL_LATTICE: lattice },
  masked_demasked: { PESQ: { status: 'success', value: 4.1 }, ViSQOL: { status: 'success', value: 4.2 }, ViSQOL_LATTICE: { status: 'success', value: 4.3 } },
};
const status: QualityEvaluationAdapter['status'] = async () => ({
  PESQ: { status: 'available' }, ViSQOL: { status: 'available' }, ViSQOL_LATTICE: { status: 'available' },
});

it('exports the current quality table without recalculating', async () => {
  const write = vi.fn().mockResolvedValue(undefined);
  const picker = vi.fn().mockResolvedValue({ createWritable: async () => ({ write, close: async () => {} }) });
  vi.stubGlobal('showSaveFilePicker', picker);
  let finish!: (value: QualityScores) => void;
  const evaluate = vi.fn(() => new Promise<QualityScores>((done) => { finish = done; }));
  render(<QualityPanel recordings={recordings} recordingNames={{ original: 'голос|1.mp3', masked: 'test-masked.wav' }}
    testMode adapter={{ status, evaluate }} />);
  const save = screen.getByRole('button', { name: 'Сохранить оценки качества' });
  expect(save).toBeDisabled();
  await act(async () => {});
  fireEvent.click(screen.getByRole('button', { name: 'Оценить качество' }));
  expect(save).toBeDisabled();
  await act(async () => finish({ masked: { ...scores.masked!, ViSQOL: { status: 'error', message: 'Сбой' } } }));
  fireEvent.click(save);
  await waitFor(() => expect(write).toHaveBeenCalledOnce());
  expect(picker).toHaveBeenCalledWith(expect.objectContaining({ suggestedName: 'audiomask-quality.md' }));
  const blob = write.mock.calls[0][0] as Blob;
  expect(blob.type).toBe('text/markdown;charset=utf-8');
  const text = new TextDecoder().decode(await readBytes(blob));
  expect(text).toContain('| Сравнение | PESQ | ViSQOL | ViSQOL с lattice |');
  expect(text).toContain('| Исходная (голос\\|1.mp3) — Тестовая маскированная копия (test-masked.wav) | 4,321 | Ошибка: Сбой | Недоступно: Модель недоступна. |');
  expect(text.match(/Не рассчитано/g)).toHaveLength(6);
  expect(evaluate).toHaveBeenCalledOnce();
});

it('opens metric help from the heading using the keyboard and dismisses it without changing the selection', async () => {
  const adapter = { status, evaluate: vi.fn().mockResolvedValue(scores) };
  const user = userEvent.setup();
  render(<QualityPanel recordings={recordings} testMode={false} adapter={adapter} />);
  const heading = screen.getByRole('heading', { name: 'Оценка качества аудио' });
  const info = screen.getByRole('button', { name: 'Как интерпретировать оценки' });
  expect(heading.nextElementSibling).toBe(info);
  await user.tab();
  expect(info).toHaveFocus();
  await user.keyboard('{Enter}');
  const popup = screen.getByRole('dialog', { name: 'Как интерпретировать оценки' });
  expect(popup).toHaveFocus();
  expect(info).toHaveAttribute('aria-expanded', 'true');
  for (const metric of ['PESQ (1–4,65)', 'ViSQOL (1–5)', 'ViSQOL с lattice (1–5)']) {
    expect(within(popup).getByText(metric)).toBeInTheDocument();
  }
  expect(within(popup).getByRole('heading', { name: 'Условная шкала качества' })).toBeInTheDocument();
  expect(within(popup).getAllByRole('listitem')).toHaveLength(4);
  expect(within(popup).getByText(/практический максимум — около 4,644/)).toBeInTheDocument();
  expect(within(popup).getByText(/Метрики не доказывают стойкость/)).toBeInTheDocument();
  expect(within(popup).queryByText(/плавно изменяется|разные модели оценивания|универсальные/)).not.toBeInTheDocument();
  await user.keyboard('{Escape}');
  expect(popup).not.toBeInTheDocument();
  expect(info).toHaveFocus();
  await user.keyboard(' ');
  expect(screen.getByRole('dialog')).toBeInTheDocument();
  await user.click(info);
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  await user.click(info);
  await user.click(heading);
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  expect(screen.getAllByRole('checkbox').filter((box) => (box as HTMLInputElement).checked)).toHaveLength(1);
  expect(adapter.evaluate).not.toHaveBeenCalled();
  await user.click(screen.getByRole('button', { name: 'Оценить качество' }));
  expect(await screen.findByText('4,321')).toBeInTheDocument();
  expect(adapter.evaluate).toHaveBeenCalledWith(recordings, ['masked'], expect.any(AbortSignal));
});

it.each([[1, 'Низкое'], [2.4999, 'Низкое'], [2.5, 'Среднее'], [2.5001, 'Среднее'],
  [3.4999, 'Среднее'], [3.5, 'Высокое'], [3.5001, 'Высокое']])(
  'classifies the unrounded score %s', (value, label) => {
    expect(qualityInterpretation('PESQ', value)?.label).toBe(`${label} качество`);
  },
);

it('interpolates the full hue scale per metric without jumps at category boundaries', () => {
  for (const [metric, max] of [['PESQ', 4.643888], ['ViSQOL', 5], ['ViSQOL_LATTICE', 5]] as const) {
    expect(qualityInterpretation(metric, 1)?.hue).toBe(0);
    expect(qualityInterpretation(metric, max)).toEqual({ hue: 140, label: 'Максимальное качество' });
    expect(qualityInterpretation(metric, (1 + max) / 2)?.hue).toBeCloseTo(70);
    for (const boundary of [2.5, 3.5]) {
      const below = qualityInterpretation(metric, boundary - 0.0001)!.hue;
      const above = qualityInterpretation(metric, boundary + 0.0001)!.hue;
      expect(above - below).toBeGreaterThan(0);
      expect(above - below).toBeLessThan(0.01);
    }
  }
  expect(qualityInterpretation('ViSQOL', 3.6)!.hue).toBeLessThan(qualityInterpretation('ViSQOL', 4.9)!.hue);
  expect(qualityInterpretation('ViSQOL', 4.65)!.hue).toBeLessThan(140);
});

it('distinguishes practical maxima from the rounded score and the API limit', () => {
  for (const value of [4.643888473510742, 4.65]) {
    expect(qualityInterpretation('PESQ', value)).toEqual({ hue: 140, label: 'Максимальное качество' });
  }
  expect(qualityInterpretation('PESQ', 4.6437)?.label).toBe('Высокое качество');
  expect(qualityInterpretation('PESQ', 4.6437)!.hue).toBeLessThan(140);
  for (const metric of ['ViSQOL', 'ViSQOL_LATTICE'] as const) {
    expect(qualityInterpretation(metric, 4.9999)?.label).toBe('Высокое качество');
  }
  expect(qualityInterpretation('ViSQOL_LATTICE', 3.94)?.label).toBe('Высокое качество');
});

it.each([undefined, NaN, Infinity, -Infinity, 0.999, 4.651, '3.5'])('rejects an invalid PESQ value (%s)', (value) => {
  expect(qualityInterpretation('PESQ', value)).toBeNull();
  expect(qualityInterpretation('ViSQOL', 5.001)).toBeNull();
});

it('uses the same hue for label and dot and only classifies valid successes', async () => {
  const evaluate = vi.fn().mockResolvedValue({ masked: {
    PESQ: { status: 'success', value: 3.4999 },
    ViSQOL: { status: 'success', value: NaN },
    ViSQOL_LATTICE: { status: 'unavailable', message: 'Нет модели' },
  } });
  render(<QualityPanel recordings={recordings} testMode={false} adapter={{ status, evaluate }} />);
  await act(async () => {});
  fireEvent.click(screen.getByRole('button', { name: 'Оценить качество' }));
  expect(screen.getAllByText('Вычисляется')).toHaveLength(3);
  const label = await screen.findByText('Среднее качество');
  expect(screen.getByText('3,5')).toHaveClass('metric-value');
  expect(Number(label.style.getPropertyValue('--quality-hue'))).toBeCloseTo((3.4999 - 1) / 3.643888 * 140);
  expect(label.firstElementChild).toHaveAttribute('aria-hidden', 'true');
  expect((label.firstElementChild as HTMLElement).style.backgroundColor.toLowerCase()).toBe('currentcolor');
  expect(screen.getByText('Сервер вернул некорректный результат.')).toBeVisible();
  expect(screen.getByText('Недоступно')).toBeVisible();
  for (const name of ['PESQ', 'ViSQOL', 'ViSQOL с lattice']) expect(screen.getByText(name, { exact: true })).toBeVisible();
  expect(screen.getAllByText(/^(Низкое|Среднее|Высокое) качество$/)).toHaveLength(1);
});

it('runs only on demand and shows independent results with a copy notice', async () => {
  const adapter = { status, evaluate: vi.fn().mockResolvedValue(scores) };
  render(<QualityPanel recordings={recordings} testMode adapter={adapter} />);
  await act(async () => {});
  expect(adapter.evaluate).not.toHaveBeenCalled();
  expect(screen.getByText(/сравниваются копии аудио/)).toBeInTheDocument();
  const [first, second, third] = screen.getAllByRole('checkbox');
  expect(first).toBeChecked();
  expect(second).not.toBeChecked();
  expect(third).not.toBeChecked();
  fireEvent.click(screen.getByRole('button', { name: 'Оценить качество' }));
  expect(await screen.findByText('4,321')).toBeInTheDocument();
  expect(screen.queryByText('3,2')).not.toBeInTheDocument();
  expect(screen.getByText('Недоступно')).toBeInTheDocument();
  fireEvent.click(first);
  expect(screen.getByRole('button', { name: 'Оценить качество' })).toBeDisabled();
  expect(screen.queryByText('4,321')).not.toBeInTheDocument();
  fireEvent.click(second);
  fireEvent.click(third);
  fireEvent.click(screen.getByRole('button', { name: 'Оценить качество' }));
  expect(await screen.findByText('4,3')).toBeInTheDocument();
  expect(adapter.evaluate).toHaveBeenLastCalledWith(recordings, ['demasked', 'masked_demasked'], expect.any(AbortSignal));
  expect(screen.getByText('3,2')).toBeInTheDocument();
  expect(screen.getByText('Ошибка расчёта.')).toBeInTheDocument();
});

it.each(['cancel', 'replace'])('ignores a late response after %s', async (event) => {
  let finish!: (value: QualityScores) => void;
  const evaluate = vi.fn<QualityEvaluationAdapter['evaluate']>(() =>
    new Promise<QualityScores>((resolve) => { finish = resolve; }));
  const adapter = { status, evaluate };
  const { rerender } = render(<QualityPanel key="old" recordings={recordings} testMode={false} adapter={adapter} />);
  await act(async () => {});
  fireEvent.click(screen.getByRole('button', { name: 'Оценить качество' }));
  expect(screen.getAllByRole('checkbox').every((box) => (box as HTMLInputElement).disabled)).toBe(true);
  if (event === 'cancel') {
    fireEvent.click(screen.getByRole('button', { name: 'Отменить оценку' }));
    expect(screen.getByText('Оценка отменена.')).toBeInTheDocument();
  } else {
    rerender(<QualityPanel key="new" recordings={recordings} testMode={false} adapter={adapter} />);
  }
  await act(async () => finish(scores));
  expect(evaluate.mock.calls[0][2].aborted).toBe(true);
  expect(screen.queryByText('4,321')).not.toBeInTheDocument();
  expect(screen.queryByText(/сравниваются копии аудио/)).not.toBeInTheDocument();
});
