# AudioMask-ASR-Test

Автономный исследовательский комплект для Windows PowerShell 5.1/7 и обычного CPython x64. Сайт AudioMask, Codex CLI, GPU и платные API не нужны. Исходный проект не используется.

На основном компьютере подготовлены скрипты. Работа моделей на виртуальной машине **пока не подтверждена**. Установка пакетов и загрузка весов — отдельные действия, которые выполняет человек после разрешения. Проверка данных не требует сторонних Python-пакетов.

## 1. Перенос и первые проверки

Скопируйте **всю папку AudioMask-ASR-Test** на виртуальную машину, например на рабочий стол. Не копируйте виртуальные окружения с другого компьютера. Уже имеющийся датасет оставьте отдельно:

```text
Рабочий стол/
  AudioMask-ASR-Test/
    run_benchmark.ps1
    ...
  data/
    eng/audio/1.wav ... 10.wav
    eng/text/1.txt ... 10.txt
    rus/audio/1.wav ... 10.wav
    rus/text/1.txt ... 10.txt
```

Откройте обычный PowerShell без прав администратора:

```powershell
$Desktop = [Environment]::GetFolderPath('Desktop')
Set-Location (Join-Path $Desktop 'AudioMask-ASR-Test')
python --version
Get-Command python
```

Все команды ниже используют политику выполнения только нового процесса PowerShell. Они не вызывают `Set-ExecutionPolicy` и не меняют системную политику. Если корпоративная политика запрещает запуск, обратитесь к администратору; не меняйте её самостоятельно.

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\run_benchmark.ps1 -Action check-env
powershell -NoProfile -ExecutionPolicy Bypass -File .\run_benchmark.ps1 -Action check-data
```

Запускатель сначала использует `py -3.13`, если Python Launcher доступен, иначе `python`. Можно явно выбрать интерпретатор:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\run_benchmark.ps1 -Action check-env -PythonExe 'C:\путь\к\python.exe'
```

Путь к `data` по умолчанию определяется через системную папку рабочего стола текущего пользователя, включая перенаправленный рабочий стол. Явный путь:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\run_benchmark.ps1 -Action check-data -DataPath 'D:\dataset\data'
```

Ожидаемый итог: `Valid pairs: 20/20`, код завершения 0. Проверяются номера 1–10 в каждом языке, пары WAV/TXT, непустые эталоны UTF-8 (BOM допускается), WAV-заголовок, PCM, полнота отсчётов, длительность, частота, каналы, разрядность. Метаданные и SHA-256 сохраняются в `results/validation/dataset.csv`, ошибки — в `dataset-errors.txt`. Проверка проходит весь массив отсчётов порциями, не загружая всю запись в RAM.

Поддерживаются несжатые целочисленные PCM WAV 8/16/24/32 бит. Сжатые WAV и IEEE float явно отклоняются. WAVE_FORMAT_EXTENSIBLE PCM зависит от поддержки стандартного `wave` в выбранном Python (есть с 3.12). Частоты и число каналов фиксируются без изменения оригиналов; преобразование выполняется только при эксперименте.

## 2. Python 3.13 и запасной Python 3.12

Для виртуальной машины с Python 3.13.16 используйте `-PythonVersion 3.13` (это значение по умолчанию). Проверка окружения требует стандартный CPython x64 с GIL, а не free-threaded сборку. Версия существующего окружения проверяется при каждом модельном действии.

Одна только запись `Python >=3.10` не доказывает совместимость. См. [COMPATIBILITY.md](COMPATIBILITY.md): проверяются wheel-теги Windows, версии зависимостей и ограничения их графа. Даже успешный аудит метаданных не подтверждает загрузку нативных DLL и инференс на VM.

Для GigaAM есть дополнительная неопределённость: официальная матрица закреплённой Hydra 1.3 заканчивается на Python 3.11. Поэтому её универсальный wheel не доказывает поддержку ни 3.13, ни запасного 3.12; эти окружения требуют проверки `check-deps` и реального запуска на VM. Не выдавайте результат метаданных за подтверждённую совместимость.

Если разрешение зависимостей, импорт или модель не работают на 3.13, установите **вручную**, после согласования, официальный CPython **3.12 x64** рядом с существующим Python. Не удаляйте 3.13 и не меняйте PATH/реестр/системные настройки. Выберите 3.12 через Launcher либо `-PythonExe`:

```powershell
py -3.12 --version
powershell -NoProfile -ExecutionPolicy Bypass -File .\run_benchmark.ps1 -Action create-env -Model whisper -PythonVersion 3.12
# Без Launcher:
powershell -NoProfile -ExecutionPolicy Bypass -File .\run_benchmark.ps1 -Action create-env -Model whisper -PythonVersion 3.12 -PythonExe 'C:\путь\к\Python312\python.exe'
```

Для следующих команд сохраняйте `-PythonVersion 3.12`. Старые окружения 3.13 не удаляются и не переиспользуются. Для сравнения используйте одну выбранную версию Python для всех моделей. Если исправить проблему не удалось, сохраните ошибки и отмечайте модель как недоступную; скрипты не подменяют её заглушкой.

## 3. Отдельные виртуальные окружения

Создание окружения использует стандартный `venv` и встроенный `ensurepip`; сторонние пакеты из сети на этом шаге не устанавливаются. Активация `Activate.ps1` не нужна.

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\run_benchmark.ps1 -Action create-env -Model whisper
powershell -NoProfile -ExecutionPolicy Bypass -File .\run_benchmark.ps1 -Action create-env -Model gigaam-v3
powershell -NoProfile -ExecutionPolicy Bypass -File .\run_benchmark.ps1 -Action create-env -Model gigaam-multi
```

Окружения: `.venvs/whisper-3.13`, `.venvs/gigaam-v3-3.13`, `.venvs/gigaam-multi-3.13`. Разделение нужно из-за разных рекомендуемых стеков Transformers/PyTorch у двух GigaAM.

Необязательная проверка разрешения пакетов **без установки**, после разрешения сетевых загрузок пакетов/метаданных:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\run_benchmark.ps1 -Action resolve -Model whisper -AllowNetwork
```

Повторите с `gigaam-v3` и `gigaam-multi`. `pip --dry-run` может скачивать дистрибутивы для получения метаданных, но не веса моделей. Он проверяет граф с PyPI; CPU-сборки PyTorch окончательно проверяются на следующем шаге. Сохраняется `results/environment/<модель>-<версия>/resolution.json`.

## 4. Установка — только после отдельного разрешения

Следующие команды **реально устанавливают пакеты** в соответствующее окружение. Не выполняйте их до разрешения:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\run_benchmark.ps1 -Action install -Model whisper -AllowInstall
powershell -NoProfile -ExecutionPolicy Bypass -File .\run_benchmark.ps1 -Action install -Model gigaam-v3 -AllowInstall
powershell -NoProfile -ExecutionPolicy Bypass -File .\run_benchmark.ps1 -Action install -Model gigaam-multi -AllowInstall
```

Без `-AllowInstall` установка запрещена. Используются PyPI и официальный CPU-индекс `download.pytorch.org/whl/cpu`; GitHub не используется. Установка не скачивает веса моделей. Устанавливаются только необходимые пакеты из `requirements-*.txt`, а также `setuptools` и `wheel` для подготовки чистого Python-пакета ANTLR. Для нативных зависимостей разрешены только готовые wheels; единственное исключение — `antlr4-python3-runtime==4.9.3`, опубликованный как исходный архив чистого Python. Скрипт не устанавливает компиляторы.

После установки автоматически выполняются `pip check`, импорты, проверка CPU-сборки torch либо доступности INT8 CTranslate2. Версии и отчёт установки сохраняются в `results/environment/`. Прямые зависимости закреплены; транзитивные разрешаются при установке и фиксируются в `installed.txt`. Это не полный заранее проверенный lock-файл.

Повторная диагностика без установки и весов:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\run_benchmark.ps1 -Action check-deps -Model whisper
powershell -NoProfile -ExecutionPolicy Bypass -File .\run_benchmark.ps1 -Action check-deps -Model gigaam-v3
powershell -NoProfile -ExecutionPolicy Bypass -File .\run_benchmark.ps1 -Action check-deps -Model gigaam-multi
```

При ошибке DLL сохраните полный вывод. Отсутствие Microsoft Visual C++ Runtime/поддержки инструкций CPU не исправляется сменой `Requires-Python`; системные компоненты скрипт не устанавливает.

## 5. Веса — отдельное разрешённое действие

| Имя в запускателе | Модель | Языки эксперимента | Исполнение |
|---|---|---|---|
| whisper | Systran/faster-whisper-small, multilingual | русский, английский | CPU INT8, beam=5 |
| gigaam-v3 | ai-sage/GigaAM-v3, revision ctc | русский | CPU FP32, greedy CTC |
| gigaam-multi | ai-sage/GigaAM-Multilingual, revision ctc, 220M | русский, английский | CPU FP32, greedy CTC |

`ssl` не является готовым распознавателем; `large_ctc` на 600M здесь не выбран из-за ограничений VM. Русский GigaAM-v3 не оценивается на английском: в отчёте будет `unsupported`.

После отдельного разрешения на загрузку весов:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\run_benchmark.ps1 -Action download -Model whisper -AllowDownload
powershell -NoProfile -ExecutionPolicy Bypass -File .\run_benchmark.ps1 -Action download -Model gigaam-v3 -AllowDownload
powershell -NoProfile -ExecutionPolicy Bypass -File .\run_benchmark.ps1 -Action download -Model gigaam-multi -AllowDownload
```

Загрузка идёт с Hugging Face и его инфраструктуры доставки; датасет не читается и не отправляется. Веса и открытые модули GigaAM сохраняются в `models/<модель>/`, commit и SHA-256 файлов — в `download.json`. При наличии аудита используется закреплённый в нём commit; иначе commit определяется в момент первой загрузки. Повторная загрузка использует сохранённый commit. Понадобится несколько гигабайт свободного диска под веса, окружения и кэш; проверьте запас до установки.

GigaAM исполняет открытый Python-код из локального снимка официальной модели. Адаптер напрямую импортирует локальный `modeling_gigaam.py` и вызывает его `GigaAMModel.from_pretrained`, вместо динамического сканера `AutoModel`, который может ошибочно потребовать необязательные longform-зависимости. Это тот же класс, который указан в официальном `auto_map`; код модели не переписывается. Такое исполнение требует доверия к коду снимка, аналогично `trust_remote_code=True` в официальном примере. Это не закрытый алгоритм маскирования. Просмотрите загруженный код перед экспериментом. Перед запуском сверяются SHA-256 файлов снимка. При инференсе действуют `local_files_only`, `HF_HUB_OFFLINE` и `TRANSFORMERS_OFFLINE`; скрипты не обращаются к удалённому распознавателю.

Проверить сохранённые хеши без сети:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\run_benchmark.ps1 -Action verify-weights -Model gigaam-multi
```

## 6. Эксперимент

Закройте другие ресурсоёмкие приложения. Сначала запустите одну выбранную модель:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\run_benchmark.ps1 -Action run -Model whisper
```

Либо замените имя на `gigaam-v3` / `gigaam-multi`. Полное сравнение:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\run_benchmark.ps1 -Action compare
```

Все три окружения и локальные снимки должны быть подготовлены заранее. Модели запускаются **последовательно, каждая в новом процессе**. Блокировка запрещает второй параллельный эксперимент из этой же папки. Пулы вычислений ограничены четырьмя потоками; процессы ограничиваются четырьмя доступными CPU. GPU отключён, а PyTorch устанавливается в CPU-варианте. Служебные потоки библиотек и монитор RAM могут существовать дополнительно к вычислительным пулам.

Лимиты по умолчанию: 7200 секунд **на модель**, 7168 MiB суммарного RSS её дерева процессов, остановка при доступной RAM системы менее 512 MiB. Это опрашиваемый watchdog с интервалом 0.2 секунды, а не жёсткая квота ОС: короткий скачок возможен. При превышении лимита процесс останавливается, сохраняется ошибка, сравнение переходит к следующей модели. Ctrl+C останавливает текущий эксперимент. Уже полученные результаты остаются доступными.

Пример настройки и явного пути:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\run_benchmark.ps1 -Action compare -DataPath 'D:\dataset\data' -TimeoutSeconds 14400 -RamLimitMiB 7168
```

При необходимости каждый WAV преобразуется **в копию mono 16 кГц PCM16** через PyAV с встроенными библиотеками FFmpeg. Системный `ffmpeg.exe` не нужен. Подготовленные копии разбиваются на одинаковые последовательные фрагменты до 20 секунд без перекрытия и VAD. Это ниже 25-секундного ограничения обычного `transcribe()` GigaAM. Все фрагменты распознаются, тексты соединяются в порядке записи. Исходные WAV/TXT не изменяются; их хеши сверяются после прогона.

Адаптер GigaAM заменяет только метод ввода `prepare_wav` чтением подготовленного PCM16 средствами Python/Torch. Признаки, веса и декодер модели не изменяются. Это устраняет вызов системного FFmpeg с неограниченными потоками и необходимость longform/VAD/pyannote/TorchCodec. Многоязычная модель может возвращать объект с полем `.text`; адаптер поддерживает его и строковый результат.

## 7. Метрики и файлы результатов

Каждый запуск создаёт уникальную папку `results/<дата-время>/`:

```text
report.md                    итоговый отчёт
summary.csv                  итог по моделям и языкам
<модель>.status.json          статус, лимиты, RAM, общее время
<модель>.log                  диагностика процесса
<модель>/metadata.json        время загрузки, подготовки, версии, commit
<модель>/results.csv          время и WER каждой записи, ошибки
<модель>/dataset.csv          параметры оригиналов и SHA-256
<модель>/transcripts/rus/*.txt
<модель>/transcripts/eng/*.txt
<модель>/audio/               нормализованные копии
<модель>/chunks/              фрагменты копий
```

Время загрузки включает импорт модельных библиотек и создание модели, исключает конвертацию и загрузку весов по сети. Время ASR измеряет полное распознавание всех фрагментов записи, включая исчерпание генератора faster-whisper, без расчёта WER. Отдельно фиксируется время подготовки. Прогрев не выполняется; первая запись может быть медленнее. Общая длительность процесса содержит также валидацию/хеширование и запись файлов.

Пиковая RAM: приблизительный максимум суммарного RSS дочернего процесса модели и его потомков, включая подготовку и загрузку. Дополнительно сохраняется системный Windows peak working set самого процесса модели, когда он доступен. Монитор и остальные приложения не входят в RSS модели. Из-за опроса и общих страниц RSS не равен точной уникальной занятой физической памяти.

WER считается стандартным расстоянием Левенштейна по словам: сумма замен/удалений/вставок, делённая на число эталонных слов. Нормализация одинакова для всех: Unicode NFKC, нижний регистр, `ё→е`, токены из Unicode-букв и цифр, пунктуация и подчёркивания разделяют слова. Числа не переводятся в слова; это может влиять на сравнение. Пустая гипотеза даёт удаления, пустой эталон отклоняется. В итоговом WER суммируются ошибки и эталонные слова **всего языка**, а не усредняются проценты файлов. Значение 0.15 означает 15%; WER может превышать 100%. RTF = время ASR / длительность аудио.

Если обработаны не все 10 записей языка или процесс завершился ошибкой, итоговый WER не публикуется. Диагностический `partial_wer` сохраняется отдельно. При разных хешах датасета отчёт помечает сравнение как недействительное. Исследование оценивает выбранные модели вместе с конкретными декодерами/точностью вычислений; 20 записей и разрезание речи по границам не дают основания заявлять об общем превосходстве модели или сравнивать цифры напрямую с опубликованными бенчмарками.

Повторное формирование отчёта по **одной конкретной папке запуска** не требует модельных зависимостей:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\run_benchmark.ps1 -Action report -OutputPath '.\results\20261108-123456-000000'
```

Результаты, копии и транскрипции автоматически не удаляются. После завершения исследования их очистку выполняет человек. Не публикуйте записи, тексты, окружения и кэш. Это автономный набор, он не меняет срок хранения аудио в сайте AudioMask.

## 8. Локальные проверки без моделей

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\run_benchmark.ps1 -Action self-test
```

Это проверки небольших синтетических PCM WAV, ошибок UTF-8/структуры, WER, копирования, разрезания и формирования отчёта. Никаких реальных моделей, сетевых запросов и установки. Синтетические артефакты сохраняются только в `.checks/<уникальный-id>/` внутри комплекта. Конвертация разных частот/каналов через PyAV и реальная ASR-интеграция проверяются отдельно на VM после установки.

Необязательное повторение метаданных аудита, без установки и весов:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\run_benchmark.ps1 -Action audit -AllowNetwork
```

Скрипт читает только JSON PyPI/Hugging Face, использует `packaging` внутри уже имеющегося `pip` и записывает `compatibility/evidence.json`. При повторении файл перезаписывается. Это упрощённый обход графа без backtracking; он не заменяет `resolve`, проверку импортов и настоящий запуск на VM.

Коды: 0 — успех; 1 — ошибка запускателя/непредвиденная ошибка; 2 — некорректные данные, несовместимость либо неполный эксперимент (PowerShell оборачивает неуспешный Python-вызов в 1). Анализируйте текст ошибки и сохранённые статусы.
