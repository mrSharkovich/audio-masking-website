"""Dependency-free checks; model runs require psutil in the supervisor environment."""
import argparse
import datetime
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import sysconfig
import time
from dataset import validate, write_csv

ROOT = Path(__file__).resolve().parent
MODELS = ('whisper', 'gigaam-v3', 'gigaam-multi')


def environment(expected=None, require_venv=False):
    info = dict(python=sys.version, executable=sys.executable, bits=platform.architecture()[0],
        platform=platform.platform(), cpu_count=os.cpu_count(), venv=sys.prefix != sys.base_prefix,
        free_threaded=bool(sysconfig.get_config_var('Py_GIL_DISABLED')))
    print(json.dumps(info, indent=2))
    valid = (sys.version_info[:2] in ((3,12),(3,13)) and sys.maxsize > 2**32
        and not info['free_threaded'] and platform.python_implementation() == 'CPython')
    if expected:
        valid &= platform.python_version().startswith(expected+'.')
    if require_venv:
        valid &= info['venv']
    if not valid:
        print('Require CPython 3.12/3.13 x64, standard GIL build, requested version and venv.')
    return 0 if valid else 2


def supervise(args):
    import msvcrt
    import psutil
    rows, errors = validate(args.data)
    if errors:
        raise ValueError('\n'.join(errors))
    if Path(args.output).resolve().is_relative_to(Path(args.data).resolve()):
        raise ValueError('Output must not be inside the source dataset')
    lock = (ROOT/'.benchmark.lock').open('a+b')
    lock.seek(0)
    if not lock.read(1):
        lock.write(b'0'); lock.flush()
    lock.seek(0)
    try:
        msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
    except OSError:
        lock.close()
        raise RuntimeError('Another benchmark is running from this kit')
    run = Path(args.output)/datetime.datetime.now().strftime('%Y%m%d-%H%M%S-%f')
    run.mkdir(parents=True)
    failed = False
    try:
        for model in MODELS if args.model == 'all' else (args.model,):
            python = ROOT/'.venvs'/f'{model}-{args.version}'/'Scripts'/'python.exe'
            record = dict(model=model, status='error', peak_rss_mib=0, windows_peak_worker_mib=0,
                elapsed_s=0, reason='', sample_interval_s=0.2, ram_limit_mib=args.ram_mib, timeout_s=args.timeout)
            started = time.perf_counter()
            if not python.is_file():
                record['reason'] = f'Missing environment: {python}'
            elif not (ROOT/'models'/model/'config.json').exists():
                record['reason'] = 'Missing local model; run download explicitly first'
            else:
                log = run/f'{model}.log'
                with log.open('w', encoding='utf-8') as stream:
                    process = subprocess.Popen([str(python), '-B', str(ROOT/'worker.py'), '--model', model,
                        '--data', str(Path(args.data).resolve()), '--output', str(run/model),
                        '--weights', str(ROOT/'models'/model)], stdout=stream, stderr=subprocess.STDOUT)
                    rootproc = psutil.Process(process.pid)
                    try:
                        rootproc.cpu_affinity(rootproc.cpu_affinity()[:4])
                        while process.poll() is None:
                            try:
                                members = [rootproc]+rootproc.children(recursive=True)
                                rss = 0
                                for member in members:
                                    try:
                                        memory = member.memory_info()
                                        rss += memory.rss/2**20
                                        if member.pid == rootproc.pid:
                                            record['windows_peak_worker_mib'] = max(record['windows_peak_worker_mib'], getattr(memory,'peak_wset',0)/2**20)
                                    except psutil.NoSuchProcess:
                                        pass
                                record['peak_rss_mib'] = max(record['peak_rss_mib'], rss)
                                reason = ('RAM limit exceeded' if rss > args.ram_mib else
                                    'Low available system RAM' if psutil.virtual_memory().available < 512*2**20 else
                                    'Timeout' if time.perf_counter()-started > args.timeout else '')
                                if reason:
                                    record['reason'] = reason
                                    break
                            except psutil.NoSuchProcess:
                                pass
                            time.sleep(.2)
                    except KeyboardInterrupt:
                        record['reason'] = 'Interrupted by user'
                        raise
                    finally:
                        if process.poll() is None:
                            try:
                                children = rootproc.children(recursive=True)
                            except psutil.NoSuchProcess:
                                children = []
                            for child in reversed(children+[rootproc]):
                                try:
                                    child.kill()
                                except psutil.NoSuchProcess:
                                    pass
                        code = process.wait()
                        record['elapsed_s'] = time.perf_counter()-started
                        if code == 0 and not record['reason']:
                            record['status'] = 'ok'
                        elif not record['reason']:
                            record['reason'] = f'Worker exit {code}; see {log.name}'
                        (run/f'{model}.status.json').write_text(json.dumps(record, indent=2), encoding='utf-8')
            record['elapsed_s'] = time.perf_counter()-started
            failed |= record['status'] != 'ok'
            (run/f'{model}.status.json').write_text(json.dumps(record, indent=2), encoding='utf-8')
            print(model, record['status'], record['reason'], flush=True)
    finally:
        lock.seek(0)
        msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
        lock.close()
        from report import build_report
        if list(run.glob('*.status.json')):
            build_report(run)
        print('Results:', run)
    return 2 if failed else 0


def main():
    p = argparse.ArgumentParser()
    p.add_argument('action', choices=['check-env','check-data','run','report'])
    p.add_argument('--data')
    p.add_argument('--output', default=str(ROOT/'results'))
    p.add_argument('--model', choices=(*MODELS,'all'), default='whisper')
    p.add_argument('--version', choices=['3.12','3.13'])
    p.add_argument('--require-venv', action='store_true')
    p.add_argument('--timeout', type=int, default=7200)
    p.add_argument('--ram-mib', type=int, default=7168)
    args = p.parse_args()
    if args.action == 'check-env':
        return environment(args.version, args.require_venv)
    if args.action == 'report':
        from report import build_report
        build_report(Path(args.output))
        return 0
    if not args.data:
        p.error('--data is required')
    if args.action == 'check-data':
        rows, errors = validate(args.data)
        out = Path(args.output)
        out.mkdir(parents=True, exist_ok=True)
        write_csv(out/'dataset.csv', rows, fields=['language','id','wav','text','wav_sha256','text_sha256','channels','bits','sample_rate','duration_s'])
        (out/'dataset-errors.txt').write_text('\n'.join(errors), encoding='utf-8')
        print(f'Valid pairs: {len(rows)}/20')
        for row in rows:
            print(f"{row['language']}/{row['id']}: {row['duration_s']:.3f}s {row['sample_rate']}Hz {row['channels']}ch {row['bits']}bit")
        for error in errors:
            print(error)
        return 2 if errors else 0
    if not args.version or args.timeout < 1 or args.ram_mib < 256:
        p.error('Version and positive resource limits are required')
    return supervise(args)


if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception as e:
        print(f'{type(e).__name__}: {e}', file=sys.stderr)
        sys.exit(1)
