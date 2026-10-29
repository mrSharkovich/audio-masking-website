import { act, renderHook } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { useWorkspace } from './useWorkspace';
import type { AudioResult, DemoSettings, OperationValue } from '../types/audio';

const settings: DemoSettings = { enabled: true, masking: 'success', quality: 'success', transcription: 'success' };
const source = () => new File(['synthetic test input'], 'fixture.audio', { type: 'audio/test' });
const demoResult = (): AudioResult => ({ id: crypto.randomUUID(), audio: new Blob(['independent fixture']), fileName: 'demo.wav', demonstration: true });

describe('workspace transitions', () => {
  it('locks every file mutation and duplicate runs until success', async () => {
    let resolve!: (value: OperationValue<AudioResult>) => void;
    const adapter = { run: vi.fn(() => new Promise<OperationValue<AudioResult>>((done) => { resolve = done; })) };
    const { result } = renderHook(() => useWorkspace(adapter));
    const first = source();
    act(() => result.current.selectFiles([first]));
    let pending!: Promise<void>;
    act(() => { pending = result.current.run(settings); });
    expect(result.current.busy).toBe(true);
    act(() => { result.current.clear(); result.current.selectFiles([source()]); void result.current.run(settings); });
    expect(result.current.source).toBe(first); expect(adapter.run).toHaveBeenCalledTimes(1);
    await act(async () => { resolve({ status: 'success', value: demoResult() }); await pending; });
    expect(result.current.busy).toBe(false); expect(result.current.view).toBe('result');
    act(() => result.current.showForm()); expect(result.current.view).toBe('form');
    act(() => result.current.showResult()); expect(result.current.view).toBe('result');
    expect(adapter.run).toHaveBeenCalledTimes(1);
    act(() => result.current.clear()); expect(result.current.source).toBeNull(); expect(result.current.result).toBeNull();
  });
  it('preserves a previous result on retry failure and unlocks the file', async () => {
    const previous = demoResult();
    const adapter = { run: vi.fn().mockResolvedValueOnce({ status: 'success', value: previous }).mockResolvedValueOnce({ status: 'error', message: 'Test error' }) };
    const { result } = renderHook(() => useWorkspace(adapter));
    act(() => result.current.selectFiles([source()]));
    await act(() => result.current.run(settings));
    act(() => result.current.showForm());
    await act(() => result.current.run(settings));
    expect(result.current.busy).toBe(false); expect(result.current.result).toBe(previous);
    act(() => result.current.showResult()); expect(result.current.view).toBe('result');
    act(() => result.current.selectFiles([source()])); expect(result.current.result).toBeNull();
  });
  it('rejects empty/multiple files and does not fake success outside demo', async () => {
    const adapter = { run: vi.fn() };
    const { result } = renderHook(() => useWorkspace(adapter));
    act(() => result.current.selectFiles([source(), source()])); expect(result.current.source).toBeNull();
    act(() => result.current.selectFiles([new File([], 'empty.audio')])); expect(result.current.error).toContain('пуст');
    act(() => result.current.selectFiles([source()]));
    await act(() => result.current.run({ ...settings, enabled: false }));
    expect(adapter.run).not.toHaveBeenCalled(); expect(result.current.result).toBeNull();
    expect(result.current.error).toContain('недоступна');
  });
});
