import click

from application.core.mongo_db import MongoDB
from application.core.settings import settings
from application.seed.seeder import DatabaseSeeder


@click.group()
def seed():
    """Database seeding commands"""
    pass


@seed.command()
@click.option("--force", is_flag=True, help="Force reseeding even if data exists")
def init(force):
    """Initialize database with seed data"""
    mongo = MongoDB.get_client()
    db = mongo[settings.MONGO_DB_NAME]

    seeder = DatabaseSeeder(db)
    seeder.seed_initial_data(force=force)


if __name__ == "__main__":
    seed()
