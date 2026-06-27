<h1 align="center">
  DocsGPT  🦖
</h1>

<p align="center">
  <strong>专为智能体、助手和企业搜索打造的私有AI平台</strong>
</p>

<p align="left">
  <strong><a href="https://www.docsgpt.cloud/">DocsGPT</a></strong> 是一个用于构建智能体和助手的开源AI平台。功能包括智能体构建器、深度研究工具、文档分析（PDF、Office、网络内容）、多模型支持（选择您的供应商或本地运行），以及用于连接可操作工具和集成的智能体的丰富API。可部署在任何地方，并拥有完整的隐私控制权。
</p>

<div align="center">
  
  <a href="https://github.com/arc53/DocsGPT"><img src="https://img.shields.io/github/stars/arc53/docsgpt?style=social" alt="指向主GitHub的链接，显示星标数"></a>
  <a href="https://github.com/arc53/DocsGPT"><img src="https://img.shields.io/github/forks/arc53/docsgpt?style=social" alt="指向主GitHub的链接，显示分支数"></a>
  <a href="https://github.com/arc53/DocsGPT/blob/main/LICENSE"><img src="https://img.shields.io/github/license/arc53/docsgpt" alt="指向许可证文件的链接"></a>
  <a href="https://www.bestpractices.dev/projects/9907"><img src="https://www.bestpractices.dev/projects/9907/badge" alt="最佳实践徽章"></a>
  <a href="https://discord.gg/vN7YFfdMpj"><img src="https://img.shields.io/discord/1070046503302877216" alt="指向discord的链接"></a>
  <a href="https://x.com/docsgptai"><img src="https://img.shields.io/twitter/follow/docsgptai" alt="X (前身为 Twitter) 关注"></a>

<br>
<a href="https://docs.docsgpt.cloud/quickstart">⚡️ 快速开始</a> • <a href="https://app.docsgpt.cloud/">☁️ 云版本</a> • <a href="https://discord.gg/vN7YFfdMpj">💬 Discord</a>
<br>
<a href="https://docs.docsgpt.cloud/">📖 文档</a> • <a href="https://github.com/arc53/DocsGPT/blob/main/CONTRIBUTING.md">👫 参与贡献</a> • <a href="https://blog.docsgpt.cloud/">🗞 博客</a>
<br>

</div>

<div align="center">
  <br>
<img src="https://d3dg1063dc54p9.cloudfront.net/videos/demov7.gif" alt="docs-gpt示例视频" width="800" height="450">
</div>

<h3 align="left">
  <strong>核心特性：</strong>
</h3>
<ul align="left">
    <li><strong>🗂️ 广泛的格式支持：</strong> 可读取 PDF、DOCX、CSV、XLSX、EPUB、MD、RST、HTML、MDX、JSON、PPTX 和图像。</li>
    <li><strong>🌐 网络与数据集成：</strong> 可从 URL、站点地图、Reddit、GitHub 和网络爬虫获取内容。</li>
    <li><strong>✅ 可靠的答案：</strong> 获得准确、无幻觉的响应，并在简洁的UI中查看来源引用。</li>
    <li><strong>🔑 简化的API密钥管理：</strong> 生成与您的设置、文档和模型关联的密钥，简化聊天机器人和集成设置。</li>
    <li><strong>🔗 可操作的工具：</strong> 连接到 API、工具和其他服务，以实现LLM操作。</li>
    <li><strong>🧩 预构建集成：</strong> 使用现成的 HTML/React 聊天组件、搜索工具、Discord/Telegram 机器人等。</li>
    <li><strong>🔌 灵活的部署：</strong> 兼容主流 LLM（OpenAI、Google、Anthropic）和本地模型（Ollama、llama_cpp）。</li>
    <li><strong>🏢 安全与可扩展：</strong> 支持 Kubernetes，可私有化安全运行，专为企业级可靠性设计。</li>
</ul>

## 路线图
- [x] 为 MCP 添加 OAuth 2.0 认证（2025年9月）
- [x] 深度智能体（2025年10月）
- [ ] 提示词模板化（2025年10月）
- [ ] 智能体调度（2025年12月）

您可以在此处找到我们的完整[路线图](https://github.com/orgs/arc53/projects/2)。请不要犹豫贡献代码或创建问题，这将帮助我们改进 DocsGPT！

### 生产支持 / 企业帮助：

我们非常乐意为您将 DocsGPT 部署到生产环境时提供个性化的帮助。

[预约演示 :wave:](https://www.docsgpt.cloud/contact)⁠

[发送邮件 :email:](mailto:support@docsgpt.cloud?subject=DocsGPT%20support%2Fsolutions)

## 加入灯塔计划 🌟

召集所有开发者和生成式AI创新者！**DocsGPT灯塔计划** 连接正在实际场景中积极部署或扩展 DocsGPT 的技术领导者。直接与我们的团队合作，共同规划路线图，获取优先支持，并利用独家社区洞察构建企业级解决方案。

[了解更多并申请 →](https://docs.google.com/forms/d/1KAADiJinUJ8EMQyfTXUIGyFbqINNClNR3jBNWq7DgTE)

## 快速开始

> **注意：** 请确保已安装 [Docker](https://docs.docker.com/engine/install/)

我们的文档中提供了更详细的[快速开始指南](https://docs.docsgpt.cloud/quickstart)

1. **克隆仓库：**

   ```bash
   git clone https://github.com/arc53/DocsGPT.git
   cd DocsGPT
   ```

**适用于 macOS 和 Linux：**

2. **运行安装脚本：**

   ```bash
   ./setup.sh
   ```

**适用于 Windows：**

2. **运行 PowerShell 安装脚本：**

   ```powershell
   PowerShell -ExecutionPolicy Bypass -File .\setup.ps1
   ```

两个脚本都将引导您完成 DocsGPT 的设置。提供五个选项：使用公共 API、本地运行、连接到本地推理引擎、使用云 API 提供商，或本地构建 Docker 镜像。脚本将根据您的选择自动配置 `.env` 文件，并处理必要的下载和安装。

**在浏览器中访问 http://localhost:5173/**

要停止 DocsGPT，请在 `DocsGPT` 目录下打开终端并运行：

```bash
docker compose -f deployment/docker-compose.yaml down
```

（或使用运行安装脚本后显示的特定 `docker compose down` 命令）。

> **注意：** 有关开发环境设置的说明，请参阅[开发环境指南](https://docs.docsgpt.cloud/Deploying/Development-Environment)。

## 贡献指南

请参阅 [CONTRIBUTING.md](CONTRIBUTING.md) 文件了解如何参与贡献。我们欢迎提交问题、疑问和拉取请求。

## 架构

![架构图](https://github.com/user-attachments/assets/fc6a7841-ddfc-45e6-b5a0-d05fe648cbe2)

## 项目结构

- Application - Flask 应用（主应用程序）。

- Extensions - 扩展，如 React 组件或 Discord 机器人。

- Frontend - 前端使用 <a href="https://vitejs.dev/">Vite</a> 和 <a href="https://react.dev/">React</a>。

- Scripts - 杂项脚本。

## 行为准则

我们作为成员、贡献者和领导者，承诺让每个人在我们的社区中参与都免受骚扰，无论其年龄、体型、可见或不可见的残疾、种族、性征、性别认同与表达、经验水平、教育程度、社会经济地位、国籍、外貌、种族、宗教或性取向如何。请参阅 [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md) 文件了解更多关于贡献的信息。

## 衷心感谢我们的贡献者们⚡

<a href="https://github.com/arc53/DocsGPT/graphs/contributors" alt="查看贡献者">
  <img src="https://contrib.rocks/image?repo=arc53/DocsGPT" alt="贡献者们" />
</a>

## 许可证

源代码采用 [MIT](https://opensource.org/license/mit/) 许可证，如 [LICENSE](LICENSE) 文件所述。

## 本项目由以下机构支持：

<p>
  <a href="https://www.digitalocean.com/?utm_medium=opensource&utm_source=DocsGPT">
    <img src="https://opensource.nyc3.cdn.digitaloceanspaces.com/attribution/assets/SVG/DO_Logo_horizontal_blue.svg" width="201px">
  </a>
</p>
<p>
  <a href="https://console.neon.tech/app/?promo=docsgpt">
    <img width="201" alt="Neon Logo" src="https://github.com/user-attachments/assets/42c8aa45-7b99-4f56-85d6-e0f07dddcc3b" />
  </a>
</p>