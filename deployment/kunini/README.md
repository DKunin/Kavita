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

Первого администратора нужно создать через веб-интерфейс после входа в Kunini
Auth. Для Kover каждый пользователь создаёт отдельный ключ в
`Settings -> Auth Keys / OPDS` и указывает сервер `https://books.kunini.ru`.

Native-аутентификация Kavita не отключена: Kunini Auth не является OIDC
провайдером, а отключение native auth без OIDC лишит веб и API штатной
идентификации пользователей. При переходе Kunini Auth на OIDC Kavita умеет
автопровижининг, синхронизацию ролей и отключение парольного входа без патча.
