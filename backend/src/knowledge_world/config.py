from dataclasses import dataclass, field
from pathlib import Path
import os

ROOT = Path(__file__).resolve().parents[3]


@dataclass
class Settings:
    data_dir: Path = field(
        default_factory=lambda: Path(os.getenv("KW_DATA_DIR", str(ROOT / "data"))).resolve()
    )
    mode: str = field(default_factory=lambda: os.getenv("KW_MODE", "production"))
    fake_provider: bool = field(default_factory=lambda: os.getenv("KW_FAKE_PROVIDER", "0") == "1")
    origin: str = field(default_factory=lambda: os.getenv("KW_ORIGIN", "http://127.0.0.1:8000"))
    secure_cookie: bool = field(default_factory=lambda: os.getenv("KW_SECURE_COOKIE", "0") == "1")

    def __post_init__(self):
        if self.fake_provider and self.mode not in {"test", "development"}:
            raise RuntimeError("测试适配器只允许在 test/development 模式启用")
        self.data_dir.mkdir(parents=True, exist_ok=True)

    @property
    def database(self):
        return self.data_dir / "knowledge-world.db"
