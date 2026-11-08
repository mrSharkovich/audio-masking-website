import types
import wave
import importlib.util
import sys
from pathlib import Path


class GigaRecognizer:
    def __init__(self, path):
        import torch
        torch.set_num_threads(4)
        torch.set_num_interop_threads(1)
        self.torch = torch
        # Import the audited local module directly. AutoModel's dynamic import
        # scanner may treat lazy longform-only imports as mandatory dependencies.
        source = Path(path)/'modeling_gigaam.py'
        spec = importlib.util.spec_from_file_location('modeling_gigaam', source)
        if spec is None or spec.loader is None:
            raise ImportError('Cannot load local modeling_gigaam.py')
        module = importlib.util.module_from_spec(spec)
        sys.modules['modeling_gigaam'] = module
        spec.loader.exec_module(module)
        self.model = module.GigaAMModel.from_pretrained(str(path),
            local_files_only=True).to('cpu').float().eval()
        # The official prepare_wav() calls a system ffmpeg executable. Replace only
        # that I/O boundary: the model, feature extraction and decoder stay intact.
        def prepare_wav(inner, wav_file):
            with wave.open(str(wav_file), 'rb') as audio:
                if audio.getnchannels() != 1 or audio.getframerate() != 16000 or audio.getsampwidth() != 2:
                    raise ValueError('GigaAM adapter requires mono 16 kHz PCM16 WAV')
                samples = bytearray(audio.readframes(audio.getnframes()))
            tensor = torch.frombuffer(samples, dtype=torch.int16).float().div_(32768).unsqueeze(0)
            return tensor, torch.tensor([tensor.shape[-1]], dtype=torch.long)
        self.model.model.prepare_wav = types.MethodType(prepare_wav, self.model.model)

    def transcribe(self, path, language):
        with self.torch.inference_mode():
            result = self.model.transcribe(str(path))
        if not isinstance(result, str):
            result = getattr(result, 'text', None)
        if not isinstance(result, str):
            raise TypeError('Model transcribe() must return a string; check model code revision')
        return result
