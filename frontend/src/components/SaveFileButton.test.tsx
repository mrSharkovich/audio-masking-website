import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { expect, it, vi } from 'vitest';
import { SaveFileButton } from './SaveFileButton';

it('opens the picker from the keyboard and treats cancellation as a normal outcome', async () => {
  const picker = vi.fn().mockRejectedValue(new DOMException('Cancelled', 'AbortError'));
  vi.stubGlobal('showSaveFilePicker', picker);
  const user = userEvent.setup();
  render(<SaveFileButton label="Сохранить" filename="report.txt" extension=".txt" content={() => 'Пример'} />);
  await user.tab();
  await user.keyboard('{Enter}');
  expect(picker).toHaveBeenCalledWith({ suggestedName: 'report.txt',
    types: [{ description: 'Текстовый файл', accept: { 'text/plain': ['.txt'] } }],
  });
  await waitFor(() => expect(screen.getByRole('button', { name: 'Сохранить' })).toBeEnabled());
  expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  expect(URL.createObjectURL).not.toHaveBeenCalled();
});

it('falls back to a Blob download when the picker is absent', async () => {
  vi.stubGlobal('showSaveFilePicker', undefined);
  let filename = '';
  const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function (this: HTMLAnchorElement) {
    filename = this.download;
  });
  render(<SaveFileButton label="Сохранить" filename="report.md" extension=".md" content={() => 'Пример'} />);
  await userEvent.setup().click(screen.getByRole('button', { name: 'Сохранить' }));
  expect(click).toHaveBeenCalledOnce();
  expect(filename).toBe('report.md');
  expect(URL.createObjectURL).toHaveBeenCalledWith(expect.objectContaining({ type: 'text/markdown;charset=utf-8' }));
  expect(document.querySelector('a[download]')).toBeNull();
});
