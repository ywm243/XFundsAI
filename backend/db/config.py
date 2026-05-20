import os
from pathlib import Path

from dotenv import load_dotenv
from pydantic_settings import BaseSettings

_ENV_FILE = Path(__file__).resolve().parent.parent.parent / ".env"

# Load .env into os.environ so code using os.environ.get() still works
load_dotenv(_ENV_FILE, override=True)


class Settings(BaseSettings):
    # Oracle
    db_host: str = "localhost"
    db_port: int = 1521
    db_service: str = "orclutf"
    db_user: str = ""
    db_password: str = ""

    # MySQL
    mysql_host: str = "localhost"
    mysql_port: int = 3306
    mysql_user: str = "root"
    mysql_password: str = ""
    mysql_database: str = "smartbi"

    # LLM
    llm_base_url: str = ""
    llm_api_key: str = ""
    llm_model: str = "deepseek-chat"

    model_config = {
        "env_file": str(_ENV_FILE),
        "env_file_encoding": "utf-8",
        "extra": "allow",  # 允许 .env 中包含未定义字段（如 llm_model_flash, llm_model_pro）
    }


settings = Settings()


class DBConfig:
    @property
    def host(self):
        return settings.db_host

    @property
    def port(self):
        return settings.db_port

    @property
    def service(self):
        return settings.db_service

    @property
    def user(self):
        return settings.db_user

    @property
    def password(self):
        return settings.db_password

    @property
    def dsn(self) -> str:
        return f"{settings.db_host}:{settings.db_port}/{settings.db_service}"


class MySQLConfig:
    @property
    def host(self):
        return settings.mysql_host

    @property
    def port(self):
        return settings.mysql_port

    @property
    def user(self):
        return settings.mysql_user

    @property
    def password(self):
        return settings.mysql_password

    @property
    def database(self):
        return settings.mysql_database

    @property
    def dsn(self) -> dict:
        return {
            "host": settings.mysql_host,
            "port": settings.mysql_port,
            "user": settings.mysql_user,
            "password": settings.mysql_password,
            "database": settings.mysql_database,
            "charset": "utf8mb4",
        }
