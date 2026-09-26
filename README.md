# Backend — сервис прогнозирования инцидентов Москоллектора

Бэкенд-часть хакатонного MVP: REST API по контракту фронтенда, схема БД, RBAC, потоковый ETL, эмуляция внешних источников (СМВУ/ОДС/реестр оборудования/система заявок), ML Prediction Port + Stub Predictor, локальный жизненный цикл заявок на ремонт, журнал аудита и TLS. Подробнее о границах и терминологии — `CONTEXT.md`; о принятых архитектурных решениях — `docs/adr/`; о доменной архитектуре и способах обработки данных — `docs/ARCHITECTURE.md` и `docs/DATA_PROCESSING.md`; о безопасности (сверка с ТЗ по пунктам) — `docs/SECURITY.md`; о честных MVP-ограничениях — `docs/LIMITATIONS.md`.

## Запуск (с нуля)

```
docker compose up --build
```

Поднимутся три контейнера: `db` (PostgreSQL 16), `app` (FastAPI) и `proxy` (nginx с TLS). При старте `app` автоматически применяет миграции Alembic (`alembic upgrade head`), засеивает справочники и реальный датасет (объекты, каналы датчиков, операционное окно журнала событий), поднимает эмуляцию внешних источников (ОДС/реестр/заявки/replay СМВУ) и материализует события/прогнозы. `proxy` при первом запуске сам создаёт самоподписанный сертификат.

API доступен только по HTTPS: **https://localhost:8443**. Порт 8080 отвечает перенаправлением на HTTPS. Приложение и база наружу напрямую не публикуются.

Проверка, что всё поднялось (`-k` — потому что сертификат самоподписанный):

```
curl -k https://localhost:8443/health
```

Ожидаемый ответ: `{"status":"ok"}`.

Остановка:

```
docker compose down
```

### Самоподписанный сертификат

- Браузер при первом заходе покажет предупреждение о недоверенном сертификате — это ожидаемо, его можно принять для демо.
- Для `curl` используйте ключ `-k`, для клиентов на Python/Node — отключение проверки сертификата только в демо-окружении.
- Сертификат хранится в томе `proxy_certs` и переиспользуется при перезапусках. Чтобы поставить свой (например, выпущенный УЦ заказчика), положите `server.crt` и `server.key` в этот том; чтобы пересоздать самоподписанный — удалите том `proxy_certs`.
- Если порты 8443/8080 заняты, задайте другие: `HTTPS_PORT=443 HTTP_PORT=80 docker compose up --build`.

## API-контракт

Swagger UI (интерактивная документация, тот же контракт, что видит фронтенд-команда): **https://localhost:8443/docs**
Машиночитаемая спецификация: `https://localhost:8443/openapi.json` (актуальный снимок для пакета сдачи — `docs/openapi.json`).

Основные группы эндпоинтов (`/api/v1/*`):

| Группа | Эндпоинты |
|---|---|
| Auth | `POST /auth/login`, `POST /auth/logout`, `GET /me` |
| Справочники | `GET /config` |
| Объекты | `GET /facilities`, `/facilities/{id}`, `/facilities/{id}/hierarchy`, `/facilities/{id}/layout` |
| Датчики | `GET /sensors`, `/sensors/{id}`, `/sensors/{id}/series` |
| События | `GET /events` |
| Риски/прогнозы | `GET /risks`, `/risks/{id}`, `POST /risks/{id}/acknowledge\|reject\|defer` |
| Заявки | `POST /work-orders`, `GET /work-orders` |
| Статус источников | `GET /system/source-health`, `GET /system/scenarios`, `POST /system/scenarios/{id}/activate`, `POST`/`DELETE /system/source-health/{source}/degrade` |
| Журнал аудита | `GET /audit` |

Каждый ответ несёт заголовок `X-Trace-Id`; по нему запрос находится в журнале аудита.

## Демо-пользователи

Сеятся автоматически при старте (см. `src/services/demo_seed.py`):

| Логин | Пароль | Роль | Scope | Права |
|---|---|---|---|---|
| `manager` | `manager123` | Руководитель | все объекты | все, включая `system.manage` (управление эмуляцией) и `audit.read` (журнал аудита) |
| `dispatcher` | `dispatcher123` | Диспетчер объекта | только `fac_5122`/`fac_5339` | `facility.read.assigned`, `sensor.read`, `risk.read`, `risk.acknowledge`, `work_order.read`, `work_order.create_draft` |

Сессия действует 480 минут (`SESSION_TTL_MINUTES`), `POST /auth/logout` завершает её сразу. После 5 неудачных попыток входа логин блокируется на время окна (ответ 429) — подробности в `docs/SECURITY.md`.

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

База из `docker compose` наружу не публикуется, поэтому для локального запуска нужен свой PostgreSQL, например:

```
docker run -d --name mkl-dev-db -e POSTGRES_USER=mkl -e POSTGRES_PASSWORD=mkl -e POSTGRES_DB=mkl -p 5432:5432 postgres:16-alpine
```

Локальный `uvicorn` работает по обычному HTTP на `http://localhost:8000` — TLS обеспечивает только прокси в `docker compose`.

## Тесты

Внутри Docker (ничего устанавливать не нужно):

```
docker compose up -d --wait db
docker compose run --rm --no-deps app sh -c "alembic upgrade head && pytest -q"
```

Локально — `pytest` с доступной базой в `DATABASE_URL` (см. раздел выше).

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
| `SESSION_TTL_MINUTES` | срок жизни сессии после входа | `480` |
| `LOGIN_MAX_FAILURES_PER_USERNAME` | неудачных входов на один логин в окне до блокировки | `5` |
| `LOGIN_MAX_FAILURES_PER_IP` | неудачных входов с одного IP в окне до блокировки | `20` |
| `LOGIN_FAILURE_WINDOW_SECONDS` | окно подсчёта неудачных входов, секунд | `900` |
| `HTTPS_PORT` | порт хоста для HTTPS (docker compose) | `8443` |
| `HTTP_PORT` | порт хоста для перенаправления с HTTP (docker compose) | `8080` |

## Переключение на реальную ML-модель

Backend взаимодействует с ML-частью через простой HTTP-контракт (не Python-интерфейс внутри бэкенда — команды пишут код параллельно и асинхронно, см. `docs/adr/0001-backend-only-mvp-scope-with-integration-ports.md` и `0006-ml-port-bespoke-not-indastrics-shaped.md`). Чтобы подключить обученную модель вместо `StubPredictor`, ML-команде достаточно поднять сервис, отвечающий `POST {ML_PREDICTOR_URL}/predict` по контракту в `src/services/ml_port.py` (`PredictionInput`/`PredictionResult`), и указать его URL в `ML_PREDICTOR_URL` — код бэкенда менять не нужно.
