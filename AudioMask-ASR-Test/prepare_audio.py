"""PyAV bundles FFmpeg; source files are never opened for writing."""
import shutil
import wave
from pathlib import Path
from dataset import inspect_wav


def prepare(source, target):
    source, target = Path(source), Path(target)
    if source.resolve() == target.resolve():
        raise ValueError('Source and destination must differ')
    target.parent.mkdir(parents=True, exist_ok=True)
    info = inspect_wav(source)
    if info['channels'] == 1 and info['sample_rate'] == 16000 and info['bits'] == 16:
        shutil.copyfile(source, target)
        return target
    import av
    resampler = av.AudioResampler(format='s16', layout='mono', rate=16000)
    with av.open(str(source)) as container, wave.open(str(target), 'wb') as out:
        stream = container.streams.audio[0]
        stream.codec_context.thread_count = 1
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(16000)
        for frame in container.decode(stream):
            for converted in resampler.resample(frame):
                out.writeframes(converted.to_ndarray().tobytes())
        for converted in resampler.resample(None):
            out.writeframes(converted.to_ndarray().tobytes())
    converted = inspect_wav(target)
    if abs(converted['duration_s']-info['duration_s']) > 0.1:
        raise ValueError('Unexpected duration change during conversion')
    return target
