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

## Деплой

UI собирается локально поверх того же pinned runtime-образа Kavita. Тег образа
содержит сокращённый Git SHA, а полный SHA записывается в OCI label:

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
