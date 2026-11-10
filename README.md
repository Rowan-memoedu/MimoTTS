# MiMo TTS

协作开发、Agent 提交与合并规则见 [CONTRIBUTING.md](CONTRIBUTING.md)。


可复用的 Python API、命令行及软件 TTS 接入。正式迁移已获授权，当前运行状态见对照汇总页。

## 直接使用

已安装入口：`D:\AppData\MimoTTS\bin\mimo-tts.cmd`。新终端可直接输入 `mimo-tts`。

```powershell
mimo-tts --json doctor
mimo-tts --json synthesize --text '你好，这是语音测试。' --out D:\Artifacts\hello.wav
mimo-tts --json synthesize --text-file D:\Artifacts\narration.txt --voice Mia --out D:\Artifacts\english.mp3
mimo-tts --json synthesize --text-file D:\Artifacts\narration.txt --mode design --style '温和清晰的青年女声，适合教学讲解' --out D:\Artifacts\designed.wav
mimo-tts --json synthesize --text '另一段测试内容。' --mode clone --reference D:\Artifacts\designed.wav --out D:\Artifacts\cloned.wav
```

`--text-file -` 读取标准输入；`--dry-run` 只校验参数；输出路径已存在时拒绝覆盖。长文本按原始顺序分段，不改写、删括号或总结输入。VoiceDesign 的文本优化关闭；模型是否实际漏读仍需试听。

`--speed 0.97 --volume 0.82` 调整最终录音。WAV 默认无需额外运行依赖；MP3 和语速／音量变换使用 ffmpeg。返回 JSON 含文件、哈希、耗时、分段缓存及完成状态；日志和清单不存原文或 API key。播放程序可以通过 `on_chunk` 接收 24 kHz 单声道 PCM16LE。

```python
from mimo_tts import synthesize

result = synthesize("需要朗读的内容", r"D:\Artifacts\sample.wav")
print(result["path"])
```

## 模型怎么选

| 模式 | 模型 | 建议场景 | 边界 |
| --- | --- | --- | --- |
| preset | mimo-v2.5-tts | 点读、网页朗读、卡片、即时提醒 | 默认；可流式返回；中英文统一 Mia（汇总页第二组音色） |
| design | mimo-v2.5-tts-voicedesign | 自定义旁白、角色与讲解风格 | 需要文字风格描述；逐段声音一致性需试听 |
| clone | mimo-v2.5-tts-voiceclone | 复用已授权样本或满意的设计音色 | WAV/MP3 参考，base64 ≤10 MB；跨文本一致性需实测 |

截至 2026-09-27，官方模型页列为限时免费，未查到明确截止日期。不要把此次免费状态视为长期价格承诺。Design/Clone 的兼容流式接口会先等完整推理，封装默认使用非流式；Preset 使用 SSE。

接口：`POST https://api.xiaomimimo.com/v1/chat/completions`；待朗读文本放在 `assistant` 消息，风格指令放在 `user` 消息。详见 [官方语音文档](https://mimo.mi.com/docs/en-US/quick-start/usage-guide/audio/speech-synthesis)、[官方脚本](https://github.com/XiaomiMiMo/MiMo-Skills/tree/main/skills/mimo-v2-5-tts)、[模型页](https://mimo.mi.com/models/zh-CN/mimo-v2.5-tts)。

## 配置与目录

- 源码：`D:\Projects\MimoTTS`；独立私有仓库，main 跟踪 origin/main。
- 运行环境：`D:\AppData\MimoTTS\venv`；依赖缓存 `D:\Caches\pip`。
- 音频缓存：`D:\Caches\MimoTTS`；音频、报告、测试构建：`D:\Artifacts\MimoTTS`。
- `MIMO_API_KEY` 按当前进程、Windows 用户环境变量顺序读取，不要求重启正在使用的软件。`doctor --probe` 才会做真实合成；普通 doctor 只检查本地配置。
- 重新安装：`pwsh -File D:\Projects\MimoTTS\scripts\Install.ps1`。API key 不写入文件、命令行参数或 Git。
- Codex Skill：`skill\mimo-tts\SKILL.md`；已通过 C 盘 Codex 元数据入口的目录联接指向 D 盘源码，没有复制活动源码。

## 对照页面与测试版本

最新页面路径保存在 `D:\Artifacts\MimoTTS\latest-report.json`。当前报告有 6 组同文旧／新录音和 3 种 MiMo 同文录音，支持顺序播放、倍速、下载。旧版声线来自源码默认或本机现用配置。合成与解码成功不等于主观质量胜出。

| 软件 | 入口（相对 D:\Artifacts\MimoTTS\test-builds） | 隔离方式 |
| --- | --- | --- |
| WebLilt | `WebLilt\extension` | 独立扩展 ID、`com.weblilt.mimo_test` Native Host；保留原版。Chrome 扩展管理页加载该文件夹后可测试；尚未在用户浏览器加载。MiMo 无词级时间戳，保留句子高亮，音高固定为 0。 |
| 零碎知识剪藏 | `KnowledgeClipper\Start-Test.ps1` | 独立 EXE、互斥锁、数据、缓存；原导出目的端点改为测试端口。旧 SpeechKit 入口及新 PCM helper 均适配 MiMo。 |
| Anki / SuperFreeTTSReview | `Anki\Start-Test.ps1` | 官方 `-b` 指向 `D:\AppData\MimoTTS\test-apps\Anki`；只在此路径创建测试牌组和挂载插件。首次打开可能显示资料库选择。不要把 `.ankiaddon` 装入正式资料库。 |
| OpenFocus | `OpenFocus\Preview-Voice.ps1` | 直接试听；完整测试界面为 `Start-Test.ps1`，使用独立空数据目录。 |
| 通用入口 | `mimo-tts` | 原有 speech-kit 配置保持原状。 |

录音后端和打包入口已有程序验证；WebLilt Chrome 扩展加载、Anki 复习界面及完整应用交互仍待测试。准确状态见 `D:\Artifacts\MimoTTS\validation.md`。Anki 路径参数依据[官方手册](https://docs.ankiweb.net/files.html#startup-options)。

## 复现与验证

```powershell
& D:\AppData\MimoTTS\venv\Scripts\python.exe -m unittest discover -s tests -v
& D:\AppData\MimoTTS\venv\Scripts\python.exe scripts\build_test_versions.py
& D:\Artifacts\MimoTTS\test-builds\KnowledgeClipper\Build.ps1
& D:\AppData\MimoTTS\venv\Scripts\python.exe scripts\verify_adapters.py
& D:\AppData\MimoTTS\venv\Scripts\python.exe scripts\create_comparison_report.py
node scripts\verify_report.mjs
```

构建器只读取现有项目，保留源码和 Git 脏改动；构建中间材料在 D 盘缓存。页面脚本会发送公开测试文本到对应旧／新 TTS 服务，不使用私人卡片。`--refresh <已有报告目录>` 只重新渲染和解码检查，不调用 API。

浏览器验收使用独立 Chrome 无头资料目录，检测全部音频实际播放进度、顺序切换、倍速、停止和桌面／窄屏布局。静音运行不证明物理扬声器出声。新旧耗时包括不同调用入口开销，且样本仅一次，不能据此做长期性能排名。

Git 排除凭据、参考音频、用户输入、缓存、数据和构建产物。三模型对比使用生成声音作为克隆参考。

## 正式迁移（2026-09-27）

用户已批准全部迁移；从各软件当前源码做增量合并和重新构建，不复用旧隔离包覆盖同期更新。通用 speech-kit 默认 MiMo，普通合成和 SRT 分段合同保留；单次 `--provider doubao` 可比较原方案。OpenFocus 后台已激活，Anki 和剪藏主程序等待重启确认；WebLilt 正式 Native Host 已激活，用户确认已加载扩展；Obsidian 阅读器已通过官方 CLI 重载并切换，保留原语速与右侧面板。

准确运行状态及验收：`D:\Artifacts\MimoTTS\production\20260927\status.json`、`deployment.md`。`scripts/production_receipt.py` 记录源码基线和当前差异；`scripts/verify_adapters.py --production` 验证正式源码/包入口，不操作私人卡片或督学规则。源码中未提交的其他更新保留；回退只逆向合并语音补丁，不还原整个目录。
