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
export ADMIN_EMAIL=admin@stamm.local
export ADMIN_PASSWORD=change-me
python3 -m app.main
```

Если переменные не заданы, используются dev-only значения `admin@stamm.local` / `stamm-admin`.

## Проверки

```bash
python3 -m unittest discover -s tests
python3 -m compileall app tests
```
