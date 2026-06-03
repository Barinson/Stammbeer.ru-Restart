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


## Первый публичный storefront

- Страница магазина: `http://127.0.0.1:8000/business` или `/business/catalog`.
- Локальный API каталога: `GET /api/public/business/catalog`.
- Фильтры: `containerType=all|keg|can`; публичная страница использует только локальную read-model `business_catalog_items` и не делает live-запросы в МойСклад.
- Если локальная read-model пустая, storefront показывает пустое состояние без предложения пользователю запускать синхронизацию.


## Проверка подключения к МойСклад

Кнопка `Проверить подключение` в `/admin/moysklad` делает серверный `GET`-запрос к JSON API 1.2 с `Authorization: Bearer <token>`, `Accept: application/json;charset=utf-8` и `Accept-Encoding: gzip`. Для GET-запроса намеренно не отправляется `Content-Type` и body, чтобы не провоцировать `415 Unsupported Media Type`.

После успешной проверки backend загружает реальные справочники из МойСклад: `entity/store` для складов и `entity/productfolder` для папок продукции. Экран настроек показывает их как dropdown-списки; сохраняются `id`, `href/meta.href` и `name` выбранного склада и выбранной папки, а галочка «Включать дочерние папки» подготавливает будущий sync к импорту вложенных папок.


## Ручная синхронизация товаров

После настройки токена, склада и папки продукции в `/admin/moysklad` администратор может нажать `Синхронизировать товары сейчас`. Это запускает server-side ручной sync: SKU читаются из выбранной папки МойСклад; если включены дочерние папки, sync сначала загружает дерево `entity/productfolder` и рекурсивно собирает всю ветку выбранной папки. Остатки читаются из `report/stock/all` с фильтром выбранного склада и `quantityMode=positiveOnly`; в локальный каталог импортируются только SKU с положительным свободным доступом (`Доступное = остаток - резерв`), цена сохраняется из `salePrices` с типом `Цена продажи` в минорных единицах за 1 SKU. Данные upsert-ятся в локальные `products` / `product_overrides` / `inventory_snapshots`, а результат пишется в `moysklad_sync_jobs` и `moysklad_sync_logs`. Новые SKU остаются скрытыми; в публичный storefront они попадают только после публикации в `/admin/catalog`.

## Проверки

```bash
python3 -m unittest discover -s tests
python3 -m compileall app tests
```
