# Stamm Brewing: спецификация реализации ядра «Бизнес + админка + МойСклад»

## 0. Назначение документа

Этот документ переводит архитектурное решение Stamm Brewing в прикладную спецификацию реализации. Он описывает экраны публичного B2B-раздела «Бизнес», рабочие экраны админки, модель данных, API-контракты и практический сценарий синхронизации с МойСклад JSON API 1.2.

Базовое правило остаётся неизменным: публичный раздел «Бизнес» работает только от локальной базы сайта и локальной read-model каталога. Публичный пользователь не может запустить загрузку товаров, остатков или цен из МойСклад. Все обращения к МойСклад выполняются серверными sync-job-ами по расписанию или вручную из админки с соответствующими правами.

## 1. Экранная модель публичного раздела «Бизнес»

### 1.1. Общие правила публичного B2B-раздела

- Источник данных: только локальная read-model `business_catalog_items`.
- Допустимые публичные действия: просмотр каталога, фильтрация, поиск, просмотр карточки, добавление в корзину-заявку, отправка заявки.
- Недопустимые публичные действия: прямой запрос к МойСклад, кнопка «Загрузить товары», обновление остатков по клику, ручной sync.
- Актуальность данных: интерфейс может показывать нейтральную подпись «Данные обновлены: <дата последней успешной синхронизации>», но только если бизнес решит, что это полезно партнёрам.
- Заказ на первом этапе — это B2B-заявка, а не гарантированное онлайн-бронирование остатка.

### 1.2. Экран 1: каталог `/business/catalog`

#### 1.2.1. Назначение

Каталог позволяет партнёру быстро собрать заявку по опубликованным SKU. Экран должен быть быстрым, индексируемым, удобным для повторных закупок и не должен зависеть от текущей доступности МойСклад.

#### 1.2.2. Структура страницы

1. Верхний блок
   - заголовок «Каталог для бизнеса»;
   - краткое пояснение: «Выберите позиции и отправьте заявку — менеджер подтвердит наличие и условия»;
   - ссылка на условия партнёрства;
   - компактный индикатор корзины-заявки.
2. Панель поиска и быстрых фильтров
   - полнотекстовый поиск по названию, SKU, артикулу, стилю и типу тары;
   - быстрые чипы: «В наличии», «Кеги», «Банки», «Бутылки», «Новинки», «Сезонное».
3. Левая или выдвижная панель фильтров
   - на desktop: боковая панель;
   - на mobile: drawer по кнопке «Фильтры».
4. Область результатов
   - количество найденных SKU;
   - активные фильтры с возможностью сброса;
   - селектор сортировки;
   - сетка карточек товаров.
5. Нижняя навигация
   - пагинация с кнопкой «Показать ещё»;
   - SEO-friendly ссылки на страницы пагинации.
6. Empty/error state
   - отдельные состояния для пустого каталога, отсутствия результатов и ошибки локального API.

#### 1.2.3. Фильтры

| Фильтр | Источник | Тип UI | Поведение |
| --- | --- | --- | --- |
| Тип тары | `business_catalog_items.container_type` | checkbox/chips | Множественный выбор: кег, банка, бутылка, короб. |
| Наличие | `availability_status` | checkbox/chips | `available`, `limited`, `preorder`, `unavailable`; по умолчанию показывать опубликованные, включая `limited`. |
| Категория / папка | `catalog_folders` + ручные витринные категории | tree/select | Позволяет сузить ассортимент по папке источника или витринной группе. |
| Объём | `volume_liters` | checkbox/range | Например 0.33, 0.5, 20, 30. |
| Бейджи | `product_badges` / `badges_json` | chips | «Новинка», «Сезонное», «HoReCa». |
| Цена | `price_minor` | range | Включается, если бизнес разрешает показывать цены публично. |
| Только опубликованные | `is_published` | скрытый фильтр | Всегда `true` для публичного API. |

#### 1.2.4. Поиск

- Поиск выполняется по локальному индексу: `public_name`, `accounting_name`, `sku`, `article`, `code`, `style`, `container_type`, `badges`.
- Минимальная длина запроса: 2 символа.
- Результаты не обращаются к МойСклад и не зависят от sync в момент запроса.
- Рекомендуется серверный поиск через PostgreSQL full-text/trigram index или отдельный search-index, который обновляется после успешного sync и изменения override-полей.

#### 1.2.5. Сортировки

| Сортировка | Ключ | Правило |
| --- | --- | --- |
| Рекомендуемое | `sort_order`, `availability_rank`, `public_name` | Значение по умолчанию: ручной порядок + доступность. |
| Сначала в наличии | `availability_rank`, `sort_order` | `available` выше `limited`, затем `preorder`, затем `unavailable`. |
| Новинки | `is_new`, `created_at` | По ручному бейджу или дате первого появления в локальном каталоге. |
| Название | `public_name` | Алфавитно. |
| Цена | `price_minor` | Если цены публичны. |

#### 1.2.6. Карточка товара в каталоге

Карточка в списке содержит:

- изображение или брендовый placeholder на базе Flavorful Foam;
- бейджи: «в наличии», «мало», «предзаказ», «нет в наличии», «новинка»;
- публичное название;
- тип тары и объём;
- SKU/артикул короткой строкой;
- цену или подпись «Цена по запросу», если цены скрыты;
- доступное количество в обобщённом виде, например «в наличии», «мало», без точных остатков, если бизнес не хочет раскрывать склад;
- stepper количества;
- CTA «В заявку»;
- ссылку «Подробнее».

#### 1.2.7. Пагинация: выбранный вариант

Выбранный вариант: классическая серверная пагинация + кнопка «Показать ещё».

Обоснование:

- лучше для SEO, чем бесконечная прокрутка;
- стабильнее для B2B-каталога с фильтрами;
- проще сохранять ссылку на конкретный набор фильтров;
- снижает нагрузку на frontend и backend;
- не создаёт ощущения «соцсеточной» ленты, что не подходит премиальному B2B-каталогу.

Техническое правило: API принимает `page` и `pageSize`, возвращает `pagination.hasNext`, а UI может рендерить обычные страницы или progressive «Показать ещё» без изменения API.

### 1.3. Экран 2: карточка товара `/business/catalog/[slug]`

#### 1.3.1. Назначение

Карточка объясняет партнёру, что именно он добавляет в заявку, в какой таре, по какой цене/условию и с каким текущим локальным статусом доступности.

#### 1.3.2. Поля на странице

1. Галерея
   - основное изображение;
   - дополнительные изображения;
   - fallback-placeholder, если изображений нет;
   - alt-тексты из `media_assets.alt` или публичного названия товара.
2. Основная информация
   - публичное название `product_overrides.public_name` или fallback на `products.accounting_name`;
   - бейджи;
   - краткое описание;
   - тип тары;
   - объём;
   - SKU/артикул/код;
   - категория/стиль, если заполнены;
   - цена или «Цена по запросу»;
   - доступность.
3. Блок заказа
   - quantity stepper;
   - минимальная партия и кратность упаковки, если заданы;
   - CTA «Добавить в заявку»;
   - вторичный CTA «Задать вопрос менеджеру».
4. Детали
   - полное маркетинговое описание;
   - технические характеристики;
   - условия хранения/логистики, если нужны;
   - похожие позиции из локального каталога.
5. SEO
   - title/description/OG из `seo_metadata`, fallback из названия и описания.

#### 1.3.3. Цена и доступность

- Цена берётся из `product_prices` через read-model и может быть скрыта настройкой `catalog_price_visibility`.
- Доступность берётся из `inventory_levels.availability_status` или агрегированной read-model.
- Точные остатки показываются только если включена настройка `show_exact_stock_to_public`.
- Если товар опубликован, но недоступен, CTA меняется на «Запросить поставку» или отключается в зависимости от `allow_preorder`.

#### 1.3.4. Что можно заказать

- Только опубликованные SKU или варианты, которые входят в текущую локальную read-model.
- Нельзя заказать скрытый SKU, даже если прямой URL известен.
- Нельзя заказать SKU с `availability_status = hidden`.
- `unavailable` можно добавить только при `allow_preorder = true`, иначе CTA недоступен.

#### 1.3.5. Что не нужно в B2B-карточке первого этапа

- Онлайн-оплата.
- Персональные цены по авторизации партнёра.
- Live-обновление остатков из МойСклад.
- Сложный конфигуратор доставки.
- Комментарии/рейтинги.
- Публичная демонстрация внутренних складов, если это не требуется бизнесом.

### 1.4. Экран 3: корзина / заявка `/business/cart`

#### 1.4.1. Добавление товара

- Пользователь добавляет SKU из каталога или карточки товара.
- Frontend отправляет `productId`/`variantId` и `quantity` в локальную корзину.
- Корзина может храниться в browser storage для гостя, но при отправке всегда валидируется backend-ом по локальной базе.
- Backend не обращается к МойСклад при добавлении, изменении или отправке заявки.

#### 1.4.2. Изменение количества

- Количество меняется stepper-ом или числовым полем.
- UI учитывает `min_order_quantity` и `order_step`, если они заданы в override-правилах.
- При попытке указать 0 товар удаляется из корзины.
- При превышении локального available quantity UI показывает предупреждение, но финальное решение зависит от политики: запретить, разрешить как запрос менеджеру или перевести в preorder.

#### 1.4.3. Оформление заявки

Поля формы:

| Поле | Обязательность | Комментарий |
| --- | --- | --- |
| Имя контактного лица | обязательно | `contact_name` |
| Компания | обязательно | `company_name` |
| ИНН | желательно/обязательно по решению бизнеса | `inn` с базовой валидацией |
| Телефон | обязательно | `phone` |
| Email | обязательно | `email` |
| Город | обязательно | `city` |
| Тип партнёра | опционально | бар, ресторан, магазин, дистрибьютор |
| Комментарий | опционально | свободный текст |
| Согласие на обработку данных | обязательно | если форма собирает персональные данные |

#### 1.4.4. Финальная заявка

Перед отправкой пользователь видит:

- список позиций;
- количество;
- цену/условную цену;
- сумму, если цены публичны;
- статусы доступности;
- предупреждение: «Заявка не является резервом до подтверждения менеджером»;
- контактные данные;
- кнопку «Отправить заявку».

#### 1.4.5. Что уходит в backend

`POST /api/public/b2b/orders` получает:

- контактные поля;
- массив позиций: `productId`, `variantId`, `quantity`;
- client-side cart id, если используется;
- UTM/referrer, если есть;
- consent flags;
- комментарий.

Backend самостоятельно формирует snapshot каждой позиции из локальной базы: публичное название, SKU, цена, доступность, sync timestamp и внешний `moysklad_href`. Клиент не присылает цену как источник истины.

### 1.5. Экран 4: пустые и крайние состояния

#### 1.5.1. Пустой каталог

Условие: в read-model нет опубликованных SKU.

UI:

- заголовок «Каталог скоро появится»;
- текст: «Мы готовим B2B-каталог Stamm Brewing. Оставьте контакты — менеджер свяжется с вами»;
- CTA «Оставить заявку партнёра»;
- без упоминания технических проблем МойСклад.

#### 1.5.2. Нет доступных SKU

Условие: товары опубликованы, но все имеют `unavailable` и `allow_preorder = false`.

UI:

- каталог можно показывать, но CTA отключены;
- общий баннер: «Сейчас позиции временно недоступны для заявки»;
- CTA «Связаться с менеджером».

#### 1.5.3. Ошибка загрузки локального каталога

Условие: публичный API сайта недоступен или вернул ошибку.

UI:

- текст: «Не удалось загрузить каталог сайта. Попробуйте обновить страницу или отправьте заявку менеджеру»;
- CTA на форму связи;
- ошибка логируется в monitoring;
- не предлагать «обновить из МойСклад».

#### 1.5.4. Нет результатов фильтрации

UI:

- показать активные фильтры;
- кнопки «Сбросить фильтры» и «Показать всё»;
- подсказка изменить тип тары/наличие;
- не показывать техническую ошибку.

## 2. Экранная модель админки

### 2.1. Общие правила админки

- Вход только для авторизованных пользователей.
- Все изменения критичных сущностей пишутся в `audit_events`.
- Токен МойСклад никогда не показывается полностью после сохранения.
- Ручной sync доступен только ролям `admin` и `integration_manager`.
- Каталоговые override-поля доступны `admin` и `catalog_manager`.
- Заявки доступны `admin` и `sales_manager`.

### 2.2. Раздел «Дашборд» `/admin`

#### Виджеты

1. Статус системы
   - API сайта: ok/degraded/down;
   - очередь sync: idle/running/backoff;
   - локальная БД: ok/degraded;
   - storage медиа: ok/degraded.
2. Синхронизация
   - последняя успешная синхронизация;
   - последний запуск;
   - текущий статус job;
   - длительность последнего sync;
   - ссылка на лог.
3. Каталог
   - число опубликованных SKU;
   - число скрытых SKU;
   - число SKU вне папки-источника;
   - число SKU без изображений;
   - число SKU без публичного slug.
4. Ошибки
   - последние ошибки sync;
   - последние ошибки публичного API;
   - предупреждения о просроченном last-known-good state.
5. B2B-заявки
   - новые заявки;
   - заявки в обработке;
   - заявки за 7 дней.

#### Действия

- перейти в каталог;
- перейти в настройки МойСклад;
- перейти к последним заявкам;
- ручной sync — только если пользователь имеет право и нет активной job.

### 2.3. Раздел «Каталог» `/admin/catalog`

#### 2.3.1. Список товаров

Таблица:

| Колонка | Значение |
| --- | --- |
| Фото | главное изображение или placeholder |
| Публичное название | override или fallback |
| Учётное название | из МойСклад |
| SKU / код | из sync |
| Тара / объём | sync + override fallback |
| Цена | из локальных цен |
| Остаток/доступность | локальный агрегат |
| Публикация | toggle `is_published` |
| Порядок | `sort_order` |
| Последний sync | `last_synced_at` |
| Ошибки | последняя ошибка по SKU, если есть |

Фильтры:

- публикация: опубликован/скрыт;
- доступность;
- тип тары;
- папка-источник;
- без изображений;
- без описания;
- без slug;
- вне источника;
- изменённые вручную;
- поиск по названию, SKU, коду, external id.

Действия:

- открыть карточку товара;
- быстро опубликовать/скрыть;
- массово скрыть;
- массово назначить бейдж;
- массово пересчитать slug для выбранных без slug;
- drag-and-drop сортировка в пределах текущей витринной группы.

#### 2.3.2. Редактирование карточки товара `/admin/catalog/products/[id]`

Вкладки:

1. Обзор
   - публичное название;
   - учётное название read-only;
   - статус публикации;
   - доступность read-only;
   - SKU/код read-only;
   - цена read-only или override, если бизнес разрешит;
   - ссылка на внешний объект МойСклад для админа.
2. Описание
   - краткое описание;
   - полное описание;
   - характеристики;
   - бейджи;
   - публичная витринная категория.
3. Медиа
   - главное изображение;
   - галерея;
   - alt-тексты;
   - порядок изображений.
4. Заказ
   - разрешить предзаказ;
   - минимальное количество;
   - шаг заказа;
   - предупреждающий текст для клиента.
5. SEO
   - slug;
   - meta title;
   - meta description;
   - OG image;
   - `noindex`.
6. Sync
   - external id;
   - external href;
   - source folder;
   - last synced at;
   - raw sync summary;
   - история изменений sync.

### 2.4. Раздел «МойСклад» `/admin/moysklad`

#### 2.4.1. Настройки подключения

Поля:

- API base URL: по умолчанию `https://api.moysklad.ru/api/remap/1.2`;
- тип авторизации: Bearer token;
- токен: ввод/замена, после сохранения masked value;
- активность подключения;
- кнопка «Проверить подключение»;
- результат последней проверки.

Доступ: `admin`, `integration_manager`.

#### 2.4.2. Источник каталога

Поля:

- папка-источник `source_product_folder_href`/`id`;
- режим включения дочерних папок;
- выбранные склады для остатков;
- тип цены / price type;
- правило для товаров, ушедших из источника: скрыть, пометить out_of_scope, оставить только админский просмотр;
- настройка точности публичных остатков: exact/generalized/hidden.

UI выбора папки:

- кнопка «Загрузить дерево папок» доступна только в админке;
- результат сохраняется локально;
- выбор папки не запускает публичную загрузку товаров;
- после смены папки админ получает предупреждение, что нужен новый full sync.

#### 2.4.3. Расписание синхронизации

Поля:

- full sync interval: например 6 часов;
- stock sync interval: например 1–3 часа;
- enabled/disabled;
- backoff strategy;
- timezone;
- максимальная длительность job;
- запрет параллельного запуска.

#### 2.4.4. Ручной запуск

Кнопки:

- «Синхронизировать каталог сейчас»;
- «Синхронизировать остатки сейчас»;
- «Проверить подключение».

Правила:

- кнопка disabled, если job уже running;
- запуск создаёт `moysklad_sync_jobs` со статусом `queued`;
- UI показывает progress/status через polling локального admin API;
- отмена job возможна только если worker поддерживает cooperative cancel.

#### 2.4.5. Логи

Таблица sync jobs:

- id;
- type;
- status;
- started by;
- started at;
- finished at;
- duration;
- created/updated/hidden/skipped counts;
- ссылка на подробный лог.

Подробный лог:

- timestamp;
- level;
- stage;
- entity type;
- external id/href;
- message;
- normalized error code;
- request id/correlation id, если доступен;
- sanitized payload excerpt без токенов.

### 2.5. Раздел «B2B-заявки» `/admin/b2b/orders`

#### 2.5.1. Список заявок

Колонки:

- номер заявки;
- дата;
- статус;
- компания;
- контакт;
- город;
- количество позиций;
- сумма, если есть цены;
- источник/UTM;
- ответственный менеджер;
- пометка экспорта.

Фильтры:

- статус;
- период;
- менеджер;
- город;
- компания/ИНН;
- наличие ошибок экспорта;
- поиск по номеру/телефону/email.

#### 2.5.2. Детали заявки

Блоки:

1. Контактные данные.
2. Реквизиты компании.
3. Позиции заявки.
4. Snapshot по каждой позиции: название, SKU, цена, статус доступности, external href, sync timestamp.
5. История статусов.
6. Комментарии менеджера.
7. UTM/referrer.
8. Действия: изменить статус, назначить ответственного, пометить как переданную, экспортировать позже.

Статусы:

- `new`;
- `in_review`;
- `confirmed`;
- `waiting_customer`;
- `rejected`;
- `exported`;
- `cancelled`.

### 2.6. Раздел «Контент» `/admin/content`

Экраны:

- список страниц;
- редактор страницы;
- блоки страницы;
- баннеры;
- медиа-библиотека;
- SEO-метаданные.

Для первого ядра достаточно поддержать страницы:

- `/business`;
- служебные тексты каталога;
- пустые состояния;
- success-страницу заявки.

Позже сюда добавляются «Пиво», «Посетить пивоварню», «История», «Контакты».

### 2.7. Раздел «Пользователи и роли» `/admin/users`

Экраны:

- список пользователей;
- создание/редактирование пользователя;
- назначение ролей;
- матрица permissions;
- журнал входов и критичных действий.

Минимальные permissions:

- `content.read`, `content.write`, `content.publish`;
- `catalog.read`, `catalog.write_overrides`, `catalog.publish`;
- `moysklad.read`, `moysklad.write_settings`, `moysklad.run_sync`;
- `orders.read`, `orders.write_status`, `orders.export`;
- `users.read`, `users.write`;
- `audit.read`.

## 3. Модель данных

### 3.1. Правила моделирования

- Синхронизируемые поля и ручные override-поля разделяются.
- Внешние идентификаторы МойСклад уникальны и не используются как primary key публичной модели.
- Заявки хранят snapshot, чтобы изменения каталога после отправки не меняли историю.
- Sync обновляет staging/sync-поля, затем атомарно публикует read-model.
- Last-known-good state хранится отдельно от текущей неуспешной попытки sync.

### 3.2. Сущности каталога и синхронизации

| Сущность | Назначение | Ключевые поля | Связи | Из МойСклад | Ручное в админке |
| --- | --- | --- | --- | --- | --- |
| `catalog_folders` | Локальное дерево папок каталога | `id`, `external_id`, `external_href`, `parent_id`, `name`, `path`, `is_in_source_scope`, `last_synced_at` | parent-child, products | id/href/name/parent/path | витринный порядок, скрытие витринной группы при необходимости |
| `products` | Базовая локальная карточка учётной позиции | `id`, `external_id`, `external_href`, `folder_id`, `accounting_name`, `code`, `article`, `external_code`, `unit_name`, `is_archived`, `sync_updated_at`, `last_synced_at` | folder, variants, prices, inventory, overrides | основные учётные поля | напрямую не редактируется, только read-only |
| `product_variants` | Модификации/SKU, если позиция имеет варианты | `id`, `product_id`, `external_id`, `external_href`, `name`, `code`, `attributes_json`, `last_synced_at` | product, prices, inventory | модификации и атрибуты | порядок/публикация через visibility/override |
| `product_prices` | Локальные цены по типам цен | `id`, `product_id`, `variant_id`, `price_type_external_id`, `price_minor`, `currency`, `last_synced_at` | product/variant | salePrices/price types | обычно read-only; override только отдельным разрешением |
| `inventory_snapshots` | Снимки остатков после sync | `id`, `sync_job_id`, `product_id`, `variant_id`, `store_external_id`, `stock`, `reserve`, `in_transit`, `available_quantity`, `captured_at` | sync job, product/variant | stock report | не редактируется |
| `inventory_levels` | Текущий агрегированный остаток для витрины | `id`, `product_id`, `variant_id`, `stock`, `reserve`, `available_quantity`, `availability_status`, `last_successful_sync_job_id`, `last_synced_at` | product/variant | вычисляется из snapshot | пороги статусов через настройки |
| `product_overrides` | Витринные поля поверх учётных данных | `id`, `product_id`, `public_name`, `slug`, `short_description`, `description`, `container_type_override`, `volume_liters_override`, `is_published`, `allow_preorder`, `min_order_quantity`, `order_step`, `sort_order`, `seo_metadata_id`, `updated_by_user_id` | product, seo, user | нет | да |
| `product_images` | Галерея товара | `id`, `product_id`, `media_asset_id`, `role`, `sort_order`, `alt`, `is_active` | product, media | опционально позже | да |
| `product_badges` | Нормализованные бейджи | `id`, `code`, `label`, `color_token`, `is_active` | product_badge_assignments | нет | да |
| `product_badge_assignments` | Связь товара и бейджа | `product_id`, `badge_id`, `sort_order` | product, badge | нет | да |
| `catalog_visibility_rules` | Глобальные правила видимости | `id`, `rule_type`, `payload_json`, `is_active`, `priority` | products/read-model | нет | да |
| `business_catalog_items` | Read-model публичного каталога | `product_id`, `variant_id`, `slug`, `public_name`, `image_url`, `price_minor`, `currency`, `container_type`, `volume_liters`, `availability_status`, `sort_order`, `search_vector`, `last_catalog_sync_at` | строится из catalog tables | агрегированно | не редактируется напрямую |
| `moysklad_sync_settings` | Настройки интеграции | `id`, `api_base_url`, `encrypted_token_ref`, `source_product_folder_href`, `include_child_folders`, `store_external_ids`, `price_type_external_id`, `full_sync_interval_minutes`, `stock_sync_interval_minutes`, `is_enabled`, `last_success_at`, `last_known_good_job_id` | sync jobs | нет | да, restricted |
| `moysklad_sync_jobs` | Запуски sync | `id`, `type`, `status`, `trigger`, `started_by_user_id`, `started_at`, `finished_at`, `lock_key`, `stats_json`, `error_summary` | logs, snapshots | нет | создаётся scheduler/admin action |
| `moysklad_sync_logs` | Детальный лог sync | `id`, `job_id`, `level`, `stage`, `entity_type`, `external_href`, `message`, `error_code`, `payload_excerpt_json`, `created_at` | sync job | ошибки/данные API | не редактируется |
| `moysklad_raw_snapshots` | Опциональный retention raw payload | `id`, `job_id`, `entity_type`, `external_id`, `payload_json`, `expires_at` | sync job | raw API | не редактируется |

### 3.3. Сущности B2B-заявок

| Сущность | Назначение | Ключевые поля | Связи | Из МойСклад | Ручное в админке |
| --- | --- | --- | --- | --- | --- |
| `b2b_partners` | Потенциальные/существующие партнёры | `id`, `company_name`, `inn`, `city`, `partner_type`, `status`, `created_at` | orders | можно сопоставить с контрагентом позже | статус, менеджер, заметки |
| `b2b_orders` | Заявка из публичной корзины | `id`, `number`, `status`, `partner_id`, `contact_name`, `company_name`, `inn`, `email`, `phone`, `city`, `comment`, `total_minor`, `currency`, `source_json`, `created_at` | partner, items, history | нет на первом этапе | статусы, ответственный, заметки |
| `b2b_order_items` | Позиции заявки | `id`, `order_id`, `product_id`, `variant_id`, `quantity`, `price_minor`, `line_total_minor`, `product_snapshot_json`, `availability_snapshot_json` | order, product/variant | нет | обычно read-only после создания |
| `b2b_order_status_history` | История статусов | `id`, `order_id`, `from_status`, `to_status`, `changed_by_user_id`, `comment`, `created_at` | order, user | нет | создаётся действиями менеджера |
| `b2b_order_notes` | Внутренние заметки | `id`, `order_id`, `user_id`, `body`, `created_at` | order, user | нет | да |
| `b2b_exports` | Будущий экспорт в МойСклад | `id`, `order_id`, `target`, `status`, `external_href`, `payload_json`, `error_summary`, `created_at` | order | результат API позже | запуск/повтор по правам |

### 3.4. Сущности контента, SEO и пользователей

| Сущность | Назначение | Ключевые поля | Связи | Из МойСклад | Ручное в админке |
| --- | --- | --- | --- | --- | --- |
| `content_pages` | Страницы сайта | `id`, `slug`, `title`, `status`, `template`, `seo_metadata_id`, `published_at` | blocks, seo | нет | да |
| `content_blocks` | Блоки страниц | `id`, `page_id`, `type`, `payload_json`, `sort_order`, `is_active` | page | нет | да |
| `banners` | Промо/инфо баннеры | `id`, `placement`, `title`, `body`, `media_asset_id`, `cta_label`, `cta_url`, `is_active`, `sort_order` | media | нет | да |
| `media_assets` | Файлы и изображения | `id`, `storage_key`, `url`, `mime_type`, `size_bytes`, `alt`, `created_by_user_id` | product_images, banners | нет | да |
| `seo_metadata` | SEO/OG | `id`, `meta_title`, `meta_description`, `canonical_url`, `og_title`, `og_description`, `og_image_id`, `robots` | pages/products | нет | да |
| `users` | Пользователи админки | `id`, `email`, `name`, `status`, `last_login_at`, `password_hash`/SSO fields | roles, audit | нет | restricted |
| `roles` | Роли | `id`, `code`, `name`, `description` | users, permissions | нет | restricted |
| `permissions` | Права | `id`, `code`, `description` | roles | нет | system seed |
| `role_permissions` | Матрица прав | `role_id`, `permission_id` | roles, permissions | нет | admin |
| `audit_events` | Аудит | `id`, `actor_user_id`, `action`, `entity_type`, `entity_id`, `before_json`, `after_json`, `ip`, `created_at` | users/entities | нет | не редактируется |

## 4. API-контракты

### 4.1. Общие правила API

- Публичные endpoint-ы читают только локальную БД.
- Admin API требует авторизации и permission checks.
- Интеграционные сервисы не вызываются из браузера напрямую.
- Все write-запросы принимают idempotency key там, где возможен повтор: заявки, sync запуск, export.
- Ошибки возвращаются в едином формате: `code`, `message`, `details`, `traceId`.

### 4.2. Публичные API

#### `GET /api/public/business/catalog`

Назначение: получить страницу локального каталога.

Доступ: публичный.

Query:

```json
{
  "q": "ipa",
  "containerType": ["keg", "can"],
  "availability": ["available", "limited"],
  "folderId": "uuid",
  "badges": ["new"],
  "volume": [0.33, 0.5],
  "sort": "recommended",
  "page": 1,
  "pageSize": 24
}
```

Response:

```json
{
  "items": [
    {
      "productId": "uuid",
      "variantId": null,
      "slug": "stamm-ipa-keg-30",
      "name": "Stamm IPA, кег 30 л",
      "image": { "url": "/media/...", "alt": "Stamm IPA" },
      "badges": [{ "code": "new", "label": "Новинка" }],
      "sku": "IPA-30",
      "containerType": "keg",
      "volumeLiters": 30,
      "price": { "amountMinor": 120000, "currency": "RUB", "visibility": "public" },
      "availability": { "status": "available", "label": "В наличии", "exactQuantity": null },
      "orderRules": { "minQuantity": 1, "step": 1, "allowPreorder": false }
    }
  ],
  "filters": {
    "containerTypes": [{ "value": "keg", "label": "Кеги", "count": 12 }],
    "availability": [{ "value": "available", "label": "В наличии", "count": 18 }]
  },
  "pagination": { "page": 1, "pageSize": 24, "total": 86, "hasNext": true },
  "meta": { "lastCatalogSyncAt": "2026-06-01T08:00:00Z" }
}
```

#### `GET /api/public/business/catalog/{slug}`

Назначение: получить карточку товара из локальной read-model.

Доступ: публичный.

Response:

```json
{
  "productId": "uuid",
  "variantId": null,
  "slug": "stamm-ipa-keg-30",
  "name": "Stamm IPA, кег 30 л",
  "shortDescription": "Плотный ароматный IPA для HoReCa.",
  "description": "...",
  "images": [{ "url": "/media/...", "alt": "Stamm IPA", "role": "main" }],
  "sku": "IPA-30",
  "article": "IPA-30",
  "containerType": "keg",
  "volumeLiters": 30,
  "price": { "amountMinor": 120000, "currency": "RUB", "visibility": "public" },
  "availability": { "status": "available", "label": "В наличии", "exactQuantity": null },
  "orderRules": { "minQuantity": 1, "step": 1, "allowPreorder": false },
  "seo": { "title": "...", "description": "...", "ogImage": "/media/..." }
}
```

Ошибки:

- `404 PRODUCT_NOT_FOUND` — товар не опубликован или slug неизвестен.

#### `GET /api/public/business/catalog/suggest`

Назначение: подсказки поиска по локальному индексу.

Доступ: публичный.

Query: `q`, `limit`.

Response:

```json
{
  "suggestions": [
    { "type": "product", "label": "Stamm IPA", "slug": "stamm-ipa-keg-30" },
    { "type": "container", "label": "Кеги", "value": "keg" }
  ]
}
```

#### `POST /api/public/b2b/orders`

Назначение: создать B2B-заявку из локальной корзины.

Доступ: публичный, с rate limit и антиспам-защитой.

Request:

```json
{
  "contact": {
    "contactName": "Иван Петров",
    "companyName": "Бар Хмель",
    "inn": "7700000000",
    "phone": "+79990000000",
    "email": "buyer@example.com",
    "city": "Москва",
    "partnerType": "bar"
  },
  "items": [
    { "productId": "uuid", "variantId": null, "quantity": 2 }
  ],
  "comment": "Интересует поставка на следующей неделе",
  "consents": { "personalData": true },
  "source": { "utm": {}, "referrer": "https://..." }
}
```

Backend validation:

- товар опубликован;
- товар присутствует в local read-model;
- quantity соответствует `minQuantity` и `step`;
- при `unavailable` проверяется `allowPreorder`;
- цена и snapshot берутся из локальной базы, а не из request.

Response:

```json
{
  "orderId": "uuid",
  "number": "B2B-2026-000123",
  "status": "new",
  "message": "Заявка отправлена. Менеджер Stamm Brewing свяжется с вами."
}
```

### 4.3. Админские API

#### `GET /api/admin/dashboard`

Доступ: `admin`, `content_manager`, `catalog_manager`, `integration_manager`, `sales_manager` с ограничением виджетов по permissions.

Response содержит:

- `systemStatus`;
- `syncSummary`;
- `catalogStats`;
- `orderStats`;
- `recentErrors`.

#### `GET /api/admin/catalog/products`

Назначение: список товаров для админки.

Доступ: `catalog.read`.

Query:

```json
{
  "q": "ipa",
  "published": true,
  "availability": "available",
  "containerType": "keg",
  "folderId": "uuid",
  "missingImage": false,
  "outOfScope": false,
  "page": 1,
  "pageSize": 50
}
```

Response: таблица товаров с sync-полями, override-полями и статусами.

#### `GET /api/admin/catalog/products/{id}`

Назначение: получить полную карточку товара для редактирования.

Доступ: `catalog.read`.

Response:

- `syncData` read-only;
- `overrideData` editable;
- `images`;
- `seo`;
- `inventory`;
- `syncHistory`.

#### `PATCH /api/admin/catalog/products/{id}/overrides`

Назначение: обновить ручные витринные поля.

Доступ: `catalog.write_overrides`.

Request:

```json
{
  "publicName": "Stamm IPA, кег 30 л",
  "slug": "stamm-ipa-keg-30",
  "shortDescription": "...",
  "description": "...",
  "containerTypeOverride": "keg",
  "volumeLitersOverride": 30,
  "allowPreorder": false,
  "minOrderQuantity": 1,
  "orderStep": 1,
  "sortOrder": 100
}
```

Response: обновлённая карточка товара.

Side effects:

- запись `audit_events`;
- пересборка `business_catalog_items` для товара;
- обновление search index.

#### `PATCH /api/admin/catalog/products/{id}/publication`

Назначение: публикация/скрытие SKU.

Доступ: `catalog.publish`.

Request:

```json
{ "isPublished": true, "reason": "Готово описание и фото" }
```

Response: `productId`, `isPublished`, `updatedAt`.

#### `PUT /api/admin/catalog/products/{id}/images`

Назначение: заменить или переупорядочить галерею.

Доступ: `catalog.write_overrides`.

Request: массив `mediaAssetId`, `role`, `sortOrder`, `alt`.

#### `GET /api/admin/moysklad/settings`

Назначение: получить настройки интеграции без раскрытия токена.

Доступ: `moysklad.read`.

Response:

```json
{
  "apiBaseUrl": "https://api.moysklad.ru/api/remap/1.2",
  "tokenMasked": "••••••••1234",
  "sourceProductFolderHref": "https://api.moysklad.ru/api/remap/1.2/entity/productfolder/...",
  "includeChildFolders": true,
  "storeExternalIds": ["..."],
  "priceTypeExternalId": "...",
  "fullSyncIntervalMinutes": 360,
  "stockSyncIntervalMinutes": 120,
  "isEnabled": true,
  "lastSuccessAt": "2026-06-01T08:00:00Z"
}
```

#### `PATCH /api/admin/moysklad/settings`

Назначение: изменить настройки интеграции.

Доступ: `moysklad.write_settings`.

Request: настройки подключения, источника и расписания. Токен передаётся только при создании/замене.

Side effects:

- зашифровать новый токен;
- записать audit event;
- пометить, что после смены источника нужен full sync.

#### `POST /api/admin/moysklad/test-connection`

Назначение: проверить доступ к API МойСклад сервером.

Доступ: `moysklad.write_settings`.

Request: optional unsaved token/settings или использовать сохранённые.

Response:

```json
{ "ok": true, "accountName": "...", "checkedAt": "2026-06-01T09:00:00Z" }
```

#### `GET /api/admin/moysklad/folders`

Назначение: загрузить дерево папок из МойСклад в админке для выбора источника.

Доступ: `moysklad.read`.

Query: `refresh=true|false`.

Response: дерево папок с `name`, `externalId`, `href`, `parentHref`.

Важное ограничение: endpoint не используется публичным сайтом и не публикует товары.

#### `POST /api/admin/moysklad/sync-jobs`

Назначение: ручной запуск sync.

Доступ: `moysklad.run_sync`.

Request:

```json
{ "type": "manual_full", "reason": "После выбора новой папки" }
```

Response:

```json
{ "jobId": "uuid", "status": "queued", "createdAt": "2026-06-01T09:00:00Z" }
```

Ошибки:

- `409 SYNC_ALREADY_RUNNING`;
- `400 SETTINGS_INCOMPLETE`;
- `403 PERMISSION_DENIED`.

#### `GET /api/admin/moysklad/sync-jobs`

Назначение: список sync jobs.

Доступ: `moysklad.read`.

Query: `status`, `type`, `page`, `pageSize`, `dateFrom`, `dateTo`.

#### `GET /api/admin/moysklad/sync-jobs/{id}`

Назначение: детали job, статистика и логи.

Доступ: `moysklad.read`.

Response: job + logs + stats + sanitized errors.

#### `GET /api/admin/b2b/orders`

Назначение: список заявок.

Доступ: `orders.read`.

Query: `status`, `q`, `dateFrom`, `dateTo`, `managerId`, `page`, `pageSize`.

#### `GET /api/admin/b2b/orders/{id}`

Назначение: детали заявки.

Доступ: `orders.read`.

Response: контакты, позиции, snapshots, история, заметки.

#### `PATCH /api/admin/b2b/orders/{id}/status`

Назначение: изменить статус заявки.

Доступ: `orders.write_status`.

Request:

```json
{ "status": "in_review", "comment": "Взял в работу" }
```

Side effects: запись истории статуса и audit event.

#### Content API group

- `GET /api/admin/content/pages` — список страниц, `content.read`.
- `POST /api/admin/content/pages` — создать страницу, `content.write`.
- `PATCH /api/admin/content/pages/{id}` — обновить страницу, `content.write`.
- `POST /api/admin/content/pages/{id}/publish` — публикация, `content.publish`.
- `GET /api/admin/media` — медиа-библиотека, `content.read`.
- `POST /api/admin/media` — загрузка файла, `content.write`.

### 4.4. Интеграционные сервисы

Эти сервисы являются внутренними application services, а не публичными HTTP endpoint-ами.

#### `MoyskladClient.fetchProductFolders(params)`

Input:

```json
{ "sourceFolderHref": "...", "includeChildFolders": true, "updatedSince": null, "limit": 100, "offset": 0 }
```

Output: normalized folders array + pagination cursor.

Использует: МойСклад JSON API 1.2 folder/productfolder endpoints.

#### `MoyskladClient.fetchAssortment(params)`

Input:

```json
{ "folderHrefs": ["..."], "updatedSince": "2026-06-01T00:00:00Z", "limit": 100, "offset": 0 }
```

Output: normalized products/variants/prices.

Правило: не делать отдельный запрос на каждый товар, если можно получить коллекцию с фильтрами и пагинацией.

#### `MoyskladClient.fetchStockReport(params)`

Input:

```json
{ "storeExternalIds": ["..."], "assortmentHrefs": ["..."], "changedSince": null }
```

Output: stock rows normalized to `inventory_snapshots`.

Правило: получать агрегированный отчёт/коллекцию остатков, а не выполнять сотни запросов по SKU.

#### `CatalogSyncService.run(jobId)`

Input: `jobId`.

Steps:

1. lock;
2. read settings;
3. fetch folders;
4. fetch assortment;
5. fetch stock;
6. upsert sync tables;
7. rebuild read-model;
8. mark last-known-good on success;
9. unlock.

Output: job status and stats.

#### `CatalogReadModelBuilder.rebuild(scope)`

Input:

```json
{ "scope": "all" | "changed_products", "productIds": ["uuid"] }
```

Output: count of rebuilt `business_catalog_items`.

## 5. Sync-сценарий МойСклад JSON API 1.2

### 5.1. Хранение токена и настроек

- Токен хранится только на сервере.
- В БД хранится `encrypted_token_ref` или ciphertext, зашифрованный application key / KMS.
- В UI показывается только masked token.
- Любое чтение/замена токена пишется в audit без раскрытия значения.
- Для доступа к JSON API 1.2 используется Bearer token в серверном HTTP-клиенте.
- Настройки источника, складов, типа цены и расписания хранятся в `moysklad_sync_settings`.

### 5.2. Выбор папки-источника

1. Администратор открывает `/admin/moysklad`.
2. Нажимает «Загрузить дерево папок».
3. Backend сервером получает дерево папок из МойСклад и сохраняет временный локальный snapshot для UI.
4. Администратор выбирает папку.
5. В `moysklad_sync_settings` сохраняется `source_product_folder_href` и `include_child_folders`.
6. Система показывает предупреждение: «Для применения нового источника выполните full sync».

Важно: выбор папки не публикует товары сам по себе и не вызывает загрузку из публичного сайта.

### 5.3. Плановая синхронизация

Scheduler каждые N минут проверяет настройки:

- если sync disabled — ничего не делает;
- если уже есть running job — не создаёт новую;
- если пора full sync — создаёт `scheduled_full` job;
- если пора stock sync — создаёт `scheduled_stock` job;
- если последняя ошибка свежая — применяет backoff.

Worker забирает job из очереди и выполняет её вне web-request.

### 5.4. Ручная синхронизация

1. Пользователь с `moysklad.run_sync` нажимает «Синхронизировать сейчас».
2. Admin API проверяет права и полноту настроек.
3. Admin API проверяет distributed lock / running job.
4. Создаётся `manual_full` или `manual_stock` job со `started_by_user_id`.
5. UI получает `jobId` и показывает статус через polling `GET /api/admin/moysklad/sync-jobs/{id}`.
6. Worker выполняет job так же, как плановый sync.

### 5.5. Обновление локального каталога

Full sync:

1. Загрузить папки в scope.
2. Загрузить assortment/products по выбранным папкам.
3. Нормализовать товары, варианты, цены, атрибуты.
4. Upsert в `catalog_folders`, `products`, `product_variants`, `product_prices`.
5. Пометить товары, отсутствующие в текущем scope, как `out_of_scope`, не удаляя физически.
6. Загрузить/обновить остатки.
7. Пересчитать `inventory_levels`.
8. Пересобрать `business_catalog_items`.
9. На успехе обновить `last_success_at` и `last_known_good_job_id`.

Stock sync:

1. Использовать уже известный локальный список external href товаров в scope.
2. Получить агрегированные остатки по выбранным складам.
3. Записать `inventory_snapshots`.
4. Обновить `inventory_levels`.
5. Пересобрать read-model только для товаров с изменившимися остатками.

### 5.6. Обработка ошибок

| Ошибка | Действие |
| --- | --- |
| 401/403 auth | job failed, отключить автоповторы до проверки токена, показать alert в админке. |
| 429 rate limit | retry with exponential backoff, сохранить warning log. |
| 5xx МойСклад | retry ограниченное число раз, затем failed без изменения public read-model. |
| timeout/network | retry, затем failed, каталог продолжает работать на last-known-good. |
| invalid payload | partial_success, пропустить проблемную сущность, записать лог. |
| конфликт slug | не ломать sync, пометить товар как требующий ручного исправления. |

Ошибки не должны удалять или обнулять публичный каталог.

### 5.7. Как не делать сотни лишних API-запросов

- Загружать коллекции с пагинацией, а не каждый SKU отдельно.
- Фильтровать по выбранной папке и дочерним папкам.
- Использовать `updatedSince`/инкрементальную стратегию там, где API позволяет.
- Остатки получать отчётом/агрегированной выборкой по складам.
- Кэшировать дерево папок в админке и обновлять по кнопке или расписанию.
- Не импортировать изображения из МойСклад в первом этапе, если они не нужны для рабочей витрины.
- Ограничить ручной sync debounce-ом и lock-ом.
- Вести статистику количества запросов на job.

### 5.8. Как не ломать публичный каталог при неуспешном sync

- Sync пишет данные в транзакционных чанках и не публикует read-model до успешной нормализации критичных частей.
- Для полного sync можно использовать staging marker: новая версия read-model становится активной только после успешного завершения.
- При failed job `last_known_good_job_id` не меняется.
- Публичный API читает только активную read-model, а не промежуточные sync-таблицы.
- Ошибки sync видны в админке, но публичный пользователь видит стабильный каталог.
- Если last-known-good слишком старый, админка показывает warning; публичный интерфейс не должен раскрывать внутреннюю интеграционную ошибку.

### 5.9. Last-known-good state

Last-known-good state — это последний успешно опубликованный локальный снимок каталога.

Состав:

- `moysklad_sync_settings.last_known_good_job_id`;
- активные строки `business_catalog_items`;
- `inventory_levels` от последней успешной публикации;
- `lastCatalogSyncAt` для публичного meta;
- sync stats последней успешной job.

Поведение:

- публичный каталог всегда читает last-known-good;
- failed sync не очищает товары;
- partial_success может публиковаться только если критичные части валидны и политика это разрешает;
- админ может видеть разницу между last attempt и last-known-good.

## 6. Следующие этапы реализации

### Этап 3. Skeleton backend + DB schema

- Выбрать и зафиксировать стек приложения.
- Создать backend skeleton, конфигурацию окружений, healthcheck.
- Подключить PostgreSQL и миграции.
- Реализовать таблицы пользователей, ролей, аудита, каталога, sync jobs, заявок.
- Добавить seed permissions и базовые роли.
- Добавить базовые дизайн-токены в frontend/admin shell.

Критерий готовности: приложение стартует, миграции проходят, есть пустая админская оболочка и схема БД.

### Этап 4. Админка: auth, users, MoySklad settings

- Реализовать вход в админку.
- Реализовать RBAC middleware.
- Реализовать пользователей и роли.
- Реализовать экран настроек МойСклад.
- Реализовать сохранение токена и masked display.
- Реализовать test connection и выбор папки-источника.

Критерий готовности: интеграционный менеджер может безопасно настроить источник sync.

### Этап 5. Sync worker + локальный каталог

- Реализовать queue/scheduler/worker.
- Реализовать MoyskladClient.
- Реализовать manual_full и manual_stock jobs.
- Реализовать logs, retry/backoff, lock.
- Реализовать upsert каталога, остатков и read-model.
- Реализовать админский список товаров read-only.

Критерий готовности: каталог синхронизируется в локальную БД без участия публичного пользователя.

### Этап 6. Админка каталога

- Реализовать редактирование override-полей.
- Реализовать публикацию/скрытие.
- Реализовать медиа и галерею товара.
- Реализовать SEO-поля товара.
- Реализовать сортировку и бейджи.

Критерий готовности: менеджер каталога может подготовить B2B-витрину из sync-данных.

### Этап 7. Публичный раздел «Бизнес»

- Реализовать `/business/catalog`.
- Реализовать фильтры, поиск, сортировку и пагинацию.
- Реализовать карточку товара.
- Реализовать empty/error states.
- Подключить брендовые UI-токены Stamm Brewing.

Критерий готовности: партнёр видит стабильный локальный каталог и может выбирать позиции.

### Этап 8. B2B-заявки

- Реализовать корзину-заявку.
- Реализовать `POST /api/public/b2b/orders`.
- Реализовать snapshots позиций.
- Реализовать админский список и карточку заявки.
- Реализовать статусы и заметки менеджера.

Критерий готовности: партнёр отправляет заявку, менеджер обрабатывает её в админке.

### Этап 9. Контентные страницы сайта

- Реализовать CMS-раздел для страниц, блоков, баннеров и медиа.
- Реализовать «Пиво», «Посетить пивоварню», «История», «Контакты».
- Добавить sitemap, robots, OG.

Критерий готовности: сайт становится полноценным многостраничным ресурсом вокруг уже работающего B2B-ядра.

### Этап 10. Пост-MVP расширения

- Экспорт подтверждённых заявок в МойСклад.
- Личный кабинет партнёра.
- Персональные цены.
- Webhook-и МойСклад как ускоритель, но не замена scheduled sync.
- Расширенная аналитика B2B-заказов.
