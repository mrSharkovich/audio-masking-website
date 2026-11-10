from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
import wave

import numpy as np

from app.audio import prepare_wav, validate_wav
from app.config import Settings
from test_api import wav


class AudioTests(unittest.TestCase):
    def test_48khz_stereo_conversion_preserves_source_and_signal(self):
        rate = 48000
        tone = np.rint(np.sin(2 * np.pi * 1000 * np.arange(rate) / rate) * 12000).astype("<i2")
        with TemporaryDirectory() as directory:
            source, target = Path(directory) / "source.wav", Path(directory) / "prepared.wav"
            with wave.open(str(source), "wb") as audio:
                audio.setnchannels(2)
                audio.setsampwidth(2)
                audio.setframerate(rate)
                audio.writeframes(np.column_stack([tone, tone]).tobytes())
            original = source.read_bytes()
            self.assertEqual(prepare_wav(source, target, Settings()), target)
            self.assertEqual(source.read_bytes(), original)
            info = validate_wav(target, Settings())
            self.assertEqual((info.rate, info.channels, info.width, info.frames), (16000, 1, 2, 16000))
            with wave.open(str(target), "rb") as audio:
                signal = np.frombuffer(audio.readframes(info.frames), dtype="<i2")
            peak = np.argmax(abs(np.fft.rfft(signal)))
            self.assertEqual(peak, 1000)
            self.assertGreater(np.max(signal), 11000)
            self.assertLessEqual(np.max(signal), 12500)

    def test_normalized_input_is_not_rewritten(self):
        with TemporaryDirectory() as directory:
            source, target = Path(directory) / "source.wav", Path(directory) / "prepared.wav"
            source.write_bytes(wav())
            self.assertEqual(prepare_wav(source, target, Settings()), source)
            self.assertFalse(target.exists())
            self.assertEqual(source.read_bytes(), wav())

    def test_pcm_widths_and_sample_rates(self):
        for width in [1, 2, 3, 4]:
            for rate in [8000, 44100, 48000, 96000]:
                with self.subTest(width=width, rate=rate), TemporaryDirectory() as directory:
                    source, target = Path(directory) / "a.wav", Path(directory) / "b.wav"
                    source.write_bytes(wav(width=width, rate=rate, channels=2, frames=rate // 10))
                    result = prepare_wav(source, target, Settings())
                    self.assertEqual(validate_wav(result, Settings()).frames, 1600)

    def test_stereo_opposite_phase_downmix(self):
        with TemporaryDirectory() as directory:
            source, target = Path(directory) / "source.wav", Path(directory) / "prepared.wav"
            with wave.open(str(source), "wb") as audio:
                audio.setparams((2, 2, 16000, 160, "NONE", "not compressed"))
                audio.writeframes(np.tile([10000, -10000], 160).astype("<i2").tobytes())
            prepare_wav(source, target, Settings())
            with wave.open(str(target), "rb") as audio:
                self.assertEqual(audio.readframes(160), bytes(320))


if __name__ == "__main__":
    unittest.main()
