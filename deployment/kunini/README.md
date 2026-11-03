# Развёртывание Kavita на Kunini

Production работает на `https://books.kunini.ru`. Контейнер слушает только
`127.0.0.1:5000`, конфигурация хранится в
`/var/apps/kavita/deployment/kunini/config`, а библиотека монтируется только для
чтения из `/mnt/data/plex/books`.

Веб-интерфейс входит через Kunini Auth по OIDC authorization-code/PKCE и
автоматически связывает пользователя по стабильному Kunini UUID. Kavita
сохраняет отдельного пользователя, права и прогресс чтения для каждого Kunini
аккаунта. Новые аккаунты получают доступ к `Books` и роли Login, Download и
Bookmark; `dkunin` сохраняет Admin. Парольный вход Kavita отключён. Машинный
`/api/*` не получает HTML-редирект и использует штатный персональный `x-api-key`
или bearer token Kavita.

## Обогащение описаний книг

`metadata_enricher.py` заполняет только пустые описания серий через штатный API
Kavita. По умолчанию команда работает в режиме аудита: получает данные из Open
Library, при необходимости предлагает атрибутированное вступление из Wikipedia
и формирует закрытый отчёт с исходным DTO, источником, лицензией и уверенностью
сопоставления. Для архивов комиксов можно дополнительно подключить Metron через
отдельный token-файл с режимом `0600`.

Open Library опрашивается пакетно по автору, ответы внешних провайдеров
кэшируются. Точное ISBN или единственное точное совпадение названия и автора
помечается как готовое к применению. Wikipedia, неоднозначные и нечёткие
совпадения всегда остаются на ручную проверку. Непроиндексированные CBR/CBZ
нужно сначала добавить в отдельную библиотеку комиксов Kavita.

```bash
state=/var/apps/kavita/metadata-enricher
install -d -m 700 "${state}" "${state}/cache" "${state}/backups"
python3 deployment/kunini/metadata_enricher.py audit \
  --api-key-file /var/apps/kavita/secrets/dkunin-kover-api-key \
  --cache-dir "${state}/cache" \
  --library-root /mnt/data/plex/books \
  --output "${state}/report.json"
sha256sum "${state}/report.json"
jq '{inventory, diskInventory: .diskInventory.counts, stats}' \
  "${state}/report.json"
```

Отчёт создаётся с режимом `0600`. Перед записью нужно просмотреть каждую запись
с `decision == "review"`; для принятой вручную записи установить
`approved: true`, затем заново вычислить SHA-256. Запись требует хеш именно этой
версии отчёта:

```bash
python3 deployment/kunini/metadata_enricher.py apply \
  --api-key-file /var/apps/kavita/secrets/dkunin-kover-api-key \
  --report "${state}/report.json" \
  --confirm-sha256 '<reviewed-report-sha256>' \
  --database-path /var/apps/kavita/deployment/kunini/config/kavita.db \
  --backup-dir "${state}/backups" \
  --journal "${state}/apply-journal.json"
```

Перед первой записью команда повторно читает все целевые DTO и полностью
отказывается от изменений при любом дрейфе. Затем она создаёт online-копию БД,
проверяет её через `PRAGMA quick_check`, меняет только `summary` и
`summaryLocked`, перечитывает каждую серию и атомарно дописывает журнал.

Откат также защищён хешем журнала и отдельной резервной копией текущей БД:

```bash
python3 deployment/kunini/metadata_enricher.py rollback \
  --api-key-file /var/apps/kavita/secrets/dkunin-kover-api-key \
  --journal "${state}/apply-journal.json" \
  --confirm-sha256 '<apply-journal-sha256>' \
  --database-path /var/apps/kavita/deployment/kunini/config/kavita.db \
  --backup-dir "${state}/backups"
```

### Ежедневное обогащение

`setup-metadata-enricher.sh` идемпотентно добавляет в пользовательский `crontab`
запуск каждый день в `03:17` по времени сервера:

```bash
./deployment/kunini/setup-metadata-enricher.sh
crontab -l | grep metadata-enricher-daily
```

Ежедневный сценарий сначала создаёт полный dry-run отчёт и автоматически
применяет только точный ISBN или единственное точное совпадение названия и
автора. Существующие описания он не меняет. Wikipedia, неоднозначные и нечёткие
совпадения остаются только в отчёте для ручной проверки. Любая ошибка внешнего
провайдера или изменение живого DTO блокирует весь этап записи.

Одновременные запуски исключены файловой блокировкой. Кэш обновляется раз в
сутки, поэтому недавно добавленная книга появится не позднее следующего
успешного обновления источника. Закрытые отчёты, журналы и проверенные резервные
копии хранятся в `/var/apps/kavita/metadata-enricher`; основной журнал — в
`daily.log`, а `latest-report.json` и `latest-journal.json` указывают на последние
артефакты. Все каталоги создаются с режимом `0700`, файлы — `0600`.

Google Books и недокументированные методы The Open Book Database намеренно не
используются: первый источник не подходит для постоянного копирования ответов,
а у второго не подтверждены публичный API и лицензия данных.

## Деплой

UI собирается локально из совместимого с runtime тега `v0.9.1.4`: поверх него
автоматически накладываются совместимый `ui-v0.9.1.4.patch` и изолированный
`ui-ink-v0.9.1.4.patch`. Это не даёт более новому
frontend вызвать API, которого ещё нет в pinned backend. Итоговый образ строится
поверх того же runtime Kavita. Тег образа содержит сокращённый Git SHA, а полный
SHA и версия UI-источника записываются в OCI labels:

```bash
./deployment/kunini/build-ui-image.sh
image="kavita-kunini:$(git rev-parse --short=12 HEAD)"
docker save "${image}" | gzip | ssh <production-host> 'gunzip | docker load'
```

На сервере используется sparse checkout репозитория. После загрузки образа:

```bash
cd /var/apps/kavita
git pull --ff-only
./deployment/kunini/deploy.sh
./deployment/kunini/setup-nginx.sh
```

Для отката можно временно запустить исходный pinned-образ, не меняя данные или
конфигурацию:

```bash
KAVITA_IMAGE='jvmilazz0/kavita:0.9.1@sha256:31181a32f0dda73cae68721867028a7253d57881b58bea5754cd9e578e75421a' \
  ./deployment/kunini/deploy.sh
```

Проверка production:

```bash
/var/apps/kavita/deployment/kunini/verify.sh
```

Первый администратор `dkunin` создан, библиотека `Books` направлена на `/books`,
OPDS включён. Сгенерированный пароль хранится только на сервере в
`/var/apps/kavita/secrets/admin-password`, отдельный ключ Kover — в
`/var/apps/kavita/secrets/dkunin-kover-api-key`; оба файла имеют режим `0600`.
В Kover нужно указать сервер `https://books.kunini.ru` и ключ из второго файла.
Kover использует штатный `/api/Plugin/authenticate`; access log для этого
маршрута отключён, поскольку контракт Kavita передаёт ключ в query string.

OIDC authority — `https://auth.kunini.ru/oidc`, client secret хранится только в
`/var/apps/kunini-auth/.env`, RSA signing key — в
`/var/apps/kunini-auth/data/oidc-signing-key.pem`; оба файла имеют режим `0600`.
API-key вход Kover остаётся независимым от браузерной OIDC-сессии.

## Интерфейс Ink

Ink реализован как `ui-ink-v0.9.1.4.patch` поверх совместимого тега
`v0.9.1.4` и базового Kunini UI-патча. Backend, схема данных, API, читатели и интеграции Kavita не
меняются. Основные токены находятся в `UI/Web/src/theme/themes/dark.scss`
внутри патча; библиотека, карточки, боковая навигация и панель деталей используют
те же переменные.

Подробности сопровождения, визуальные референсы и ограничения описаны в
[`docs/INK_UI.md`](docs/INK_UI.md).

При обновлении Kavita сначала нужно изменить `ui_source_ref`, применить патч к
новому тегу через `git apply --check`, собрать образ и проверить его до замены
production. Не следует переносить патч вслепую между несовместимыми API-версиями.
