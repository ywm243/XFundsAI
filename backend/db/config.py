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


class MySQLConfig:
    host = os.environ.get("MYSQL_HOST", "localhost")
    port = int(os.environ.get("MYSQL_PORT", "3306"))
    user = os.environ.get("MYSQL_USER", "root")
    password = os.environ.get("MYSQL_PASSWORD", "smartbi123")
    database = os.environ.get("MYSQL_DATABASE", "smartbi")

    @property
    def dsn(self) -> dict:
        return {
            "host": self.host,
            "port": self.port,
            "user": self.user,
            "password": self.password,
            "database": self.database,
            "charset": "utf8mb4",
        }
