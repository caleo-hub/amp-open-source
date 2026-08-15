import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote


@dataclass(frozen=True)
class DatabaseSettings:
    host: str
    port: int
    name: str
    user: str
    password_file: Path

    def password(self) -> str:
        value = self.password_file.read_text(encoding="utf-8").strip()
        if not value:
            raise RuntimeError("Database secret vazio.")
        return value

    def kwargs(self, search_path: str = "amp,public") -> dict:
        return {
            "host": self.host,
            "port": self.port,
            "dbname": self.name,
            "user": self.user,
            "password": self.password(),
            "options": f"-c search_path={search_path}",
        }

    def dsn(self, search_path: str = "langgraph,public") -> str:
        options = quote(f"-c search_path={search_path}", safe="")
        return (
            f"postgresql://{quote(self.user, safe='')}:{quote(self.password(), safe='')}"
            f"@{self.host}:{self.port}/{quote(self.name, safe='')}?options={options}"
        )


def database_settings() -> DatabaseSettings:
    return DatabaseSettings(
        host=os.getenv("AMP_DB_HOST", "localhost"),
        port=int(os.getenv("AMP_DB_PORT", "5432")),
        name=os.getenv("AMP_DB_NAME", "amp"),
        user=os.getenv("AMP_DB_USER", "amp"),
        password_file=Path(
            os.getenv(
                "AMP_DB_PASSWORD_FILE",
                "/run/secrets/postgres_password",
            )
        ),
    )


AMP_AGENT_KEY = os.getenv("AMP_AGENT_KEY", "amp-agent")
AMP_AGENT_VERSION = os.getenv("AMP_AGENT_VERSION", "0.1.0")
GRAPH_VERSION = os.getenv("AMP_GRAPH_VERSION", "1")
STATE_VERSION = int(os.getenv("AMP_STATE_VERSION", "1"))
JOB_LEASE_SECONDS = int(os.getenv("AMP_JOB_LEASE_SECONDS", "120"))
JOB_HEARTBEAT_SECONDS = int(os.getenv("AMP_JOB_HEARTBEAT_SECONDS", "15"))
JOB_MAX_ATTEMPTS = int(os.getenv("AMP_JOB_MAX_ATTEMPTS", "3"))
CHAT_WAIT_TIMEOUT_SECONDS = float(os.getenv("AMP_CHAT_WAIT_TIMEOUT_SECONDS", "30"))
VOICE_WAIT_TIMEOUT_SECONDS = float(os.getenv("AMP_VOICE_WAIT_TIMEOUT_SECONDS", "5"))
REPLY_CHANNELS = frozenset({"alexa", "aws_iot"})
SEARXNG_BASE_URL = os.getenv(
    "SEARXNG_BASE_URL",
    "http://127.0.0.1:8888",
)

WEB_SEARCH_TIMEOUT_SECONDS = float(
    os.getenv("WEB_SEARCH_TIMEOUT_SECONDS", "8")
)

WEB_SEARCH_MAX_RESULTS = int(
    os.getenv("WEB_SEARCH_MAX_RESULTS", "5")
)

WEB_SEARCH_MAX_SNIPPET_CHARS = int(
    os.getenv("WEB_SEARCH_MAX_SNIPPET_CHARS", "500")
)