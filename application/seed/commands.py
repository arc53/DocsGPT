import click

from application.seed.seeder import DatabaseSeeder


@click.group()
def seed():
    """Database seeding commands"""
    pass


@seed.command()
@click.option("--force", is_flag=True, help="Force reseeding even if data exists")
def init(force):
    """Initialize database with seed data"""
    seeder = DatabaseSeeder()
    seeder.seed_initial_data(force=force)


if __name__ == "__main__":
    seed()
