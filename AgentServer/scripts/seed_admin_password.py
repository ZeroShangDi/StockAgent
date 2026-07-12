#!/usr/bin/env python3
"""Docker entrypoint: seed admin password on first boot."""
import asyncio, os, sys
sys.path.insert(0, "/app")

async def seed():
    from core.managers import mongo_manager
    await mongo_manager.initialize()

    import bcrypt
    admin_password = os.environ.get("ADMIN_PASSWORD", "admin123")
    pw_hash = bcrypt.hashpw(admin_password.encode(), bcrypt.gensalt(rounds=12)).decode()

    existing = await mongo_manager.find_one("users", {"username": "admin"})
    if existing:
        await mongo_manager.update_one(
            "users",
            {"username": "admin"},
            {"$set": {"password_hash": pw_hash}},
        )
        print(f"Admin password seeded (updated existing user)")
    else:
        import uuid
        await mongo_manager.insert_one("users", {
            "user_id": uuid.uuid4().hex,
            "username": "admin",
            "password_hash": pw_hash,
            "email": "admin@stockagent.local",
            "nickname": "Admin",
            "is_admin": True,
            "created_at": __import__("datetime").datetime.now(),
        })
        print(f"Admin user created with seeded password")

    await mongo_manager.shutdown()

if __name__ == "__main__":
    asyncio.run(seed())
