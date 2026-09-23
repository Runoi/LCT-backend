# Архитектура backend

## Функциональная архитектура

Домены выстроены в цепочку, каждый следующий наполняется из предыдущего, а не из сырых данных напрямую:

```
Facility/District
  └─ SensorChannel/SensorReading (потоковый ETL операционного окна)
       └─ Event (материализация alarm/anomaly показаний)
            └─ Risk (группировка по датчику -> ML Prediction Port -> прогноз)
                 └─ WorkOrder (черновик на основе рекомендации риска)
```

Наполнение каждого следующего уровня — **лениво, на чтение** (не фоновый воркер): `sync_events`/`sync_risks`/статус `WorkOrder` пересчитываются в начале соответствующего `GET`-запроса, идемпотентно через high-water-mark (см. `docs/DATA_PROCESSING.md`). Единственный настоящий фоновый процесс — replay-движок СМВУ, потому что именно он должен выглядеть как непрерывный поток телеметрии.

Параллельно, независимо от этой цепочки:

- **Auth/RBAC** — capability + scope модель (`docs/adr/0002`), пронизывает все домены сверху (каждый список/карточка фильтруется по scope вызывающего).
- **Эмуляция внешних источников** — СМВУ (replay поверх реальных показаний + fixture-сценарии), ОДС/реестр оборудования/система заявок (полностью синтетические, но выведены из реальных распределений). Отдельный слой `GET /system/source-health`, не завязан на бизнес-цепочку выше.
- **ML Prediction Port** (`docs/adr/0006`) — HTTP-граница между backend и ML-частью. Backend вызывает `POST {ML_PREDICTOR_URL}/predict`; при отсутствии `ML_PREDICTOR_URL` использует встроенный `StubPredictor`. Контракт (вход/выход) — единственное, что должна знать ML-команда, реализация backend'а им не видна и не важна.

## Компонентная архитектура

```
src/
  api/            # тонкий HTTP-слой: FastAPI-роутеры, парсинг query/body, коды ошибок
  services/       # вся бизнес-логика: seed/ETL, sync-паттерны, RBAC-резолюция, sensor/risk/event/work-order query-слои
  models/         # SQLAlchemy ORM (по одному модулю на домен)
  schemas/        # Pydantic response/request модели (форма API-контракта)
  deps/           # FastAPI-зависимости (auth: get_current_user, require_permission, require_any_permission)
  db.py           # engine/session factory
  config.py       # Settings (pydantic-settings, читает переменные окружения)
  errors.py       # единый формат ошибок {error: {code, message, trace_id, details, retryable}}
  main.py         # сборка приложения: регистрация роутеров, lifespan (seed + синки + replay-таск)

alembic/          # миграции схемы, по одной на домен
tests/            # pytest, зеркалит структуру src/ по одному файлу на сценарий
data/             # реальные CSV-датасеты (справочник каналов, справочник объектов, журнал событий — операционное окно)
docs/adr/         # architecture decision records — почему принято именно так, не только что сделано
```

**Слой `services/` — источник истины**, `api/` его не дублирует: каждый роутер вызывает 1-2 функции из `services/` и собирает ответ. Это осознанно, чтобы бизнес-логику можно было тестировать без HTTP-слоя (см. `tests/test_*_leveling.py`, `tests/test_*_lifecycle.py` — pure-function тесты без БД).

**Единый источник правды для перечислений** — `src/services/reference_data.py` (`GET /api/v1/config`): типы датчиков, уровни риска, причины отклонения, типы работ, статусы, границы свежести данных. Ни один другой модуль не переопределяет эти списки — только переиспользует по id.

## Схема БД (по доменам)

| Домен | Таблицы |
|---|---|
| Auth/RBAC | `users`, `user_permissions`, `districts`, `district_facilities`, `user_scope*`, `sessions` |
| Facility/иерархия объектов | `facilities`, `hierarchy_nodes` |
| ETL датчиков | `sensor_channels`, `sensor_readings`, `etl_ingested_sources` |
| Эмуляция внешних источников | `replay_state`, `ods_journal_entries`, `equipment_registry_items`, `external_work_order_records`, `synthetic_provider_runs`, `source_health_overrides` |
| События (Event) | `events`, `event_sync_state` |
| Риски (Risk) | `risks`, `risk_decisions`, `risk_sync_state` |
| Заявки (WorkOrder) | `work_orders` |

`external_work_order_records` (синтетический исторический бэклог для правдоподобности source-health) и `work_orders` (реальный локальный жизненный цикл заявок) — умышленно разные таблицы, не путать.
