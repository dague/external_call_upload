# external_call_uploader.py

Документация по CLI-утилите:
`assistant/helper/utils/external_call_uploader.py`

## Назначение
Утилита выполняет двухшаговую загрузку записи звонка во внешний API:
1. `PUT /api/v1/integrations/calls/upload-init`
2. `PUT` бинарного файла по `upload_url`
3. `PUT /api/v1/integrations/calls/finalize`

## Особенности
- `base_url` зафиксирован в коде: `https://demo.neuro-tech.ai`
- `external_call_id` генерируется автоматически
- `content_type` определяется по расширению файла
- `sha256` файла считается локально и отправляется в `upload-init`
- `duration_sec` не передаётся: длительность вычисляется сервером на `finalize`

## Требования
- Python 3
- пакет `requests` (рекомендуется запуск через `poetry run`)
- валидный integration token (`Bearer`)

## Аргументы
- `file_path` (позиционный): путь к аудиофайлу
- `--token` (обязательный): integration API token
- `--operator-phone` (обязательный): телефон оператора или добавочный номер (например, `1400`)
- `--client-phone` (обязательный): телефон клиента
- `--start-time` (обязательный): ISO8601 datetime (`2026-03-01T10:20:30+03:00` или `...Z`)
- `--call-type` (обязательный): `in` или `out`

Проверка интерфейса:
```bash
poetry run python assistant/helper/utils/external_call_uploader.py --help
```

## Пример запуска
```bash
poetry run python assistant/helper/utils/external_call_uploader.py /path/to/call.mp3 \
  --token "<TOKEN>" \
  --operator-phone "+79990001122" \
  --client-phone "+79990003344" \
  --start-time "2026-03-01T12:30:00+03:00" \
  --call-type in
```

## Вывод
Утилита пишет:
- человекочитаемые этапы в `stdout`
- structured JSON-события в лог (`logging`), префикс: `json=...`

Ключевые события:
- `upload_flow_start`
- `upload_init_response`
- `upload_binary_response`
- `finalize_response`
- `upload_flow_result`
- `upload_flow_failure` (при ошибке)

## Ретраи
Количество попыток: 3.

Ретраятся:
- сетевые ошибки (`requests.RequestException`)
- HTTP `429`
- HTTP `5xx`
- HTTP `409` только для шага `finalize`, если:
  - `error_code == "UPLOAD_NOT_READY"`, или
  - `retryable == true`

Backoff: `1s`, `2s` между попытками.

## Поведение по результату
- если `upload-init` вернул `already_finalized=true`, утилита завершится успешно без загрузки файла
- если любой шаг вернул non-200 (после ретраев), утилита завершится с кодом `1`
- при успехе всех шагов утилита завершится с кодом `0`

## Типовые проблемы
- `ModuleNotFoundError: requests`: запускать через `poetry run` или установить зависимости
- `Invalid --start-time ISO8601`: исправить формат времени
- `401 UNAUTHORIZED`: проверить `--token`
- `409 UPLOAD_NOT_READY` на finalize: обычно временная гонка, покрывается ретраями
