# Развёртывание Kavita на Kunini

Production работает на `https://books.kunini.ru`. Контейнер слушает только
`127.0.0.1:5000`, конфигурация хранится в
`/var/apps/kavita/deployment/kunini/config`, а библиотека монтируется только для
чтения из `/mnt/data/plex/books`.

Веб-интерфейс закрыт через Kunini Auth. Kavita сохраняет собственных
пользователей и права: это необходимо для раздельного прогресса чтения,
библиотек и персональных API-ключей. Парольный вход и первичная регистрация
дополнительно требуют активную сессию Kunini Auth. Машинный `/api/*` не получает
HTML-редирект и использует штатный `x-api-key` или bearer token Kavita.

## Деплой

На сервере используется sparse checkout репозитория:

```bash
cd /var/apps/kavita
git pull --ff-only
./deployment/kunini/deploy.sh
./deployment/kunini/setup-nginx.sh
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

Native-аутентификация Kavita не отключена: Kunini Auth не является OIDC
провайдером, а отключение native auth без OIDC лишит веб и API штатной
идентификации пользователей. При переходе Kunini Auth на OIDC Kavita умеет
автопровижининг, синхронизацию ролей и отключение парольного входа без патча.
