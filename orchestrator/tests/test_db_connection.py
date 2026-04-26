#!/usr/bin/env python3
"""
Test PostgreSQL Connection
"""

import asyncpg
import asyncio

async def test_pg():
    try:
        conn = await asyncpg.connect(
            host='localhost',
            port=5434,
            user='pfe',
            password='pfe2026',
            database='scoring_db'
        )
        vers = await conn.fetchval('SELECT version()')
        print(f"✅ PostgreSQL connected!")
        print(f"Version: {vers[:50]}...")
        await conn.close()
        return True
    except Exception as e:
        print(f"❌ PostgreSQL connection failed: {e}")
        return False

if __name__ == "__main__":
    result = asyncio.run(test_pg())
    exit(0 if result else 1)
