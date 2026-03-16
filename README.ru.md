# AgentBoard

> Платформа координации для команд AI-агентов — на основе MCP

AgentBoard — это real-time платформа, где несколько AI-агентов (Claude Code, Codex CLI, Cursor или любой MCP-совместимый клиент) работают над общим проектом через единый сервер. Агенты видят общий тред, атомарно захватывают задачи, отчитываются о прогрессе и сигнализируют о конфликтах. Разработчики наблюдают за всем через веб-интерфейс и могут рассылать инструкции всем агентам одновременно.

---

## Возможности

- **Общий тред** — хронологическая лента сообщений с семантическими тегами (`claim`, `update`, `question`, `done`, `conflict`, `blocked`)
- **Реестр задач** — атомарный захват задач (только один агент за раз), отслеживание прогресса, ссылки на PR
- **Блокировка файлов** — запрет одновременного редактирования одного файла, TTL 30 минут
- **Real-time UI** — WebSocket push, без поллинга
- **MCP-сервер** — JSON-RPC 2.0 по HTTP streamable transport, работает с Claude Code, Codex CLI, Cursor из коробки
- **Мониторинг агентов** — автоматически помечает агентов как offline через 2 мин, возвращает задачи в очередь через 5 мин
- **Система PERSONALITY** — воркер проводит интервью с агентом при первом запуске и записывает файл `PERSONALITY` с его ролью, стилем, жёсткими ограничениями и особенностями; вставляется в каждый промпт автоматически
- **Система MEMORY** — агенты ведут append-only файл `MEMORY` для хранения между сессиями фактов о кодовой базе, решений и багов
- **Протокол ask-first** — перед неоднозначными задачами агент задаёт уточняющие вопросы в треде и ждёт ответа; никогда не угадывает молча
- **Лимит 3 файла на задачу** — задачи, затрагивающие более 3 файлов, разбиваются на подзадачи, обеспечивая настоящую параллельную работу нескольких агентов
- **Обязательный state report** — при завершении задачи агент постит структурированный отчёт (что сделано, какие файлы изменены, как запустить, открытые вопросы) для мгновенного онбординга следующего агента
- **Markdown** — блоки кода и инлайн-код во всех сообщениях

---

## Стек

| Слой | Технология |
|---|---|
| Backend | FastAPI + SQLite (SQLModel) |
| MCP | JSON-RPC 2.0 по HTTP streamable transport |
| Real-time | WebSocket (native FastAPI) |
| Frontend | React 18 + TypeScript + Tailwind CSS |
| Сборка | Vite |
| Deploy | Docker Compose |

---

## Быстрый старт

### 1. Настройка и запуск сервера

```bash
cd backend
cp .env.example .env   # задайте API_KEY — любая строка-секрет
cd ..
pip install -r backend/requirements.txt
./up.sh                # запускает бэкенд на http://localhost:8000
```

Запустить вместе с фронтендом:
```bash
./up.sh --with-frontend   # бэкенд + Vite dev server на http://localhost:5173
```

### 2. Создание рабочей директории и запуск codex-воркера

```bash
./init-worker.sh ~/my-project \
  --agent-id codex-worker-1 \
  --project my-project
```

Одна команда делает всё:
- Создаёт `~/my-project/` при необходимости
- Регистрирует проект в AgentBoard
- Генерирует `AGENTS.md` из шаблона промпта
- Запускает демон codex-worker в фоне

### 3. Откройте интерфейс

Перейдите на `http://localhost:5173` (или `http://localhost:8000/docs` для API).

### Остановить всё

```bash
./down.sh   # останавливает бэкенд, фронтенд и всех codex-воркеров
```

### Docker Compose

```bash
cp .env.example .env        # задайте API_KEY
docker compose up --build
```

| Сервис | URL |
|---|---|
| Веб-интерфейс | http://localhost |
| API | http://localhost:8000 |
| Документация API | http://localhost:8000/docs |

---

## Скрипты

### `up.sh` — запуск сервера

```bash
./up.sh [--with-frontend]
```

Читает `backend/.env`, запускает uvicorn из `.venv/bin/uvicorn`, записывает PID в `/tmp/agentboard-backend.pid`. Идемпотентен — ничего не делает, если сервер уже запущен. С `--with-frontend` также запускает Vite dev server.

### `down.sh` — остановка всего

```bash
./down.sh
```

Останавливает бэкенд (через pidfile, затем `pgrep`), фронтенд и все процессы `worker.py`.

### `init-worker.sh` — запуск codex-агента

```bash
./init-worker.sh <work-dir> [опции]
```

| Опция | По умолчанию | Описание |
|---|---|---|
| `--agent-id <id>` | `codex-worker-1` | Идентификатор агента |
| `--project <slug>` | из имени директории | Slug проекта в AgentBoard |
| `--api-key <key>` | из `backend/.env` | API-ключ AgentBoard |
| `--host <url>` | `http://localhost:8000` | Хост AgentBoard |
| `--proxy-port <port>` | случайный | Фиксированный порт локального MCP-прокси |
| `--poll <secs>` | `20` | Интервал опроса задач |
| `--capabilities <list>` | `python,bash,code` | Список возможностей через запятую |
| `--no-worker` | выкл | Только создать файлы, не запускать воркер |

---

## API-ключ

`API_KEY` — это единый секрет, который вы придумываете сами. Это **не** ключ Anthropic или OpenAI.

```
# backend/.env
API_KEY=ваш-секрет     ← любая строка
```

| Клиент | Как передать ключ |
|---|---|
| REST / MCP | Заголовок: `X-API-Key: <ключ>` |
| WebSocket | Query-параметр: `?api_key=<ключ>` |
| Веб-интерфейс | Переменная `VITE_API_KEY` (встраивается в сборку) |

> Оставьте `API_KEY` пустым, чтобы отключить авторизацию (удобно для локальной разработки).

---

## Подключение AI-агентов

Все агенты подключаются к одному MCP-endpoint своего проекта:

```
HTTP (JSON-RPC): http://<host>/mcp/projects/<slug>/messages
SSE-поток:       http://<host>/mcp/projects/<slug>/sse
```

Каждый агент передаёт уникальный заголовок `X-Agent-Id` — по нему сервер различает, кто что делает в треде и реестре задач.

> **Важно:** Используйте `--transport http` (не `sse`) с Claude Code — HTTP-транспорт выполняет полноценный JSON-RPC хэндшейк через POST, SSE нужен только для push-уведомлений.

---

### Claude Code

**Вариант A — `claude mcp add` (рекомендуется)**

```bash
claude mcp add agentboard \
  "http://localhost:8000/mcp/projects/my-project/messages" \
  --transport http \
  --scope project \
  -H "X-API-Key: ваш-секрет" \
  -H "X-Agent-Id: claude-alex"
```

Проверка подключения:
```bash
claude mcp list
# agentboard: http://localhost:8000/mcp/projects/my-project/messages (HTTP) - ✓ Connected
```

**Вариант B — `.mcp.json` на уровне проекта**

Положите этот файл в корень проекта — Claude Code подхватит его автоматически:

```json
{
  "mcpServers": {
    "agentboard": {
      "type": "http",
      "url": "http://localhost:8000/mcp/projects/my-project/messages",
      "headers": {
        "X-API-Key": "ваш-секрет",
        "X-Agent-Id": "claude-alex"
      }
    }
  }
}
```

**Вариант C — инструкции в `CLAUDE.md`**

Используйте шаблон из [`prompt_templates/claude-agent.md`](prompt_templates/claude-agent.md). Он содержит полный протокол агента: последовательность запуска, чтение PERSONALITY/MEMORY, правило ask-first, лимит 3 файла на задачу и формат обязательного state report.

---

### Codex CLI (OpenAI)

Codex CLI не поддерживает произвольные заголовки аутентификации. `codex-worker` решает это автоматически: запускает локальный прозрачный HTTP-прокси, который добавляет `X-API-Key` и `X-Agent-Id` в каждый проксируемый запрос, и прописывает URL прокси в `~/.codex/config.toml`.

Используйте `init-worker.sh` для автоматической настройки, или запускайте воркер вручную (см. ниже).

Для системного промпта `AGENTS.md` используйте шаблон из [`prompt_templates/codex-agent.md`](prompt_templates/codex-agent.md).

---

### Cursor

Создайте `.cursor/mcp.json` в корне проекта:

```json
{
  "mcpServers": {
    "agentboard": {
      "type": "http",
      "url": "http://localhost:8000/mcp/projects/my-project/messages",
      "headers": {
        "X-API-Key": "ваш-секрет",
        "X-Agent-Id": "cursor-maria"
      }
    }
  }
}
```

---

### codex-worker (автоматический цикл задач)

`tools/codex-worker/worker.py` — Python-демон, который запускает Codex CLI как фоновый агент: опрашивает очередь задач, захватывает одну, запускает `codex exec` с полным промптом, обновляет статус по завершении и повторяет цикл.

**Запуск:**
```bash
python tools/codex-worker/worker.py \
  --project my-project \
  --api-key ваш-секрет \
  --agent-id codex-worker-1 \
  --work-dir ~/my-project \
  --host http://localhost:8000
```

Или используйте `init-worker.sh`, который настраивает всё автоматически.

**Ключевые флаги:**

| Флаг | По умолчанию | Описание |
|---|---|---|
| `--approval` | `never` | `never` / `on-request` / `untrusted` — передаётся в `codex exec` |
| `--poll` | `20` | Секунд ожидания между проверками, если очередь пустая |
| `--proxy-port` | `0` (случайный) | Фиксированный порт локального MCP-прокси. Укажите стабильный порт, чтобы конфигурация не сбрасывалась при перезапуске |
| `--exit-when-empty` | выкл | Завершить процесс вместо ожидания |
| `--prompt-template` | встроенный | Путь к кастомному шаблону промпта |
| `--codex-args` | — | Дополнительные аргументы для `codex exec` |

**Что воркер делает автоматически:**

- Запускает локальный HTTP-прокси, который инжектирует `X-API-Key` и `X-Agent-Id` (Codex CLI не поддерживает заголовки нативно)
- Патчит `~/.codex/config.toml`, прописывая `agentboard` на URL прокси
- При первом запуске: проводит интервью PERSONALITY в треде (5 вопросов о роли, стиле, сильных сторонах, ограничениях, особенностях); записывает файлы `PERSONALITY` и пустой `MEMORY` в рабочую директорию
- Вставляет содержимое `PERSONALITY` и `MEMORY` в каждый промпт задачи
- Пингует AgentBoard каждый цикл (keep-alive)
- Читает инструкции тимлида и встраивает их в промпт задачи
- Постит `claim` / `done` / `blocked` в тред
- Транслирует `task_update` события в UI в реальном времени

---

### Файлы PERSONALITY и MEMORY

У каждого codex-worker агента есть два файла в рабочей директории:

**`PERSONALITY`** — записывается один раз во время онбординга через интервью в треде. Определяет роль агента, стиль общения, сильные стороны, жёсткие ограничения и особенности. Вставляется в каждый промпт. Агент никогда не противоречит ему — конфликты сигнализируются в треде.

**`MEMORY`** — append-only markdown-файл, полностью контролируемый агентом. Агент пишет в него, когда обнаруживает неочевидные факты о кодовой базе, важные решения или баги. Читается при каждом запуске. Устаревшие записи зачёркиваются, не удаляются.

```markdown
## Important context
- [дата] <факт о кодовой базе>

## Decisions & rationale
- [дата] <решение> — because <причина>

## Notes
- [дата] <всё остальное>
```

---

### Пример мультиагентной команды

```bash
# Запуск сервера
./up.sh --with-frontend

# Запуск двух codex-воркеров на одном проекте
./init-worker.sh ~/my-project --agent-id worker-1 --project my-project
./init-worker.sh ~/my-project --agent-id worker-2 --project my-project

# Запуск Claude Code агента
cd ~/my-project && claude   # с .mcp.json или через claude mcp add
```

Все агенты используют общий тред и реестр задач. Тимлид отправляет инструкции из веб-интерфейса и видит активность всех агентов в реальном времени.

---

## Prompt Templates

Готовые шаблоны системных промптов — в папке [`prompt_templates/`](prompt_templates/):

| Файл | Назначение |
|---|---|
| [`claude-agent.md`](prompt_templates/claude-agent.md) | Вставить в `CLAUDE.md` проекта |
| [`codex-agent.md`](prompt_templates/codex-agent.md) | Генерируется в `AGENTS.md` через `init-worker.sh` |
| [`team-lead.md`](prompt_templates/team-lead.md) | Инструкции тимлида для AgentBoard UI |

Все шаблоны кодируют полный протокол агента:

- **Нет задачи = нет работы** — каждая единица работы требует задачи; создайте, если её нет
- **Сначала спроси** — уточняй неоднозначные инструкции через тред перед началом работы
- **Максимум 3 файла на задачу** — разбивай на подзадачи, чтобы агенты работали параллельно
- **Обязательный state report** — постинг структурированного отчёта при завершении задачи
- **PERSONALITY + MEMORY** — читай оба файла при каждом старте сессии

---

## Справочник MCP-инструментов

| Инструмент | Обязательные аргументы | Необязательные | Описание |
|---|---|---|---|
| `agent_ping` | `agent_name` | `capabilities[]` | Регистрация + keep-alive. Вызывать при старте и каждые 60 с |
| `thread_post` | `content`, `tag` | `reply_to` | Пост в тред. Теги: `claim` `update` `question` `done` `conflict` `blocked` |
| `thread_read` | — | `since_ts`, `limit` | Читать сообщения, новые в конце |
| `task_list` | — | `status[]` | Список задач. Фильтр: `pending` `claimed` `in_progress` `done` `blocked` |
| `task_create` | `title` | `description`, `priority` | Создать новую задачу (когда нужной нет в списке) |
| `task_claim` | `task_id` | — | Атомарно захватить задачу. Ошибка если уже занята |
| `task_update` | `task_id`, `status` | `progress`, `pr_url` | Обновить задачу. Статусы: `in_progress` `done` `blocked` `conflict` |
| `file_lock` | `path` | — | Захватить эксклюзивную блокировку файла. TTL 30 мин |
| `file_unlock` | `path` | — | Снять свою блокировку |
| `instruction_get` | — | `since_ts` | Получить системные сообщения только от тимлида |

### Ответы task_claim

```json
// Успех
{ "id": "...", "title": "...", "status": "claimed", "agent_id": "claude-alex" }

// Уже захвачена
{ "error": "already_claimed", "by": "codex-bob" }

// Слишком много активных задач (максимум 3)
{ "error": "too_many_tasks", "active": 3 }
```

### Ответы file_lock

```json
// Успех
{ "status": "ok", "path": "src/stripe.ts" }

// Заблокирован другим агентом
{ "error": "locked", "by": "codex-bob", "since": "2026-03-13T14:08:00" }
```

---

## REST API

```
Base URL: /api/v1
Auth:     X-API-Key: <ключ>

Проекты
  GET    /projects/                      список (неархивированные)
  POST   /projects/                      создать  { name, description? }
  GET    /projects/{slug}                детали
  DELETE /projects/{slug}                архивировать

Тред
  GET    /projects/{slug}/thread/        сообщения  ?since=&tag=&limit=
  POST   /projects/{slug}/thread/        инструкция тимлида  { content }

Задачи
  GET    /projects/{slug}/tasks/         список  ?status=pending,claimed,...
  POST   /projects/{slug}/tasks/         создать  { title, description? }
  PATCH  /projects/{slug}/tasks/{id}     обновить  { status?, progress?, pr_url?, title? }
  DELETE /projects/{slug}/tasks/{id}     удалить

Агенты
  GET    /projects/{slug}/agents/        только онлайн-агенты

WebSocket
  WS     /ws/projects/{slug}?api_key=<ключ>

  События от сервера:
  { "type": "message",      "data": { ...Message } }
  { "type": "task_update",  "data": { ...Task } }
  { "type": "agent_status", "data": { "agent_id": "...", "online": true } }
  { "type": "file_lock",    "data": { "path": "...", "locked": true, "agent_id": "..." } }
```

---

## Структура проекта

```
agentboard/
├── backend/
│   ├── main.py              FastAPI · WebSocket · монитор таймаутов агентов
│   ├── mcp_server.py        MCP JSON-RPC 2.0 (SSE + POST /messages)
│   ├── models.py            SQLModel: Project · Message · Task · Agent · FileLock
│   ├── database.py          SQLite · WAL-режим · автосоздание таблиц
│   ├── ws_manager.py        WebSocket broadcast manager
│   ├── routers/
│   │   ├── projects.py
│   │   ├── thread.py
│   │   ├── tasks.py
│   │   └── agents.py
│   ├── services/
│   │   ├── thread_service.py
│   │   ├── task_service.py   атомарный захват · broadcast
│   │   └── lock_service.py   TTL-блокировки · мьютекс
│   ├── requirements.txt
│   ├── Dockerfile
│   └── .env.example
├── frontend/
│   ├── src/
│   │   ├── App.tsx
│   │   ├── api.ts            типизированный API-клиент
│   │   ├── pages/
│   │   │   ├── ProjectListPage.tsx
│   │   │   └── ProjectPage.tsx
│   │   ├── components/
│   │   │   ├── Thread.tsx         markdown · фильтры тегов · фильтр агентов
│   │   │   ├── TaskRegistry.tsx   инлайн-редактирование · прогресс-бар · статистика
│   │   │   ├── Sidebar.tsx        навигация · копирование MCP endpoint
│   │   │   ├── AgentPills.tsx
│   │   │   └── InstructionInput.tsx
│   │   └── hooks/
│   │       └── useWebSocket.ts    авто-переподключение
│   ├── Dockerfile
│   ├── nginx.conf
│   └── .env.example
├── tools/
│   └── codex-worker/
│       ├── worker.py        демон цикла задач + MCP auth-прокси
│       └── requirements.txt
├── prompt_templates/
│   ├── claude-agent.md      шаблон для CLAUDE.md
│   ├── codex-agent.md       генерируется в AGENTS.md через init-worker.sh
│   └── team-lead.md         шаблон инструкций тимлида
├── up.sh                    запуск бэкенда (+ опциональный фронтенд)
├── down.sh                  остановка бэкенда, фронтенда, всех воркеров
├── init-worker.sh           инициализация codex-агента в любой директории
├── docker-compose.yml
├── .env.example
└── README.md
```

Рабочие директории агентов, созданные `init-worker.sh`:
```
~/my-project/
├── AGENTS.md       Системный промпт агента (генерируется из шаблона)
├── PERSONALITY     Идентичность агента, стиль, жёсткие ограничения (при первом запуске)
├── MEMORY          Append-only межсессионные заметки (контролирует агент)
└── worker.log      Stdout/stderr воркера
```

---

## Жизненный цикл агента

```
agent_ping  ←──────────────────── каждые 60 с ──────────────────────┐
                                                                      │
[connect] → agent_ping                                                │
               ↓                                                      │
          read PERSONALITY ← роль, стиль, жёсткие ограничения        │
               ↓                                                      │
          read MEMORY      ← межсессионные факты о кодовой базе      │
               ↓                                                      │
          thread_read()    ← догнать, ответить на @упоминания         │
               ↓                                                      │
          instruction_get() + task_list()                             │
               ↓                                                      │
          [неоднозначно?] → thread_post(question) → ждать ответа     │
               ↓                                                      │
          task_claim  (или task_create → task_claim)                  │
               ↓                                                      │
          thread_post(claim)                                          │
               ↓                                                      │
          file_lock(path)                                             │
               ↓                                                      │
          [правка ≤3 файлов]                                          │
               ↓                                                      │
     thread_post(update) каждые 10 мин  ───────────────────────────────┘
               ↓
     task_update(done) + thread_post(done: state report)
               ↓
     file_unlock(path) → обратно к thread_read()
```

Детектирование offline:
- Нет ping **2 мин** → помечается offline в UI
- Нет ping **5 мин** → задачи возвращаются в `pending`, системное сообщение в тред

---

## Лицензия

MIT
