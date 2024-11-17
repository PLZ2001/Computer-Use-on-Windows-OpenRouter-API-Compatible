# computer-use-demo-on-windows-using-openrouter-api

这是[Anthropic的Computer Use Demo](https://github.com/anthropics/anthropic-quickstarts/tree/main/computer-use-demo)的Windows兼容版本，经过修改可以在Windows系统上通过OpenRouter API原生运行，无需Docker容器和Anthropic官方API。

## ⚠️ 注意事项

计算机使用功能目前处于测试阶段。请注意，计算机使用功能带来的风险与标准API功能或聊天界面的风险有所不同。当使用计算机功能与互联网交互时，这些风险会更加显著。为了最大程度地降低风险，建议采取以下预防措施：

- 使用具有最小权限的专用虚拟机，以防止直接系统攻击或意外
- 避免向模型提供敏感数据（如账户登录信息），以防止信息泄露
- 将互联网访问限制在允许的域名列表内，以减少接触恶意内容的可能

在某些情况下，AI可能会执行在内容中发现的命令，即使这些命令与用户指令相冲突。例如，网页上的指令或图片中包含的指令可能会覆盖用户指令或导致AI出错。我们建议采取预防措施，将AI与敏感数据和操作隔离，以避免与提示注入相关的风险。

**实验性软件 - 使用风险自负**。本软件按"原样"提供，不提供任何形式的保证。作者和贡献者对使用本软件可能造成的任何损害或系统问题概不负责。

## 环境配置

1. 克隆此仓库
2. 创建虚拟环境：`conda create --name computer_use_demo_env python=3.11`
3. 激活虚拟环境：`conda activate computer_use_demo_env`
4. 安装依赖：`pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple`
5. 在`.env`文件中配置您的OpenRouter URL、OpenRouter API密钥和OpenRouter模型名称

## 运行应用程序
1. 点击`start.bat`启动应用程序
2. 启动应用程序后，浏览器自动打开 http://localhost:8501

## 已测试模型

1. 推荐：`anthropic/claude-3.5-sonnet:beta`
2. 能用，但不推荐：`anthropic/claude-3-5-haiku`、`openai/gpt-4o`、`openai/gpt-4o-mini`、`google/gemini-pro-1.5`、`google/gemini-flash-1.5`

## 使用说明

1. 启动应用程序后，在浏览器中打开 http://localhost:8501
2. 您将看到一个Streamlit界面，包含：
   - 底部的聊天输入框，用于输入您的请求
   - 显示对话历史的聊天记录区域
   - 显示AI桌面视图的屏幕捕获区域
3. 您可以要求AI执行各种计算机任务，例如：
   - 创建或编辑文件
   - 运行命令
   - 与应用程序交互
   - 分析屏幕内容
4. AI将：
   - 在执行操作前向您展示计划
   - 提供操作反馈
   - 截取屏幕以验证其操作

**重要提示：**
- 对修改系统文件或设置的命令要特别谨慎
- 确保敏感信息不在AI的视野范围内
- 监控应用程序的操作，确保符合您的意图

## 致谢

本项目基于[Anthropic的Computer Use Demo](https://github.com/anthropics/anthropic-quickstarts/tree/main/computer-use-demo)，参考[Cognitive Creators AI的Claude on Windows](https://github.com/Cognitive-Creators-AI/Claude-on-windows)和[jessy2027的Computer Use](https://github.com/jessy2027/computer-use)，在Windows系统上通过OpenRouter API原生运行，无需Docker容器和Anthropic官方API。原始实现的所有功劳归属于Anthropic。
