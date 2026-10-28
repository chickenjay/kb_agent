# 安装与导入排障记录

初始命令 `python -m unittest discover -s tests -v` 出现 5 个模块导入错误：`ModuleNotFoundError: No module named 'kb_agent'`。这不是业务用例通过。

当时 `pip install -e .` 已成功，但 Python 3.11 / Windows 中文目录中的路径型 `.pth` 使用 UTF-8 路径文本，而解释器按区域编码读取，没有把源目录正确加入路径。仅设置 PYTHONUTF8 未解决该 `.pth` 读取路径问题。

修正 pyproject.toml，明确 `packages=["kb_agent"]` 和 `package-dir={"kb_agent":"src/kb_agent"}`，使 setuptools 生成 import finder 而不是非 ASCII 绝对路径型 `.pth`。重新安装后，不设置 PYTHONPATH 即可导入，后续完整测试通过。

另外首次使用 `--no-build-isolation` 的 editable 安装缺少 wheel，补装 wheel 后成功。README 正常安装使用构建隔离，会按 pyproject 声明获取构建依赖。系统的额外 Python 包索引不可达，依赖实际由 PyPI 下载；npm 默认缓存位于受限的 Program Files，改用项目内缓存后安装成功。依赖安装授权没有用于改变系统配置。
