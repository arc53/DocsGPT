<!-- Translated from README.md at commit c345cddb3ac33b44a077cfb5599f6adb2fc6604f by .github/workflows/readme-translations.yml. Fix wording here; change structure in README.md. -->
<h1 align="center">
  DocsGPT 🦖
</h1>

<p align="center">
  <strong>Open-source AI-агенты, работающие на основе ваших документов. Конфиденциально, с самостоятельным размещением, любая модель.</strong>
</p>

<p align="center">
  <a href="https://github.com/arc53/DocsGPT"><img src="https://img.shields.io/github/stars/arc53/docsgpt?style=social" alt="Звёзды GitHub"></a>
  <a href="https://github.com/arc53/DocsGPT/blob/main/LICENSE"><img src="https://img.shields.io/github/license/arc53/docsgpt" alt="Лицензия MIT"></a>
  <a href="https://www.bestpractices.dev/projects/9907"><img src="https://www.bestpractices.dev/projects/9907/badge" alt="Лучшие практики OpenSSF"></a>
  <a href="https://discord.gg/vN7YFfdMpj"><img src="https://img.shields.io/discord/1070046503302877216" alt="Discord"></a>
  <a href="https://x.com/docsgptai"><img src="https://img.shields.io/twitter/follow/docsgptai" alt="Подписаться в X"></a>
</p>

<p align="center">
  <a href="https://docs.docsgpt.cloud/quickstart">⚡️ Быстрый старт</a> •
  <a href="https://app.docsgpt.cloud/">☁️ Облако</a> •
  <a href="https://docs.docsgpt.cloud/">📖 Документация</a> •
  <a href="https://discord.gg/vN7YFfdMpj">💬 Discord</a> •
  <a href="https://blog.docsgpt.cloud/">🗞 Блог</a>
</p>

<!-- languages:start -->
<p align="center">
  <a href="../../README.md">English</a> |
  <a href="README.de.md">Deutsch</a> |
  <a href="README.es.md">Español</a> |
  <a href="README.ja.md">日本語</a> |
  <strong>Русский</strong> |
  <a href="README.zh-CN.md">简体中文</a> |
  <a href="README.zh-TW.md">繁體中文</a>
</p>
<!-- languages:end -->

> [!TIP]
> Разверните самостоятельно одной командой. В macOS и Linux:
> ```bash
> curl -fsSL https://docs.ac/install | bash
> ```
> В Windows (PowerShell): `irm https://docs.ac/install.ps1 | iex`

<p align="center">
  <a href="https://docs.docsgpt.cloud/">
    <img src="https://pub.arc53.com/docsgpt/readme-reel.webp?v=2" alt="DocsGPT за 30 секунд: загрузка документов, синхронизация с GitHub, ответы с источниками, глубокое исследование, визуальные workflow, инструменты, чат-виджет, OpenAI-совместимый API, MCP-сервер и самостоятельное размещение через docsgpt up" width="100%">
  </a>
</p>

> 🎃 **Hacktoberfest 2026:** футболки за значимый вклад весь октябрь. Подробнее в [HACKTOBERFEST.md](../../HACKTOBERFEST.md).

## Зачем нужен DocsGPT

DocsGPT превращает ваши документы, сайты и подключённые приложения в AI-агентов, которые отвечают с указанием источников. Создавайте агентов и
визуальные workflow, предоставляйте им инструменты и добавляйте их в свой продукт с помощью виджета, OpenAI-совместимого API или
MCP-сервера. Всё работает в вашей среде с выбранной вами моделью — облачной или локальной; все компоненты,
включая SSO, команды и квоты, лицензированы по MIT.

## Быстрый старт

Установщик выше проверяет наличие [Docker](https://docs.docker.com/engine/install/), устанавливает команду `docsgpt` и
запускает `docsgpt up`, которая спросит, кому нужен доступ к DocsGPT и какую модель использовать. Локальная установка откроется по адресу
[http://localhost:7091](http://localhost:7091).

Предпочитаете Docker Compose, pip, Kubernetes или изолированную от сети установку? См. [Выбор способа развёртывания](https://docs.docsgpt.cloud/Deploying).
Хотите просто попробовать? Используйте [DocsGPT Cloud](https://app.docsgpt.cloud/).

## Возможности

- 🤖 **Агенты и глубокое исследование:** агенты с собственными промптами, знаниями, инструментами и моделью, а также режим исследования для многошаговых ответов.
- 🔀 **Визуальные workflow:** связывайте агентов, условия, состояние и код в песочнице в drag-and-drop-конструкторе.
- 📚 **Знания откуда угодно:** PDF, файлы Office, веб-страницы, аудио и многое другое; синхронизация с Google Drive, SharePoint, Confluence, GitHub, S3 и другими источниками, с GraphRAG.
- 🔎 **Ответы с источниками:** каждый ответ содержит ссылки на документы, из которых он получен.
- 🛠️ **Инструменты и действия:** веб-поиск, любые REST API, MCP-серверы, артефакты и код в песочнице, а также shell на сопряжённых устройствах.
- 🧠 **Любые модели:** OpenAI, Anthropic, Google, Groq, OpenRouter или локальные модели через Ollama, vLLM и другие OpenAI-совместимые серверы.
- 🛡️ **Защитные механизмы:** выявляйте, редактируйте или блокируйте PII, секреты, prompt injection и ответы без опоры на источники.
- ⏰ **Расписания и webhook:** запускайте агентов по таймеру или из любой системы, способной отправить HTTP-запрос.

<table>
  <tr>
    <td width="50%" valign="top">
      <a href="https://docs.docsgpt.cloud/Agents/basics"><img src="../../docs/public/create-agent-poster.png" alt="Создание агента в DocsGPT: его знания, инструменты и промпт" width="100%"></a>
      <p align="center"><b>Агенты</b>: знания, инструменты и промпт — публикация в один клик</p>
    </td>
    <td width="50%" valign="top">
      <a href="https://docs.docsgpt.cloud/Agents/nodes"><img src="../../docs/public/workflow-builder-poster.png" alt="Конструктор workflow DocsGPT с узлом AI-агента, условием и двумя конечными узлами" width="100%"></a>
      <p align="center"><b>Workflow</b>: агенты и логика на одном полотне</p>
    </td>
  </tr>
  <tr>
    <td width="50%" valign="top">
      <a href="https://docs.docsgpt.cloud/Sources/Connectors"><img src="../../docs/public/connect-your-data-poster.png" alt="Подключение репозитория GitHub к DocsGPT и выбор ежедневной синхронизации" width="100%"></a>
      <p align="center"><b>Знания</b>: подключите сервис и поддерживайте данные в синхронизации</p>
    </td>
    <td width="50%" valign="top">
      <a href="https://docs.docsgpt.cloud/Extensions/chat-widget"><img src="../../docs/public/chat-widget-poster.png" alt="Чат-виджет DocsGPT на странице поддержки продукта, отвечающий на основе руководства" width="100%"></a>
      <p align="center"><b>Виджет</b>: ваш агент на любом сайте</p>
    </td>
  </tr>
</table>

Всё остальное — в [документации](https://docs.docsgpt.cloud/).

## Используйте где угодно

- **Веб-приложение:** чат, агенты, знания и настройки в браузере.
- **Виджеты чата и поиска:** добавьте агента на любой сайт с помощью тега script или [React-пакета](https://docs.docsgpt.cloud/Extensions/chat-widget).
- **OpenAI-совместимый API:** направьте любой OpenAI SDK на [`/v1`](https://docs.docsgpt.cloud/API/openai-compatible) или используйте [Agent API](https://docs.docsgpt.cloud/API/agent-api) и [webhook](https://docs.docsgpt.cloud/API/webhooks).
- **MCP-сервер:** позвольте Claude, Cursor или любому [MCP-клиенту](https://docs.docsgpt.cloud/API/mcp-server) искать по знаниям вашего агента.
- **Чат-приложения и терминал:** боты для [Discord](https://github.com/arc53/discord-docsgpt-extension), [Slack](https://github.com/arc53/slack-bot-docsgpt-extenstion) и [Telegram](https://github.com/arc53/tg-bot-docsgpt-extenstion), а также [DocsGPT CLI](https://github.com/arc53/DocsGPT-cli). Больше — в [интеграциях сообщества](https://docs.docsgpt.cloud/Extensions/community).

## Конфиденциальность по умолчанию

Всё работает внутри вашей среды: API, worker, Postgres, Redis, векторное хранилище и ваши файлы.
Выберите облачного провайдера моделей или запускайте модели и эмбеддинги локально, в том числе [в изолированной от сети среде](https://docs.docsgpt.cloud/Deploying/Air-Gapped).

```mermaid
flowchart LR
    Users["Веб-приложение, виджеты,<br/>клиенты API и MCP"] --> API
    subgraph Yours["Ваша среда"]
        API["DocsGPT API"] <--> Redis["Redis"]
        Redis <--> Worker["Worker<br/>загрузка и эмбеддинги"]
        API --> Data[(("Postgres, векторное хранилище<br/>и файлы"))]
        Worker --> Data
        Local["Локальные модели<br/>(необязательно)"]
    end
    API -.-> Local
    API -.-> Cloud["Облачный провайдер моделей<br/>(необязательно)"]
```

Прочитайте [руководство по архитектуре](https://docs.docsgpt.cloud/Concepts/Architecture) и
[контрольный список безопасности](https://docs.docsgpt.cloud/Deploying/Security), прежде чем открывать доступ к DocsGPT за пределами своего компьютера.

## Самостоятельное размещение

После установки одной командой стек управляется командой `docsgpt`:

```bash
docsgpt status     # версия, адрес и состояние
docsgpt logs       # просмотр журналов в реальном времени
docsgpt upgrade    # обновление и перезапуск на новой версии
docsgpt backup     # резервное копирование базы данных и загруженных данных
docsgpt down       # остановка (данные и настройки сохраняются)
```

Полный список команд — в [справочнике CLI](https://docs.docsgpt.cloud/Deploying/cli). Другие способы запуска:
[Docker Compose](https://docs.docsgpt.cloud/Deploying/Docker-Deploying),
[pip](https://docs.docsgpt.cloud/Deploying/Pip-Install),
[Kubernetes](https://docs.docsgpt.cloud/Deploying/Kubernetes-Deploying),
[в изолированной от сети среде](https://docs.docsgpt.cloud/Deploying/Air-Gapped) или
[из клона с помощью скрипта настройки](https://docs.docsgpt.cloud/Deploying/Docker-Deploying#using-the-source-checkout).
Чтобы работать над самим DocsGPT, см. [руководство по среде разработки](https://docs.docsgpt.cloud/Deploying/Development-Environment).

## Для команд

- **Единый вход:** подготовка пользователей через [OIDC и SCIM](https://docs.docsgpt.cloud/Deploying/OIDC-SSO).
- **Контроль доступа:** [роли, команды и совместный доступ](https://docs.docsgpt.cloud/Deploying/Access-Control) к агентам, знаниям и инструментам, с журналом аудита.
- **Квоты использования:** [лимиты на токены и расходы](https://docs.docsgpt.cloud/Deploying/Usage-Quotas) для каждого пользователя и команды.
- **Наблюдаемость:** аналитика, журналы и трассировки, а также [OpenTelemetry](https://docs.docsgpt.cloud/Deploying/Observability).

Развёртываете DocsGPT для своей компании? [Запросите демо](https://www.docsgpt.cloud/contact) или
[напишите нам](mailto:support@docsgpt.cloud?subject=DocsGPT%20support%2Fsolutions).

## Участие в разработке

Мы приветствуем сообщения об ошибках, вопросы и pull request. Начните с [CONTRIBUTING.md](../../CONTRIBUTING.md), ознакомьтесь с
[планом развития](https://github.com/orgs/arc53/projects/2) и [списком изменений](https://docs.docsgpt.cloud/changelog), а также напишите нам в
[Discord](https://discord.gg/vN7YFfdMpj). Пожалуйста, соблюдайте наш [Кодекс поведения](../../CODE_OF_CONDUCT.md).

<details>
<summary>Технологический стек и структура проекта</summary>

- **Backend:** Python, Flask и flask-restx за приложением Starlette ASGI (uvicorn/gunicorn), Celery с RedBeat, настройки Pydantic.
- **Данные:** PostgreSQL (SQLAlchemy, Alembic), Redis и FAISS, pgvector, Elasticsearch, Qdrant, Milvus или MongoDB для векторов.
- **Frontend:** React, Vite, Redux Toolkit, Tailwind CSS и React Flow.
- **Документация:** Next.js с Nextra.

Структура проекта:

- `docsgpt/`: backend и команда `docsgpt` (API, агенты, инструменты, поиск, парсеры, worker).
- `frontend/`: веб-интерфейс.
- `extensions/`: мост Chatwoot и React-виджет (публикуется в npm как `docsgpt`).
- `deployment/`: файлы Docker Compose, манифесты Kubernetes, скрипты установки и образ песочницы.
- `docs/`: сайт документации на [docs.docsgpt.cloud](https://docs.docsgpt.cloud).
- `tests/` и `scripts/`: тесты, а также скрипты обслуживания и миграции.

</details>

## Лицензия

DocsGPT распространяется по [лицензии MIT](../../LICENSE).

## При поддержке

<p>
  <a href="https://www.digitalocean.com/?utm_medium=opensource&utm_source=DocsGPT">
    <img src="https://opensource.nyc3.cdn.digitaloceanspaces.com/attribution/assets/SVG/DO_Logo_horizontal_blue.svg" width="201px" alt="DigitalOcean">
  </a>
</p>
<p>
  <a href="https://get.neon.com/docsgpt">
    <img width="201" alt="Neon" src="https://github.com/user-attachments/assets/7d9813b7-0e6d-403f-b5af-68af066b326f" />
  </a>
</p>
