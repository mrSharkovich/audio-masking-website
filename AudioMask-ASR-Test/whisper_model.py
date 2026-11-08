class Recognizer:
    def __init__(self, path):
        from faster_whisper import WhisperModel
        self.model = WhisperModel(str(path), device='cpu', compute_type='int8',
            cpu_threads=4, num_workers=1, local_files_only=True)

    def transcribe(self, path, language):
        segments, _ = self.model.transcribe(str(path), language={'rus':'ru', 'eng':'en'}[language],
            task='transcribe', beam_size=5, temperature=0, vad_filter=False,
            condition_on_previous_text=False)
        return ' '.join(segment.text.strip() for segment in segments)
