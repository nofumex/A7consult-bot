# А7 Консалт бот: Telegram + MAX

Мультиплатформенный бот юридической компании «А7 Консалт» на Python 3.11+. Telegram-версия работает на aiogram 3.x, MAX-версия вынесена в отдельный адаптер `app/adapters/max/`. Обе платформы используют одну базу данных, модели, сервисы заявок, рефералов, бонусов и чатов.

## Быстрый старт

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
python -m app.main
```

Для Linux/VPS:

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python -m app.main
```

## Запуск Telegram + MAX

Одна команда запускает все включённые платформы:

```bash
python -m app.main
```

Варианты:

- Только Telegram: заполните `BOT_TOKEN` или `TELEGRAM_BOT_TOKEN`, установите `RUN_MAX=false`.
- Только MAX: заполните `MAX_BOT_TOKEN`, установите `RUN_TELEGRAM=false`.
- Обе платформы: заполните Telegram token и `MAX_BOT_TOKEN`, оставьте `RUN_TELEGRAM=true`, `RUN_MAX=true`.

Если токен платформы не указан, соответствующий адаптер пропускается с записью в лог. Если нет ни одного токена, запуск остановится с понятной ошибкой.

## Настройки `.env`

- `BOT_TOKEN` — старое имя токена Telegram, сохраняется для обратной совместимости.
- `TELEGRAM_BOT_TOKEN` — новое имя токена Telegram; если задано, используется вместо `BOT_TOKEN`.
- `ADMIN_IDS`, `MANAGER_IDS` — старые Telegram ID админов и менеджеров.
- `TELEGRAM_ADMIN_IDS`, `TELEGRAM_MANAGER_IDS` — новые Telegram ID; если пустые, используются `ADMIN_IDS` и `MANAGER_IDS`.
- `MAX_BOT_TOKEN` — токен MAX-бота.
- `MAX_API_BASE_URL` — базовый URL MAX API. В `.env.example` указан `https://botapi.max.ru`; по актуальной документации MAX также используется `https://platform-api.max.ru`.
- `MAX_BOT_LINK` — ссылка на MAX-бота для реферальных ссылок.
- `MAX_ADMIN_IDS`, `MAX_MANAGER_IDS` — MAX user ID админов и менеджеров.
- `RUN_TELEGRAM`, `RUN_MAX` — включение/отключение адаптеров.
- `DATABASE_URL` — по умолчанию `sqlite+aiosqlite:///bot.db`.
- `DROP_PENDING_UPDATES` — очищать старые Telegram updates при старте.
- `GOOGLE_SHEETS_ID`, `GOOGLE_SHEETS_WORKSHEET`, `GOOGLE_SERVICE_ACCOUNT_FILE` — опциональная синхронизация заявок в Google Sheets через service account.
- `AMOCRM_BASE_URL`, `AMOCRM_ACCESS_TOKEN`, `AMOCRM_PIPELINE_ID` — односторонняя синхронизация заявок в amoCRM.
- `AMOCRM_STATUS_ID_NEW`, `AMOCRM_STATUS_ID_IN_PROGRESS`, `AMOCRM_STATUS_ID_CLOSED`, `AMOCRM_STATUS_ID_CANCELED` — соответствие статусов бота этапам amoCRM.
- `AGENT_CLIENT_NOTIFICATION_DELAY_SECONDS` — задержка уведомления менеджеров о новом клиенте от агента, по умолчанию `60`.

Секреты хранятся только в локальном `.env`. Не коммитьте `.env`, service account JSON и локальную базу `bot.db`: они исключены через `.gitignore`.

## MAX-адаптер

MAX-код изолирован в `app/adapters/max/`:

- `client.py` — HTTP-клиент на `aiohttp`, методы `/updates`, `/messages`, callback answer.
- `mapper.py` — преобразование MAX update в общий `IncomingEvent`.
- `keyboards.py` — inline-клавиатуры MAX.
- `states.py` — состояние MAX-сценариев в таблице `user_states`.
- `handlers.py` — сценарии MAX.
- `bot.py` — polling loop.

MAX Long Polling официально рекомендован для разработки и тестирования. Для production MAX рекомендует webhook; endpoint polling и отправки сообщений изолированы в `client.py`, чтобы их было легко заменить.

## База данных

При запуске автоматически создаются таблицы и безопасно добавляются поля:

- `users.platform`
- `users.platform_user_id`
- `users.phone`
- `leads.platform`
- `leads.relation_to_agent`
- `leads.agent_payout_phone`
- `leads.staff_notified_at`
- таблица `developer_user_mutes`
- таблица `user_states`

Старые Telegram-пользователи сохраняются. Для обратной совместимости поле `telegram_id` не удаляется и продолжает использоваться Telegram-кодом. MAX-пользователи дополнительно идентифицируются через `platform='max'` и `platform_user_id`.

## Команды

- `/start` — главное меню.
- `/profile` — профиль.
- `/consultation` — заявка на консультацию.
- `/ref_url` — реферальная ссылка или код.
- `/tutor` — связь с менеджером/куратором.
- `/new_client` — передать клиента.
- `/manager` — панель менеджера.
- `/admin` — админ-панель.
- `/endchat` — завершить чат.
- `/cancel` — отменить текущий сценарий ввода.
- `/help` — помощь.

## Роли

- `user` — обычный пользователь.
- `client` — клиент.
- `agent` — участник партнёрской программы.
- `manager` — менеджер платформы.
- `admin` — администратор платформы.

Права разделены по платформам. Telegram ID не дают права в MAX, и MAX ID не дают права в Telegram, если они отдельно не указаны в соответствующих переменных.

## Ограничения MAX-версии

- Если MAX-клиент пользователя не поддерживает конкретный тип кнопки, сценарии всё равно доступны через текст кнопок и команды.
- Видео из `COMPANY_VIDEO_URL` в MAX отправляется ссылкой, если вложение не поддерживается текущей конфигурацией клиента.
- Для production MAX рекомендует webhook вместо Long Polling; текущий адаптер использует polling, потому что проект запускается одной командой без внешнего HTTPS endpoint.

## Деплой

1. Установите Python 3.11+.
2. Установите зависимости: `pip install -r requirements.txt`.
3. Скопируйте `.env.example` в `.env` и заполните реальные токены и ID.
4. Проверьте запуск: `python -m app.main`.
5. Для постоянной работы используйте `systemd`, `supervisor` или Docker.

Пример `systemd`:

```ini
ExecStart=/path/to/project/.venv/bin/python -m app.main
WorkingDirectory=/path/to/project
Restart=always
```
