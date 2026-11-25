import { act, fireEvent, render, screen } from '@testing-library/react';
import { expect, it, vi } from 'vitest';
import { QualityPanel } from './QualityPanel';
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
