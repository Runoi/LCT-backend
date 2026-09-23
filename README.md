# Backend — сервис прогнозирования инцидентов Москоллектора

Бэкенд-часть хакатонного MVP: REST API по контракту фронтенда, схема БД, RBAC, потоковый ETL, эмуляция внешних источников (СМВУ/ОДС/реестр оборудования/система заявок), ML Prediction Port + Stub Predictor, локальный жизненный цикл заявок на ремонт. Подробнее о границах и терминологии — `CONTEXT.md`; о принятых архитектурных решениях — `docs/adr/`; о доменной архитектуре и способах обработки данных — `docs/ARCHITECTURE.md` и `docs/DATA_PROCESSING.md`; о честных MVP-ограничениях — `docs/LIMITATIONS.md`.

## Запуск (с нуля)

```
docker compose up --build
```

Поднимутся два контейнера: `db` (PostgreSQL 16) и `app` (FastAPI). При старте `app` автоматически применяет миграции Alembic (`alembic upgrade head`), засеивает справочники и реальный датасет (объекты, каналы датчиков, операционное окно журнала событий), поднимает эмуляцию внешних источников (ОДС/реестр/заявки/replay СМВУ) и материализует события/прогнозы, затем запускает сервер на `http://localhost:8000`.

Проверка, что всё поднялось:

```
curl http://localhost:8000/health
```

Ожидаемый ответ: `{"status":"ok"}`.

Остановка:

```
docker compose down
```

## API-контракт

Swagger UI (интерактивная документация, тот же контракт, что видит фронтенд-команда): **http://localhost:8000/docs**
Машиночитаемая спецификация: `http://localhost:8000/openapi.json` (актуальный снимок для пакета сдачи — `docs/openapi.json`).

Основные группы эндпоинтов (`/api/v1/*`):

| Группа | Эндпоинты |
|---|---|
| Auth | `POST /auth/login`, `GET /me` |
| Справочники | `GET /config` |
| Объекты | `GET /facilities`, `/facilities/{id}`, `/facilities/{id}/hierarchy`, `/facilities/{id}/layout` |
| Датчики | `GET /sensors`, `/sensors/{id}`, `/sensors/{id}/series` |
| События | `GET /events` |
| Риски/прогнозы | `GET /risks`, `/risks/{id}`, `POST /risks/{id}/acknowledge\|reject\|defer` |
| Заявки | `POST /work-orders`, `GET /work-orders` |
| Статус источников | `GET /system/source-health`, `GET /system/scenarios`, `POST /system/scenarios/{id}/activate`, `POST`/`DELETE /system/source-health/{source}/degrade` |

## Демо-пользователи

Сеятся автоматически при старте (см. `src/services/demo_seed.py`):

| Логин | Пароль | Роль | Scope |
|---|---|---|---|
| `manager` | `manager123` | Руководитель | все объекты, все permissions |
| `dispatcher` | `dispatcher123` | Диспетчер объекта | только `fac_5122`/`fac_5339`, ограниченный набор permissions |

## Локальная разработка без Docker

```
python -m venv .venv
source .venv/Scripts/activate   # Windows Git Bash
# .venv\Scripts\activate.bat    # Windows cmd
pip install -r requirements.txt
cp .env.example .env            # при необходимости поправить DATABASE_URL
alembic upgrade head
uvicorn src.main:app --reload
```

## Тесты

```
pytest
```

Тестам нужна доступная база данных, указанная в `DATABASE_URL` (используйте локальный Postgres или значение по умолчанию из `.env.example`).

## Конфигурация

Все настройки читаются из переменных окружения (см. `.env.example`):

| Переменная | Назначение | По умолчанию |
|---|---|---|
| `DATABASE_URL` | строка подключения к PostgreSQL (asyncpg) | `postgresql+asyncpg://mkl:mkl@localhost:5432/mkl` |
| `APP_ENV` | имя окружения | `local` |
| `LOG_LEVEL` | уровень логирования | `INFO` |
| `ML_PREDICTOR_URL` | URL внешнего ML-сервиса, реализующего ML Prediction Port (`docs/adr/0006-ml-port-bespoke-not-indastrics-shaped.md`). Если не задан — используется встроенный `StubPredictor` | не задан (используется stub) |
| `REPLAY_SPEED_MULTIPLIER` | сколько виртуальных секунд эмуляции СМВУ проходит за одну реальную секунду | `360.0` |
| `REPLAY_TICK_SECONDS` | интервал между тиками фонового replay-движка | `5.0` |

## Переключение на реальную ML-модель

Backend взаимодействует с ML-частью через простой HTTP-контракт (не Python-интерфейс внутри бэкенда — команды пишут код параллельно и асинхронно, см. `docs/adr/0001-backend-only-mvp-scope-with-integration-ports.md` и `0006-ml-port-bespoke-not-indastrics-shaped.md`). Чтобы подключить обученную модель вместо `StubPredictor`, ML-команде достаточно поднять сервис, отвечающий `POST {ML_PREDICTOR_URL}/predict` по контракту в `src/services/ml_port.py` (`PredictionInput`/`PredictionResult`), и указать его URL в `ML_PREDICTOR_URL` — код бэкенда менять не нужно.
