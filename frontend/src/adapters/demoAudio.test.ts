import { describe, expect, it } from 'vitest';
import { createDemoAdapters, createDemoTone } from './demoAudio';

describe('isolated demo adapters', () => {
  it('creates independent synthetic audio, never returning input as output', async () => {
    const source = new File(['not-a-wave-file'], 'source.audio');
    const result = await createDemoAdapters(0).masking.run(source, 'success');
    expect(result.status).toBe('success');
    if (result.status !== 'success') throw new Error('Expected demo success');
    expect(result.value.audio).not.toBe(source);
    expect(result.value.audio.type).toBe('audio/wav');
    expect(result.value.audio.size).toBe(createDemoTone().size);
    expect(result.value.fileName).toContain('not-masked');
    expect(result.value.demonstration).toBe(true);
  });
  it('returns explicit error and unavailable states', async () => {
    const adapter = createDemoAdapters(0);
    expect((await adapter.masking.run(new File(['test'], 'test.audio'), 'error')).status).toBe('error');
    expect((await adapter.masking.run(new File(['test'], 'test.audio'), 'unavailable')).status).toBe('unavailable');
    const quality = await adapter.quality.evaluate('demo', 'partial');
    expect(quality.PESQ.status).toBe('success'); expect(quality.ViSQOL.status).toBe('unavailable');
  });
  it('only returns requested sources and supports partial/empty answers', async () => {
    const adapter = createDemoAdapters(0).transcription;
    expect(await adapter.transcribe('demo', 'original', 'success')).not.toHaveProperty('masked');
    expect(await adapter.transcribe('demo', 'masked', 'success')).not.toHaveProperty('original');
    expect((await adapter.transcribe('demo', 'both', 'partial')).masked?.status).toBe('unavailable');
    expect((await adapter.transcribe('demo', 'original', 'empty')).original?.status).toBe('empty');
  });
});
