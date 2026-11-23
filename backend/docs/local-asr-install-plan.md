# План локальной установки ASR — без выполнения команд

Для подтверждённой конфигурации Windows и проверенных версий GigaAM см.
[документацию backend](../README.md#окружения-asr-на-windows). Версии и команды
ниже относятся к предварительному плану установки.

Статус: подготовка. Пакеты, веса и исполняемые файлы не устанавливались и не
загружались в рамках этого плана. Все команды ниже требуют отдельного подтверждения.
Системная инвентаризация, поиск программ и чтение внешних каталогов не выполняются.
Внешние пути и сведения о компьютере предоставляет пользователь.

## Что ожидает существующий backend

- `AUDIOMASK_WHISPER_PYTHON`: абсолютный путь к Python отдельного окружения.
- `AUDIOMASK_WHISPER_WEIGHTS`: каталог CTranslate2 small multilingual,
  а не исходные веса OpenAI PyTorch. Worker использует CPU INT8, язык en.
- `AUDIOMASK_GIGAAM_PYTHON`: Python второго окружения.
- `AUDIOMASK_GIGAAM_WEIGHTS`: полный локальный Transformers snapshot
  GigaAM-Multilingual CTC 220M. Worker проверяет `multilingual_ctc`, encoder 16×768.
- Backend-окружение с FastAPI остаётся отдельным; его requirements не устанавливаются
  в модельные окружения. Ни GPU, ни CUDA-пакеты для этой задачи не нужны.

Совместимость workers исправлена без установки моделей:

1. Для faster-whisper **1.2.1** `preprocessor_config.json` необязателен. При отсутствии
   библиотека использует стандартные настройки FeatureExtractor, подходящие small.
   Файл не создаётся и не докачивается из другой модели. Если файл присутствует
   в локальном snapshot, сама библиотека прочитает его обычным способом.
2. GigaAM-worker извлекает строковое поле `.text` из `TranscriptionResult`;
   отсутствующее/нестроковое поле — ошибка, пустая строка сохраняется пустой.
3. GigaAM явно переводится в `device='cpu', dtype=torch.float32`, затем eval/inference_mode.
4. Введён `AUDIOMASK_FFMPEG_PATH`: абсолютный путь к конкретному исполняемому файлу.
   Он обязателен только для GigaAM. PATH и диски не сканируются, переменные PATH
   не меняются. Вызов `run(['ffmpeg', ...])` из закреплённого custom code временно
   привязывается к этому пути в памяти worker. Сам snapshot не изменяется;
   функция восстанавливается после вызова, включая исключение. Используются список
   аргументов, shell=False, whitelist протоколов file/pipe и скрытое окно Windows.
5. Обычный `transcribe` GigaAM ограничивает длину аудио; длинные записи следует
   проверять отдельно. Автоматическое подключение longform/VAD не входит в установку.

Поведение faster-whisper проверено по исходнику опубликованного wheel 1.2.1 из PyPI
в памяти, без установки или сохранения пакета. SHA256 релиза:
`79a66ad50688c0b794dd501dc340a736992a6342f7f95e5811be60b5224a26a7`.
`_get_feature_kwargs` начинает с пустого словаря и читает preprocessor только при
его наличии. Локальный tokenizer обязателен, поскольку без него библиотека содержит
ветвь `Tokenizer.from_pretrained`; worker отклоняет неполный snapshot до импорта модели.

## Минимальные локальные snapshot

| Модель | Обязательные файлы |
| --- | --- |
| Systran/faster-whisper-small | `model.bin`, `config.json`, `tokenizer.json`, `vocabulary.txt` |
| GigaAM-Multilingual CTC 220M, закреплённый snapshot | `config.json`, `modeling_gigaam.py`, `pytorch_model.bin` |

Для Whisper `preprocessor_config.json` необязателен; исходные PyTorch-веса OpenAI
вместо CTranslate2 не подходят. Для GigaAM проверяются локальные auto_map
`modeling_gigaam.GigaAMConfig`/`modeling_gigaam.GigaAMModel`: ссылки на custom code
другого Hub repository отклоняются. Выбранный character-wise CTC snapshot содержит
словарь в config и не требует отдельного `tokenizer.model`. Этот перечень относится
к выбранным snapshot, а не ко всем вариантам Whisper/GigaAM.

При отсутствии интерпретатора/весов/зависимостей API возвращает 503/asr_unavailable.
Для отсутствующего/незапускаемого FFmpeg — 503/ffmpeg_unavailable с безопасным
сообщением без внутренних путей. Неверный результат модели — 502/asr_failed.

## Предлагаемые версии

Целевая платформа для этого варианта: Windows x64, CPython 3.11.
Версии являются кандидатами для проверки, а не доказанной рабочей сборкой:
разрешение транзитивных зависимостей и настоящая загрузка ещё не выполнялись.

| Окружение | Закреплённые основные пакеты |
| --- | --- |
| Whisper | faster-whisper 1.2.1, ctranslate2 4.6.0, av 16.0.1, onnxruntime 1.23.2 |
| GigaAM | torch 2.10.0 CPU, torchaudio 2.10.0 CPU, transformers 5.10.1, hydra-core 1.3.2, omegaconf 2.3.0, soundfile 0.13.1, sentencepiece 0.2.1 |
| Оба | numpy 2.2.6, tokenizers 0.22.2, huggingface-hub 1.5.0 |

Transformers 5.10.0 исключён: релиз отозван на PyPI. Выбран кандидат 5.10.1;
он требует huggingface-hub >=1.5.0. Не смешивать torch и torchaudio разных версий.
Модель рекомендует torch/torchaudio 2.10.* и Transformers 5.*.
После разрешённой установки — `pip check`, тест импорта, затем полный `pip freeze`
в согласованный внешний каталог. До этого полного воспроизводимого lock-файла нет.
При конфликте остановиться и сообщить, не заменять версии молча.

## Расположение и объёмы

Корневой каталог `$AsrRoot` выбирает пользователь вне AudioMask. Предлагаемая структура:

```text
<разрешённый каталог>/
  envs/whisper/
  envs/gigaam/
  models/whisper-small/
  models/gigaam-multi-ctc/
  cache/huggingface/
  cache/pip/
  cache/tmp/
  reports/
```

Исследовательские аудио не копируются: тесты используют только явно указанные
пользователем пути. Модели, окружения, кэши и отчёты не помещаются в репозиторий.

Официальные каталоги: Whisper около 486 MB, GigaAM около 883 MB; вместе около
1.37 GB весов/сопутствующих файлов. Whisper загружается в формате CTranslate2,
INT8 задаётся при исполнении и не означает, что скачанный model.bin уже INT8.
Полный сетевой объём с библиотеками предварительно 2–3 GB, резерв на диске 10 GB.
Это оценка, не измерение: распаковка Torch, кэш pip/HF и временные файлы увеличивают
занятое место. Точный объём библиотек зависит от окончательного разрешения wheels.
Наличие RAM и свободного места оценивается только по сведениям пользователя.

## Команды для согласования — НЕ ВЫПОЛНЕНЫ

Подставить два явно предоставленных пути. Не выполнять шаблоны как готовые пути.

```powershell
$PythonExe = '<полный путь к разрешённому Python 3.11 x64>'
$AsrRoot = '<разрешённый каталог вне репозитория>'
$env:HF_HOME = Join-Path $AsrRoot 'cache/huggingface'
$env:HF_MODULES_CACHE = Join-Path $AsrRoot 'cache/huggingface/modules'
$env:PIP_CACHE_DIR = Join-Path $AsrRoot 'cache/pip'
$env:TEMP = Join-Path $AsrRoot 'cache/tmp'
$env:TMP = $env:TEMP
New-Item -ItemType Directory -Force -Path $AsrRoot, $env:HF_HOME, $env:HF_MODULES_CACHE, $env:PIP_CACHE_DIR, $env:TEMP
& $PythonExe -m venv (Join-Path $AsrRoot 'envs/whisper')
& $PythonExe -m venv (Join-Path $AsrRoot 'envs/gigaam')
$WhisperPython = Join-Path $AsrRoot 'envs/whisper/Scripts/python.exe'
$GigaamPython = Join-Path $AsrRoot 'envs/gigaam/Scripts/python.exe'

& $WhisperPython -m pip install --index-url https://pypi.org/simple faster-whisper==1.2.1 ctranslate2==4.6.0 av==16.0.1 onnxruntime==1.23.2 numpy==2.2.6 tokenizers==0.22.2 huggingface-hub==1.5.0
& $GigaamPython -m pip install --index-url https://download.pytorch.org/whl/cpu torch==2.10.0 torchaudio==2.10.0
& $GigaamPython -m pip install --index-url https://pypi.org/simple transformers==5.10.1 hydra-core==1.3.2 omegaconf==2.3.0 soundfile==0.13.1 sentencepiece==0.2.1 numpy==2.2.6 tokenizers==0.22.2 huggingface-hub==1.5.0
& $WhisperPython -m pip check
& $GigaamPython -m pip check
```

Это отдельные команды PowerShell: при ненулевом exit code прекращаем процедуру.
Создание venv не должно перезаписывать существующее окружение: перед выполнением
пользователь должен подтвердить, что выбранные новые целевые каталоги свободны.

Загрузки только из каталогов издателей моделей, без Git/GitHub:

```powershell
$Hf = Join-Path $AsrRoot 'envs/whisper/Scripts/hf.exe'
& $Hf download Systran/faster-whisper-small model.bin config.json tokenizer.json vocabulary.txt --revision main --local-dir (Join-Path $AsrRoot 'models/whisper-small')
& $Hf download ai-sage/GigaAM-Multilingual config.json modeling_gigaam.py pytorch_model.bin --revision 2f8a57144e6ec3adfd32fe0484d9ea9913305bc8 --local-dir (Join-Path $AsrRoot 'models/gigaam-multi-ctc')
```

Для ссылки `main` перед загрузкой зафиксировать SHA текущей ревизии по метаданным
Hugging Face и заменить `main` на SHA. Это чтение официальных метаданных, не Git-операция.
Офлайн-переменные не включать на стадии разрешённой загрузки. Если они уже заданы,
отдельно согласовать их изменение только для текущего процесса.

## Подключение после согласованной установки

```powershell
$env:AUDIOMASK_WHISPER_PYTHON = $WhisperPython
$env:AUDIOMASK_WHISPER_WEIGHTS = Join-Path $AsrRoot 'models/whisper-small'
$env:AUDIOMASK_GIGAAM_PYTHON = $GigaamPython
$env:AUDIOMASK_GIGAAM_WEIGHTS = Join-Path $AsrRoot 'models/gigaam-multi-ctc'
$env:AUDIOMASK_FFMPEG_PATH = '<полный путь к явно разрешённому ffmpeg.exe>'
$env:HF_HUB_OFFLINE = '1'
$env:TRANSFORMERS_OFFLINE = '1'
$env:HF_HUB_DISABLE_TELEMETRY = '1'
$env:AUDIOMASK_MAX_CONCURRENT_ASR = '1'
```

FFmpeg задаётся только предоставленным пользователем путём; без него тест GigaAM
не считать подготовленным. PATH менять не требуется. Проверка существования пути
не доказывает совместимость binary/DLL: это устанавливается отдельным разрешённым тестом.

Оба worker принудительно включают offline/disable-telemetry переменные до импорта
моделей и запрещают Python socket connect/DNS. Загрузчикам передаются только
абсолютные локальные каталоги и local_files_only=True. Неполный snapshot отвергается,
а не дополняется через Hub. FFmpeg разрешены только локальные file/pipe протоколы.
Это не сетевая песочница ОС для любого native/custom code: финальный запуск
с настоящими моделями нужно дополнительно проверить при отключённой сети.

Далее: загрузка каждой модели офлайн → один короткий ru WAV и один en WAV →
запросы существующего API → при наличии явно разрешённого набора сравнительный запуск.
Фиксировать время запуска/инференса, wall time запроса, пиковую память дерева
собственных workers, dtype, число CPU-потоков и обезличенные ошибки. Записи и
транскрипции не включать в технические логи без отдельной необходимости/разрешения.
Отсутствие внешних передач проверять с отключённой сетью и наблюдением только
за собственными тестовыми процессами; одно local_files_only этого не доказывает.

## Первичные источники

- https://huggingface.co/ai-sage/GigaAM-Multilingual
- https://huggingface.co/ai-sage/GigaAM-Multilingual/blob/main/modeling_gigaam.py
- https://huggingface.co/ai-sage/GigaAM-Multilingual/tree/main
- https://huggingface.co/Systran/faster-whisper-small/tree/main
- https://huggingface.co/openai/whisper-small/tree/main
- https://pypi.org/project/faster-whisper/1.2.1/
- https://pypi.org/project/ctranslate2/4.6.0/
- https://pypi.org/project/transformers/5.10.1/
- https://pytorch.org/get-started/previous-versions/
