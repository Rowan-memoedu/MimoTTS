# Python 离线单元测试

## 从干净检出运行

需要 Python 3.10 或更高版本（见 `pyproject.toml`）。现有测试只使用 Python 标准库和仓库源码，无需 pip 安装、下载依赖或安装本项目，也不需要 API key、Anki、SpeechKit、本机私人配置或 ffmpeg/ffprobe。

在检出仓库的根目录打开终端（该目录包含 `src` 和 `tests`）。源码使用 src 布局，因此必须将本次检出的 `src` 绝对路径设为 `PYTHONPATH`，避免导入本机已安装的版本。

PowerShell：

```powershell
$env:PYTHONPATH = Join-Path (Get-Location).Path 'src'
python -m unittest discover -s tests -v
```

POSIX shell：

```sh
PYTHONPATH="$PWD/src" python3 -m unittest discover -s tests -v
```

`python` / `python3` 应指向满足版本要求的解释器，也可以替换为其绝对路径。命令非交互执行；当前共有 10 项测试，通过时末尾显示 `Ran 10 tests` 和 `OK`，退出码为 0。若出现 `No module named 'mimo_tts'`，检查当前目录及 `PYTHONPATH`。

测试用 `tempfile.TemporaryDirectory` 创建并清理合成数据、缓存及输出文件；默认使用系统临时目录。如需限定输出位置，可在启动 Python 前将 `TMPDIR`（或 Windows 的 `TEMP`、`TMP`）设为已存在且可写的专用临时目录。可设置 `PYTHONDONTWRITEBYTECODE=1` 避免生成 `__pycache__`。

## 现有覆盖范围

以下依据 [test_client.py](../tests/test_client.py)（8 项）与 [test_speechkit_bridge.py](../tests/test_speechkit_bridge.py)（2 项），不是完整覆盖率报告。

| 测试范围 | 实际断言 |
| --- | --- |
| 文本分段 | 中英文、括号与大量空白拼接后保持原文，分段不全为空白 |
| VoiceDesign 请求 | 原文位于最后的 assistant 消息，关闭文本优化，不携带预设 voice 字段 |
| 克隆输入大小 | 拒绝 7,500,001 字节的临时参考文件 |
| SSE 与音频完成状态 | 解析内存中的注释、data 和 `[DONE]`；拒绝 `finish_reason=length` 的不完整音频 |
| 缓存与输出保护 | 相同文本命中缓存，不同文本重新调用模拟提供者，拒绝覆盖已有输出；未验证切换模型或提供者时的缓存隔离 |
| 参数校验 | `speed=0` 抛错且不调用网络入口 |
| Anki 文本与音色映射 | English 模式去除汉字，bilingual 保留原文；旧音色回退到 Mia，`mimo-Dean` 映射为 Dean |
| SpeechKit 失败保护 | 合成失败后保留已有音频与时间戳文件；拒绝 `voice_cloning=True`，且不调用合成函数 |

## Mock 与外部边界

- 不完整音频测试将 `mimo_tts.client._open` 替换为内存 `BytesIO` SSE 响应；无效语速测试 mock 同一入口并断言未调用。因此不会执行真实 HTTP 请求或其中的凭据读取。
- 缓存测试将 `client._pcm` 替换为固定 PCM 字节及指标，并把 `client.CACHE` 指向临时目录。WAV、缓存和 JSON 清单的本地读写实际执行，但不访问默认的 `D:\Caches\MimoTTS`。
- 两项桥接测试 mock `mimo_tts.speechkit_bridge.synthesize`：一项模拟 `MimoError`，另一项确认克隆配置在合成前被拒绝。两条路径均在 ffprobe 调用前结束；ffprobe 本身没有被 mock，也没有被执行。
- Anki 测试只调用 `AnkiBackend.spoken` 静态方法和 `selected_voice`，不实例化后端、不启动 Anki、不访问牌组、用户资料或真实学习账户。桥接测试直接传入内存字典，不加载 SpeechKit 配置。
- 参考文件、PCM、旧音频和时间戳均由测试构造，不使用私人录音。当前测试路径不调用真实 TTS API 或生产服务，也不读取 `MIMO_API_KEY` 或 Windows 用户环境注册表。mock 是各用例的局部替换，并非全局网络隔离机制。

这些测试不验证真实服务的认证、HTTP 重试、音质、真实克隆效果、MP3 转码、播放、桥接成功流程或应用界面集成。README 中的构建、报告及生产验收脚本不属于此测试命令，可能读取其他项目、本机配置或调用外部服务；离线验证只运行上述 unittest 命令。
