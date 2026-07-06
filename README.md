# Stamm Brewing Core Skeleton

Первый рабочий технический каркас нового сайта Stamm Brewing. На этом этапе реализованы:

- backend skeleton на Python standard library;
- SQLite/PostgreSQL-friendly SQL schema foundation;
- базовая admin auth с sessions и RBAC seed;
- admin shell с разделами Dashboard, Каталог, МойСклад, B2B-заявки, Контент, Пользователи и роли;
- стартовый экран настроек МойСклад;
- integration layer для МойСклад JSON API 1.2;
- публичная foundation-страница без live-запросов к МойСклад.

## Быстрый старт

```bash
python3 -m app.main
```

По умолчанию dev-БД создаётся в `var/stamm.sqlite3`.

Dev admin credentials задаются переменными окружения:

```bash
export ADMIN_EMAIL=admin
export ADMIN_PASSWORD=1
python3 -m app.main
```

Если переменные не заданы, используются dev-only значения `admin` / `1`. Сменить пароль можно в админке: `Профиль` → `Смена пароля`.


## Запуск через Docker

Продакшн-стек поднимается через `docker compose` и состоит из двух сервисов: приложение (`app`) и reverse proxy `caddy` с автоматическим HTTPS от Let's Encrypt (получение и продление сертификата — без ручных действий).

БД остаётся SQLite: файл `stamm.sqlite3` и загруженные медиа хранятся в именованном томе `app-data` (`/app/var`), миграции применяются автоматически при старте.

1. Подготовьте переменные окружения:

   ```bash
   cp .env.example .env
   # заполните DOMAIN, ACME_EMAIL, SESSION_SECRET, ADMIN_EMAIL, ADMIN_PASSWORD
   # для продакшена: APP_ENV=production, PUBLIC_BASE_URL=https://<домен>
   ```

2. Соберите и запустите (версия и git-ревизия зашиваются в образ и OCI-метки):

   ```bash
   export GIT_SHA=$(git rev-parse --short HEAD) BUILD_DATE=$(date -u +%Y-%m-%dT%H:%M:%SZ)
   docker compose up -d --build
   ```

3. Проверка: `https://<DOMAIN>/healthz` должен вернуть `{"ok": true, ...}` с валидным сертификатом.

Требования для TLS: публичный домен с A-записью на сервер и открытые порты `80`/`443`. Сертификаты хранятся в томе `caddy-data` — не удаляйте его, чтобы не терять выданные сертификаты между рестартами.

Версия приложения задаётся в `docker-compose.yml`: тег образа `stammbeer-app:0.1.0` и OCI-label `org.opencontainers.image.version` (через `build.args.APP_VERSION`). Больше нигде не дублируется — при выпуске новой версии обновите обе строки в `docker-compose.yml` (тег `image` и `APP_VERSION`). Посмотреть: `docker images | grep stammbeer-app` (тег) и `docker inspect stammbeer-app:0.1.0 --format '{{json .Config.Labels}}'` (лейблы). Для локальной отладки без Caddy можно раскомментировать проброс порта `8000:8000` в сервисе `app` и обращаться к `http://localhost:8000`.

Резервное копирование БД — копирование `stamm.sqlite3` из тома `app-data` (лучше через `sqlite3 .backup`, чтобы не поймать блокировку записи).


## Первый публичный storefront

- Страница магазина: `http://127.0.0.1:8000/business` или `/business/catalog`.
- Локальный API каталога: `GET /api/public/business/catalog`.
- Фильтры: `containerType=all|keg|can`; публичная страница использует только локальную read-model `business_catalog_items` и не делает live-запросы в МойСклад.
- Если локальная read-model пустая, storefront показывает пустое состояние без предложения пользователю запускать синхронизацию.


## Проверка подключения к МойСклад

Кнопка `Проверить подключение` в `/admin/moysklad` делает серверный `GET`-запрос к JSON API 1.2 с `Authorization: Bearer <token>`, `Accept: application/json;charset=utf-8` и `Accept-Encoding: gzip`. Для GET-запроса намеренно не отправляется `Content-Type` и body, чтобы не провоцировать `415 Unsupported Media Type`.

После успешной проверки backend загружает реальные справочники из МойСклад: `entity/store` для складов и `entity/productfolder` для папок продукции. Экран настроек показывает их как dropdown-списки; сохраняются `id`, `href/meta.href` и `name` выбранного склада и выбранной папки, а галочка «Включать дочерние папки» подготавливает будущий sync к импорту вложенных папок.


## Ручная синхронизация товаров

После настройки токена, склада и папки продукции в `/admin/moysklad` администратор может нажать `Синхронизировать товары сейчас`. Это запускает server-side ручной sync: SKU читаются из выбранной папки МойСклад; если включены дочерние папки, sync сначала загружает дерево `entity/productfolder` и рекурсивно собирает всю ветку выбранной папки. Остатки читаются отдельно от папки из складского отчёта `report/stock/bystore` с `stockMode=positiveOnly`, а выбранный склад применяется при разборе `stockByStore`; в локальный каталог импортируются только SKU с положительным свободным доступом (`Доступное = остаток - резерв`), цена сохраняется из `salePrices` с типом `Цена продажи` в минорных единицах за 1 SKU. Данные upsert-ятся в локальные `products` / `product_overrides` / `inventory_snapshots`, а результат пишется в `moysklad_sync_jobs` и `moysklad_sync_logs`, включая diagnostic sample по match stock report → SKU → saved available/status. Для углубленной проверки включите чекбокс `Diagnostic mode` перед ручным sync: в разделе МойСклад появятся первые 10 SKU из папки, первые 10 строк stock report, matching и фактические DB writes/local catalog after sync. Новые SKU остаются скрытыми; в публичный storefront они попадают только после публикации в `/admin/catalog`.


## Фото SKU в storefront

Во время ручной синхронизации sync пытается взять фото SKU из `images`/`image`/`files` в ответе МойСклад; если в assortment-строке нет вложенных изображений, server-side sync запрашивает `/images` для конкретной SKU. Найденный `downloadHref`/`href` сохраняется в локальное поле `products.image_url`, затем при публикации копируется в локальную read-model `business_catalog_items.image_url`. Публичный storefront читает только это локальное поле и не делает live-запросы в МойСклад; если фото нет, карточка показывает брендированную заглушку.

## Email через Яндекс

Почтовая отправка вынесена в отдельный слой `app.modules.email`: сервис создаёт одноразовые токены, рендерит шаблоны, отправляет письма через единый SMTP transport и пишет результат в `email_send_logs`. Провайдер на первом этапе — Яндекс Почта / Яндекс 360 через SMTP.

Минимальная конфигурация задаётся переменными окружения:

```bash
export PUBLIC_BASE_URL=http://127.0.0.1:8000
export EMAIL_PROVIDER=yandex
export EMAIL_ENABLED=true
export EMAIL_SMTP_HOST=smtp.yandex.com
export EMAIL_SMTP_PORT=465
export EMAIL_SMTP_USERNAME=mailer@example.com
export EMAIL_SMTP_PASSWORD=app-password-from-yandex
export EMAIL_FROM_EMAIL=mailer@example.com
export EMAIL_FROM_NAME="Stamm Brewing"
```

Для локальной разработки можно оставить `EMAIL_ENABLED=false`: письма не будут уходить наружу, но токены и записи о попытках отправки сохранятся локально.

Поддержанные письма первого этапа:

- подтверждение e-mail после регистрации: `GET /account/verify-email?token=...`;
- восстановление пароля: `/account/password-reset` → `/account/password-reset/confirm`;
- уведомление «заказ создан» после успешной отправки B2B-заказа в МойСклад.


## Проверки

```bash
python3 -m unittest discover -s tests
python3 -m compileall app tests
```
