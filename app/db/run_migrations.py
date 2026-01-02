"""
Migration runner script
"""

import asyncio
import sys
sys.path.insert(0, '.')

from app.db.migrations.multi_tenancy_001 import run_migration, rollback_migration


async def main():
    import argparse
    parser = argparse.ArgumentParser(description='Run database migrations')
    parser.add_argument('action', choices=['up', 'down'], help='Migration direction')
    args = parser.parse_args()

    if args.action == 'up':
        await run_migration()
    elif args.action == 'down':
        confirm = input("⚠️ This will delete multi-tenancy tables. Type 'YES' to confirm: ")
        if confirm == 'YES':
            await rollback_migration()
        else:
            print("Rollback cancelled.")


if __name__ == "__main__":
    asyncio.run(main())
