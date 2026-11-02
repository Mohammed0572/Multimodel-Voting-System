"""Configure isolated test services before any module imports application code."""
import os

os.environ["SECRET_KEY"] = "test-only-secret-with-at-least-thirty-two-bytes"
os.environ["ADMIN_USERNAME"] = "admin_user"
os.environ["ADMIN_PASSWORD"] = "securepassword123"
os.environ["REDIS_URL"] = "memory://"
os.environ["REQUIRE_REDIS"] = "false"
os.environ["IMPORT_LEGACY_PICKLE"] = "false"
os.environ["BLOCKCHAIN_CONTRACT_ADDRESS"] = ""
os.environ["BLOCKCHAIN_RELAYER_PRIVATE_KEY"] = ""
