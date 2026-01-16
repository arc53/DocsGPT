<h1 align="center">
  DocsGPT  🦖
</h1>

<p align="center">
  <strong>面向智能代理、助手和企业搜索的私有 AI 平台</strong>
</p>

<p align="center">
  <a href="./README.md">English</a> | <a href="./README.zh-CN.md">简体中文</a>
</p>

<p align="left">
  <strong><a href="https://www.docsgpt.cloud/">DocsGPT</a></strong> 是一个开源 AI 平台，用于构建智能代理和助手。功能包括 Agent Builder、深度研究工具、文档分析（PDF、Office、网页内容）、多模型支持（选择您的提供商或本地运行），以及为代理提供可操作工具和集成的丰富 API 连接能力。可在任何地方部署，完全掌控隐私。
</p>

<div align="center">

  <a href="https://github.com/arc53/DocsGPT">![link to main GitHub showing Stars number](https://img.shields.io/github/stars/arc53/docsgpt?style=social)</a>
  <a href="https://github.com/arc53/DocsGPT">![link to main GitHub showing Forks number](https://img.shields.io/github/forks/arc53/docsgpt?style=social)</a>
  <a href="https://github.com/arc53/DocsGPT/blob/main/LICENSE">![link to license file](https://img.shields.io/github/license/arc53/docsgpt)</a>
  <a href="https://www.bestpractices.dev/projects/9907"><img src="https://www.bestpractices.dev/projects/9907/badge"></a>
  <a href="https://discord.gg/vN7YFfdMpj">![link to discord](https://img.shields.io/discord/1070046503302877216)</a>
  <a href="https://x.com/docsgptai">![X (formerly Twitter) URL](https://img.shields.io/twitter/follow/docsgptai)</a>

<a href="https://docs.docsgpt.cloud/quickstart">⚡️ 快速开始</a> • <a href="https://app.docsgpt.cloud/">☁️ 云端版本</a> • <a href="https://discord.gg/vN7YFfdMpj">💬 Discord</a>
<br>
<a href="https://docs.docsgpt.cloud/">📖 文档</a> • <a href="https://github.com/arc53/DocsGPT/blob/main/CONTRIBUTING.md">👫 贡献指南</a> • <a href="https://blog.docsgpt.cloud/">🗞 博客</a>
<br>

</div>


<div align="center">
  <br>
<img src="https://d3dg1063dc54p9.cloudfront.net/videos/demov7.gif" alt="video-example-of-docs-gpt" width="800" height="450">
</div>
<h3 align="left">
  <strong>主要特性：</strong>
</h3>
<ul align="left">
    <li><strong>🗂️ 广泛的格式支持：</strong> 读取 PDF、DOCX、CSV、XLSX、EPUB、MD、RST、HTML、MDX、JSON、PPTX 和图片。</li>
    <li><strong>🌐 网页与数据集成：</strong> 从 URL、站点地图、Reddit、GitHub 和网络爬虫获取内容。</li>
    <li><strong>✅ 可靠的回答：</strong> 获得准确、无幻觉的响应，在简洁的 UI 中查看来源引用。</li>
    <li><strong>🔑 简化的 API 密钥管理：</strong> 生成与您的设置、文档和模型关联的密钥，简化聊天机器人和集成设置。</li>
    <li><strong>🔗 可操作的工具：</strong> 连接 API、工具和其他服务，使 LLM 能够执行操作。</li>
    <li><strong>🧩 预置集成：</strong> 使用现成的 HTML/React 聊天小部件、搜索工具、Discord/Telegram 机器人等。</li>
    <li><strong>🔌 灵活部署：</strong> 支持主流 LLM（OpenAI、Google、Anthropic）和本地模型（Ollama、llama_cpp）。</li>
    <li><strong>🏢 安全可扩展：</strong> 支持 Kubernetes，可私密安全运行，专为企业级可靠性设计。</li>
</ul>

## 路线图
- [x] 为 MCP 添加 OAuth 2.0 认证（2025年9月）
- [x] 深度代理（2025年10月）
- [x] Prompt 模板（2025年10月）
- [x] 完整的 API 工具支持（2025年12月）
- [ ] Agent 调度（2026年1月）

完整路线图请查看[这里](https://github.com/orgs/arc53/projects/2)。欢迎提交 issue 或贡献代码，这将帮助我们改进 DocsGPT！

### 企业生产支持/帮助：

我们很乐意在您将 DocsGPT 部署到生产环境时提供个性化帮助。

[获取演示 :wave:](https://www.docsgpt.cloud/contact)

[发送邮件 :email:](mailto:support@docsgpt.cloud?subject=DocsGPT%20support%2Fsolutions)

## 加入 Lighthouse 计划 🌟

召集所有开发者和 GenAI 创新者！**DocsGPT Lighthouse 计划**连接那些正在实际场景中积极部署或扩展 DocsGPT 的技术领导者。与我们的团队直接合作，参与制定路线图，获得优先支持，并通过独家社区洞察构建企业级解决方案。

[了解更多并申请 →](https://docs.google.com/forms/d/1KAADiJinUJ8EMQyfTXUIGyFbqINNClNR3jBNWq7DgTE)

## 快速开始

> [!Note]
> 请确保已安装 [Docker](https://docs.docker.com/engine/install/)

更详细的[快速开始](https://docs.docsgpt.cloud/quickstart)可在我们的文档中查看

1. **克隆仓库：**

   ```bash
   git clone https://github.com/arc53/DocsGPT.git
   cd DocsGPT
   ```

**对于 macOS 和 Linux：**

2. **运行安装脚本：**

   ```bash
   ./setup.sh
   ```

**对于 Windows：**

2. **运行 PowerShell 安装脚本：**

   ```powershell
   PowerShell -ExecutionPolicy Bypass -File .\setup.ps1
   ```

任一脚本都会引导您完成 DocsGPT 的设置。有五个选项可选：使用公共 API、本地运行、连接本地推理引擎、使用云端 API 提供商，或在本地构建 Docker 镜像。脚本会根据您选择的选项自动配置 `.env` 文件并处理必要的下载和安装。

**访问 http://localhost:5173/**

要停止 DocsGPT，在 `DocsGPT` 目录打开终端并运行：

```bash
docker compose -f deployment/docker-compose.yaml down
```

（或使用运行安装脚本后显示的特定 `docker compose down` 命令）。

> [!Note]
> 开发环境设置说明请参阅[开发环境指南](https://docs.docsgpt.cloud/Deploying/Development-Environment)。

## 贡献

请参阅 [CONTRIBUTING.md](CONTRIBUTING.md) 文件了解如何参与贡献。我们欢迎 issue、问题和 pull request。

## 架构

![Architecture chart](https://github.com/user-attachments/assets/fc6a7841-ddfc-45e6-b5a0-d05fe648cbe2)

## 项目结构

- Application - Flask 应用（主应用程序）。

- Extensions - 扩展，如 React 小部件或 Discord 机器人。

- Frontend - 前端使用 <a href="https://vitejs.dev/">Vite</a> 和 <a href="https://react.dev/">React</a>。

- Scripts - 杂项脚本。

## 行为准则

作为成员、贡献者和领导者，我们承诺让每个人参与我们的社区时都不会受到骚扰，无论年龄、体型、可见或不可见的残疾、种族、性别特征、性别认同和表达、经验水平、教育程度、社会经济地位、国籍、个人外表、种族、宗教或性认同和取向。更多信息请参阅 [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md) 文件。

## 感谢所有贡献者 ⚡

<a href="https://github.com/arc53/DocsGPT/graphs/contributors" alt="View Contributors">
  <img src="https://contrib.rocks/image?repo=arc53/DocsGPT" alt="Contributors" />
</a>

## 许可证

源代码采用 [MIT](https://opensource.org/license/mit/) 许可证，详见 [LICENSE](LICENSE) 文件。

## 本项目由以下机构支持：

<p>
  <a href="https://www.digitalocean.com/?utm_medium=opensource&utm_source=DocsGPT">
    <img src="https://opensource.nyc3.cdn.digitaloceanspaces.com/attribution/assets/SVG/DO_Logo_horizontal_blue.svg" width="201px">
  </a>
</p>
<p>
  <a href="https://console.neon.tech/app/?promo=docsgpt">
    <img width="201" alt="color" src="https://github.com/user-attachments/assets/42c8aa45-7b99-4f56-85d6-e0f07dddcc3b" />
  </a>
</p>

