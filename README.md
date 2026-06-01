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

## Проверки

```bash
python3 -m unittest discover -s tests
python3 -m compileall app tests
```
