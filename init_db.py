"""Create/update the local database without importing or deleting documents."""
from config import Settings
from database import Repository


def inisialisasi_database():
    repository = Repository(Settings().db_path)
    repository.initialize()
    print(f"Database siap: {repository.path}")


if __name__ == "__main__":
    inisialisasi_database()
