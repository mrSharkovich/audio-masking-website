import { act, renderHook } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { useTheme } from './useTheme';

function systemTheme(initialDark: boolean) {
  let dark = initialDark;
  const listeners = new Set<() => void>();
  vi.stubGlobal('matchMedia', () => ({
    get matches() { return dark; },
    addEventListener: (_event: string, listener: () => void) => listeners.add(listener),
    removeEventListener: (_event: string, listener: () => void) => listeners.delete(listener),
  }));
  return (next: boolean) => { dark = next; act(() => listeners.forEach((listener) => listener())); };
}

describe('theme behavior', () => {
  it.each([true, false])('uses the system theme (%s) without storage', (dark) => {
    systemTheme(dark);
    const getItem = vi.spyOn(Storage.prototype, 'getItem');
    const setItem = vi.spyOn(Storage.prototype, 'setItem');
    const cookieGet = vi.spyOn(document, 'cookie', 'get');
    const cookieSet = vi.spyOn(document, 'cookie', 'set');
    const fetch = vi.fn(); vi.stubGlobal('fetch', fetch);
    const { result } = renderHook(useTheme);
    expect(result.current.theme).toBe(dark ? 'dark' : 'light');
    act(() => result.current.toggle());
    expect(getItem).not.toHaveBeenCalled(); expect(setItem).not.toHaveBeenCalled();
    expect(cookieGet).not.toHaveBeenCalled(); expect(cookieSet).not.toHaveBeenCalled();
    expect(fetch).not.toHaveBeenCalled();
  });
  it('follows changes until manual choice and resets on a fresh mount', () => {
    const change = systemTheme(false);
    const { result, unmount } = renderHook(useTheme);
    change(true); expect(result.current.theme).toBe('dark');
    change(false); expect(result.current.theme).toBe('light');
    act(() => result.current.toggle()); expect(result.current.theme).toBe('dark');
    change(true); change(false); expect(result.current.theme).toBe('dark');
    unmount();
    const fresh = renderHook(useTheme);
    expect(fresh.result.current.theme).toBe('light');
    change(true); expect(fresh.result.current.theme).toBe('dark');
  });
});
