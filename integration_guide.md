# Integration Guide

## Шаги интеграции
1. Получите API token у нашей команды.
2. Вызовите `PUT /api/v1/integrations/calls/upload-init`.
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
- Номера телефонов должны быть валидными (E.164 / проектный формат).
- Длительность звонка вычисляется сервером на этапе `finalize`.

## Статусы finalize
- `created` — звонок принят и создан диалог.
- `duplicate` — звонок уже был обработан.
- `filtered` — звонок отфильтрован по доменным правилам.
- `fault` — техническая ошибка обработки.

## Особенность upload-init
- Если для `(source_system, external_call_id)` сессия уже финализирована, `upload-init`
  вернёт `already_finalized=true` и бизнес-статус без нового `upload_url`.
