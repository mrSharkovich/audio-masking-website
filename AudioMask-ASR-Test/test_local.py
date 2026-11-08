"""Offline synthetic checks only. No model imports, package installs or downloads.

Generated fixtures stay inside .checks/<unique-id>/ in this kit.
"""
import csv
import contextlib
import json
from pathlib import Path
import struct
import subprocess
import sys
import unittest
import uuid
import wave
from types import SimpleNamespace
from unittest.mock import patch

from dataset import fingerprint, inspect_wav, validate, word_errors, tokens, write_csv
from prepare_audio import prepare
from report import build_report
from worker import split_audio

ROOT = Path(__file__).resolve().parent
SESSION = ROOT/'.checks'/uuid.uuid4().hex


def create_wav(path, seconds=0.1, rate=16000, channels=1):
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), 'wb') as stream:
        stream.setnchannels(channels)
        stream.setsampwidth(2)
        stream.setframerate(rate)
        stream.writeframes(struct.pack('<h', 100)*round(rate*seconds)*channels)


class LocalChecks(unittest.TestCase):
    def setUp(self):
        self.folder = SESSION/self._testMethodName
        self.data = self.folder/'data'
        for language in ('rus','eng'):
            for i in range(1,11):
                create_wav(self.data/language/'audio'/f'{i}.wav')
                txt = self.data/language/'text'/f'{i}.txt'
                txt.parent.mkdir(parents=True, exist_ok=True)
                txt.write_text('Тест речи' if language == 'rus' else 'Speech test', encoding='utf-8')

    def test_valid_dataset_and_metadata(self):
        rows, errors = validate(self.data)
        self.assertEqual(errors, [])
        self.assertEqual(len(rows), 20)
        self.assertEqual(rows[0]['sample_rate'], 16000)
        self.assertEqual(rows[0]['channels'], 1)
        self.assertAlmostEqual(rows[0]['duration_s'], .1)
        self.assertEqual(rows[0]['bits'], 16)

    def test_missing_pair(self):
        path = self.data/'eng'/'text'/'1.txt'
        path.rename(path.with_suffix('.missing'))
        rows, errors = validate(self.data)
        self.assertEqual(len(rows), 19)
        self.assertTrue(any('eng/1' in e for e in errors))

    def test_extra_files(self):
        create_wav(self.data/'eng'/'audio'/'11.wav')
        self.assertTrue(any('extra' in e for e in validate(self.data)[1]))

    def test_invalid_utf8(self):
        (self.data/'rus'/'text'/'1.txt').write_bytes(b'\xff\xfe\x00')
        self.assertEqual(len(validate(self.data)[0]), 19)

    def test_empty_reference(self):
        (self.data/'rus'/'text'/'1.txt').write_text(' ... ', encoding='utf-8')
        self.assertTrue(any('Empty reference' in e for e in validate(self.data)[1]))

    def test_utf8_bom_accepted(self):
        (self.data/'rus'/'text'/'1.txt').write_text('Привет', encoding='utf-8-sig')
        self.assertFalse(validate(self.data)[1])

    def test_fake_wav(self):
        (self.data/'eng'/'audio'/'1.wav').write_bytes(b'not a wave file')
        self.assertEqual(len(validate(self.data)[0]), 19)

    def test_truncated_wav(self):
        path = self.data/'rus'/'audio'/'1.wav'
        path.write_bytes(path.read_bytes()[:-20])
        self.assertTrue(any('Truncated' in e for e in validate(self.data)[1]))

    def test_empty_wav(self):
        create_wav(self.data/'rus'/'audio'/'1.wav', seconds=0)
        self.assertEqual(len(validate(self.data)[0]), 19)

    def test_wer_observable_examples(self):
        self.assertEqual(word_errors('one two three', 'one four three'), (1,3))
        self.assertEqual(word_errors('one two', 'one'), (1,2))
        self.assertEqual(word_errors('one', 'one two three'), (2,1))
        self.assertEqual(word_errors('one two', ''), (2,2))
        self.assertEqual(word_errors('Ёлка, ТЕСТ!', 'елка тест'), (0,2))
        with self.assertRaises(ValueError):
            word_errors('...', 'word')

    def test_chunk_boundaries_and_source_unchanged(self):
        source = self.folder/'long.wav'
        create_wav(source, seconds=40.1)
        digest = fingerprint(source)
        chunks = split_audio(source, self.folder/'chunks')
        self.assertEqual(len(chunks), 3)
        self.assertAlmostEqual(sum(inspect_wav(p)['duration_s'] for p in chunks), 40.1)
        self.assertTrue(all(inspect_wav(p)['duration_s'] <= 20 for p in chunks))
        self.assertEqual(fingerprint(source), digest)

    def test_copy_preserves_source(self):
        source = self.data/'rus'/'audio'/'1.wav'
        digest = fingerprint(source)
        target = prepare(source, self.folder/'copy.wav')
        self.assertEqual(fingerprint(target), digest)
        self.assertEqual(fingerprint(source), digest)
        with self.assertRaises(ValueError):
            prepare(source, source)

    def test_report_corpus_wer_and_incomplete(self):
        run = self.folder/'experiment'
        folder = run/'whisper'
        folder.mkdir(parents=True)
        (run/'whisper.status.json').write_text(json.dumps(dict(model='whisper',status='ok',peak_rss_mib=123,reason='')), encoding='utf-8')
        (folder/'metadata.json').write_text('{"load_s": 1.5}', encoding='utf-8')
        rows = [dict(language='rus',id=i,status='ok',reference_words=10 if i else 100,
            errors=1,recognition_s=1,duration_s=2) for i in range(10)]
        write_csv(folder/'results.csv', rows)
        build_report(run)
        with (run/'summary.csv').open(encoding='utf-8-sig', newline='') as stream:
            summary = list(csv.DictReader(stream))
        self.assertAlmostEqual(float(summary[0]['wer']), 10/190)
        self.assertEqual(summary[1]['wer'], '')
        self.assertEqual(summary[1]['status'], 'incomplete')
        (run/'whisper.status.json').write_text(json.dumps(dict(model='whisper',status='error',peak_rss_mib=123,reason='Timeout')), encoding='utf-8')
        build_report(run)
        with (run/'summary.csv').open(encoding='utf-8-sig', newline='') as stream:
            self.assertEqual(next(csv.DictReader(stream))['wer'], '')

    def test_download_requires_permission_before_import(self):
        from manage import download
        with self.assertRaisesRegex(ValueError, 'denied'):
            download('whisper', False)

    def test_gigaam_result_contract(self):
        from gigaam_common import GigaRecognizer
        recognizer = object.__new__(GigaRecognizer)
        recognizer.torch = SimpleNamespace(inference_mode=contextlib.nullcontext)
        recognizer.model = SimpleNamespace(transcribe=lambda path: SimpleNamespace(text='test text'))
        self.assertEqual(recognizer.transcribe('unused.wav', 'eng'), 'test text')
        recognizer.model = SimpleNamespace(transcribe=lambda path: 'тест речи')
        self.assertEqual(recognizer.transcribe('unused.wav', 'rus'), 'тест речи')
        recognizer.model = SimpleNamespace(transcribe=lambda path: None)
        with self.assertRaises(TypeError):
            recognizer.transcribe('unused.wav', 'rus')

    def test_cli_dataset_exit_codes(self):
        command = [sys.executable,'-B',str(ROOT/'benchmark.py'),'check-data','--data',str(self.data),
            '--output',str(self.folder/'validation')]
        result = subprocess.run(command, capture_output=True, text=True, encoding='utf-8')
        self.assertEqual(result.returncode, 0, result.stderr)
        (self.data/'rus'/'audio'/'1.wav').write_bytes(b'bad')
        result = subprocess.run(command, capture_output=True, text=True, encoding='utf-8')
        self.assertEqual(result.returncode, 2, result.stderr)

    def check_watchdog(self, simulated_rss, timeout, expected_reason):
        # A real short-lived sleeper process, simulated memory readings, no ASR.
        import benchmark
        kit = self.folder/'supervisor-kit'
        weights = kit/'models'/'whisper'
        weights.mkdir(parents=True)
        (weights/'config.json').write_text('{}', encoding='utf-8')
        child_holder = []
        real_popen = subprocess.Popen
        real_is_file = Path.is_file

        def launch_unused_worker(command, **kwargs):
            process = real_popen([sys.executable, '-B', '-c', 'import time; time.sleep(5)'], **kwargs)
            child_holder.append(process)
            return process

        class FakeProcess:
            def __init__(self, pid):
                self.pid = pid

            def cpu_affinity(self, values=None):
                return [0,1,2,3]

            def children(self, recursive=False):
                return []

            def memory_info(self):
                return SimpleNamespace(rss=simulated_rss, peak_wset=simulated_rss)

            def kill(self):
                child_holder[0].kill()

        fake_psutil = SimpleNamespace(Process=FakeProcess, NoSuchProcess=ProcessLookupError,
            virtual_memory=lambda: SimpleNamespace(available=1024**3))
        args = SimpleNamespace(data=str(self.data), output=str(self.folder/'runs'), model='whisper',
            version='3.13', ram_mib=256, timeout=timeout)
        def synthetic_executable(path):
            return True if path == kit/'.venvs'/'whisper-3.13'/'Scripts'/'python.exe' else real_is_file(path)
        with patch.object(benchmark, 'ROOT', kit), patch.dict(sys.modules, {'psutil':fake_psutil}), \
                patch.object(subprocess, 'Popen', side_effect=launch_unused_worker), \
                patch.object(Path, 'is_file', synthetic_executable):
            self.assertEqual(benchmark.supervise(args), 2)
        status = next((self.folder/'runs').glob('*/whisper.status.json'))
        self.assertEqual(json.loads(status.read_text(encoding='utf-8'))['reason'], expected_reason)
        self.assertIsNotNone(child_holder[0].poll())

    @unittest.skipUnless(sys.platform == 'win32', 'Windows supervisor uses msvcrt locking')
    def test_memory_watchdog_stops_child(self):
        self.check_watchdog(1024**3, 20, 'RAM limit exceeded')

    @unittest.skipUnless(sys.platform == 'win32', 'Windows supervisor uses msvcrt locking')
    def test_time_watchdog_stops_child(self):
        self.check_watchdog(1024**2, 1, 'Timeout')


if __name__ == '__main__':
    print('Offline synthetic fixtures:', SESSION, flush=True)
    unittest.main(verbosity=2)
