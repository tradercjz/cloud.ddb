# FILE: create_first_user.py
import asyncio
from db.session import SessionLocal
from db import crud
from schemas import UserCreate

async def main():
    """
    A simple script to create the first user directly in the database.
    """
    print("--- Creating the first user ---")
    db = SessionLocal()
    
    username = "admin"
    password = "JZJZ112233"

    print(f"Checking if user '{username}' already exists...")
    user = await crud.get_user_by_username(db, username=username)
    
    if user:
        print(f"User '{username}' already exists. Skipping creation.")
    else:
        user_in = UserCreate(username=username, password=password)
        await crud.create_user(db, user=user_in)
        print(f"✅ User '{username}' created successfully!")
        print("You can now log in with these credentials.")
    
    await db.close()

if __name__ == "__main__":
    asyncio.run(main())