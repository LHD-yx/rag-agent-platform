"""配置加载与路径解析。"""
from __future__ import annotations

import os
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent


def _load_dotenv(path: Path) -> None:
    """极简 .env 加载：KEY=VALUE 逐行读取，不覆盖已存在的环境变量。

    这样在 PyCharm 里新建 .env 文件写入 API Key 即可，无需配置 Run Configuration。
    """
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_dotenv(ROOT / ".env")


def load_config(path: str | Path | None = None) -> dict:
    """读取 YAML 配置，默认使用 configs/config.yaml。"""
    cfg_path = Path(path) if path else ROOT / "configs" / "config.yaml"
    with open(cfg_path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    cfg["_root"] = ROOT
    return cfg


def resolve(cfg: dict, key_path: str) -> Path:
    """把配置里的相对路径解析成项目根目录下的绝对路径。"""
    value = cfg
    for key in key_path.split("."):
        value = value[key]
    path = Path(value)
    return path if path.is_absolute() else cfg["_root"] / path
