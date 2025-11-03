import configparser
import os
import logging

# Get base directory
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "config.ini")
LOG_PATH = os.path.join(BASE_DIR, "app.log")

def setup_logging():
    logging.basicConfig(
        filename=LOG_PATH,
        level=logging.DEBUG,
        format='%(asctime)s - %(levelname)s - %(name)s - %(message)s'
    )

setup_logging()

logger = logging.getLogger(__name__)

# Load config
config = configparser.ConfigParser()
config.read(CONFIG_PATH)

logger.info("Loaded configuration from %s", CONFIG_PATH)
if not config.sections():
    logger.warning("No sections found in config.ini")
    raise RuntimeError("config.ini is missing or empty")

# Settings
MODE = config.get("settings", "mode", fallback="DEBUG")
MYSQL_USER = config.get("mysql", "user")
MYSQL_PASSWORD = config.get("mysql", "password")
MYSQL_HOST = config.get("mysql", "host")
MYSQL_PORT = config.get("mysql", "port")
MYSQL_DB = config.get("mysql", "database")
OPTIONS = dict(config.items("options"))

# URLs
SQLITE_DATABASE_URL = f"sqlite:///{os.path.join(BASE_DIR, 'test.db')}"
MSSQL_DATABASE_URL = (
    f"mssql+pyodbc://{MYSQL_USER}:{MYSQL_PASSWORD}@{MYSQL_HOST}:{MYSQL_PORT}/{MYSQL_DB}"
    f"?driver={OPTIONS['driver'].replace(' ', '+')}"
)

# Cache TTLs
CACHE_TTL_EXECUTIONS_ACTIVE = 5  # 5 seconds for active executions (PENDING, IN_PROGRESS)
CACHE_TTL_EXECUTIONS_COMPLETED = 3600  # 1 hour for completed executions (SUCCESS, FAILED)
