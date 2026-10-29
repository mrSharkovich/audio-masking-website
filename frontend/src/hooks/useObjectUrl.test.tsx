import { renderHook } from '@testing-library/react';
import { expect, it } from 'vitest';
import { useObjectUrl } from './useObjectUrl';

it('releases an old URL after replacement and the active URL on unmount', () => {
  const first = new Blob(['first']);
  const { result, rerender, unmount } = renderHook(({ blob }) => useObjectUrl(blob), { initialProps: { blob: first } });
  const firstUrl = result.current;
  rerender({ blob: new Blob(['second']) });
  expect(URL.revokeObjectURL).toHaveBeenCalledWith(firstUrl);
  expect(result.current).not.toBe(firstUrl);
  const secondUrl = result.current;
  unmount(); expect(URL.revokeObjectURL).toHaveBeenCalledWith(secondUrl);
});
