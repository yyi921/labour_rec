"""
Database connection handling for MCP Server
Detects PostgreSQL (Railway) vs SQLite (local) based on environment
"""
import os
from pathlib import Path
from contextlib import contextmanager


def get_connection():
    """
    Get a database connection based on environment.
    Uses PostgreSQL when PGHOST is set, otherwise SQLite.
    """
    if os.environ.get('PGHOST'):
        # PostgreSQL for Railway production
        import psycopg2
        return psycopg2.connect(
            dbname=os.environ.get('PGDATABASE'),
            user=os.environ.get('PGUSER'),
            password=os.environ.get('PGPASSWORD'),
            host=os.environ.get('PGHOST'),
            port=os.environ.get('PGPORT', '5432')
        )
    else:
        # SQLite for local development
        import sqlite3
        base_dir = Path(__file__).resolve().parent.parent
        db_path = base_dir / 'db.sqlite3'
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        return conn


@contextmanager
def get_db_cursor():
    """
    Context manager for database operations.
    Automatically handles connection and cleanup.
    """
    conn = get_connection()
    try:
        cursor = conn.cursor()
        yield cursor
        conn.commit()
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        cursor.close()
        conn.close()


def is_postgresql():
    """Check if we're using PostgreSQL"""
    return bool(os.environ.get('PGHOST'))


def dict_from_row(row, cursor_description):
    """Convert a database row to a dictionary"""
    if hasattr(row, 'keys'):
        # SQLite Row object
        return dict(row)
    else:
        # PostgreSQL tuple
        return {desc[0]: value for desc, value in zip(cursor_description, row)}


def execute_query(query, params=None):
    """
    Execute a query and return results as list of dictionaries.
    """
    with get_db_cursor() as cursor:
        cursor.execute(query, params or ())
        rows = cursor.fetchall()
        return [dict_from_row(row, cursor.description) for row in rows]


def execute_single(query, params=None):
    """
    Execute a query and return a single result as dictionary.
    """
    results = execute_query(query, params)
    return results[0] if results else None
