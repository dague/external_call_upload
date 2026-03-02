# Operations Runbook

## Логи
Ключевые события:
- `upload_init_issued`
- `dialog_created`
- `status=filtered/duplicate/fault` в ответах finalize

Ключи корреляции:
- `request_id`
- `upload_id`
- `external_call_id`
- `dialog_id`

## Метрики (рекомендация)
- `integration_upload_init_total{source_system}`
- `integration_finalize_total{source_system,status}`
- `integration_finalize_latency_seconds`

## Типовые проблемы
1. `UNAUTHORIZED`:
- токен неверный или отключён.

2. `UPLOAD_EXPIRED`:
- signed URL истёк; повторить `upload-init`.

3. `UPLOAD_NOT_READY`:
- finalize вызван до бинарной загрузки.

4. `filtered`:
- оператор не состоит в команде,
- клиент в blacklist / в сотрудниках / в партнёрах.

5. `DURATION_DETECT_FAILED`:
- не удалось определить длительность после нормализации файла (проверить файл и логи finalize).
