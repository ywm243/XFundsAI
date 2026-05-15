import os


class DBConfig:
    host = os.environ.get("DB_HOST", "localhost")
    port = int(os.environ.get("DB_PORT", "1521"))
    service = os.environ.get("DB_SERVICE", "orclutf")
    user = os.environ.get("DB_USER", "")
    password = os.environ.get("DB_PASSWORD", "")

    @property
    def dsn(self) -> str:
        return f"{self.host}:{self.port}/{self.service}"
