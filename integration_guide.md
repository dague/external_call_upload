# Integration Guide

## Шаги интеграции
1. Получите API token у нашей команды.
2. Вызовите `PUT /api/v1/integrations/calls/upload-init`.
   - Если ответ содержит `status: "filtered"` — звонок отклонён, шаги 3–4 не нужны.
   - Если ответ содержит `upload_url` — переходите к шагу 3.
3. Выполните `PUT` бинарного файла по `upload_url`.
4. Вызовите `PUT /api/v1/integrations/calls/finalize`.

## Авторизация
Все запросы (кроме binary upload по signed URL) требуют заголовок:
`Authorization: Bearer <token>`

Выдача токена (для админа):
`python3 assistant/manage.py create_integration_token --team-id <ID> --source-system <source>`

## Ретраи
- `upload-init`: можно ретраить при сетевых ошибках.
- upload signed URL: при `410 UPLOAD_EXPIRED` нужно заново выполнить `upload-init`.
- upload signed URL: `409 DUPLICATE_CALL` означает, что загрузка уже финализирована.
- `finalize`: идемпотентен для одного `external_call_id`.
- `finalize`: `409 UPLOAD_NOT_READY` означает, что бинарная загрузка ещё не завершена.

## Ограничения
- Максимальный размер файла: 100 MB.
- `call_type`: `in` или `out`.
- `client_phone` должен быть валидным в проектном телефонном формате.
- `operator_phone` может быть как телефоном, так и внутренним добавочным номером (например, `1400`).
- Длительность звонка вычисляется сервером на этапе `finalize`.

## Статусы finalize
- `created` — звонок принят и создан диалог.
- `duplicate` — звонок уже был обработан.
- `filtered` — звонок отфильтрован по доменным правилам.
- `fault` — техническая ошибка обработки.

## Особенности upload-init
- Если для `(source_system, external_call_id)` сессия уже финализирована, `upload-init`
  вернёт `already_finalized=true` и бизнес-статус без нового `upload_url`.
- Если участники звонка не проходят доменные проверки (оператор не в команде, клиент в
  чёрном списке и т.д.), `upload-init` вернёт `status: "filtered"` с `error_code` и
  `message`. Загрузка файла и finalize в этом случае не требуются.
