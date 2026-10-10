from alembic import context


def run():
    connection = context.config.attributes.get("connection")
    if connection is None:
        from knowledge_world.config import Settings
        from knowledge_world.db import Database

        database = Database(Settings())
        with database.engine.connect() as conn:
            context.configure(connection=conn, transaction_per_migration=True)
            with context.begin_transaction():
                context.run_migrations()
    else:
        context.configure(connection=connection, transaction_per_migration=True)
        with context.begin_transaction():
            context.run_migrations()


run()
