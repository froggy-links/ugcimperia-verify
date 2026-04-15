import os
import aiohttp
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import RedirectResponse
from motor.motor_asyncio import AsyncIOMotorClient

# =========================
# ENV
# =========================
CLIENT_ID = os.getenv("ROBLOX_CLIENT_ID")
CLIENT_SECRET = os.getenv("ROBLOX_CLIENT_SECRET")
REDIRECT_URI = os.getenv("REDIRECT_URI")
MONGO_URI = os.getenv("MONGO_URI")

# =========================
# APP
# =========================
app = FastAPI()

# =========================
# MONGO
# =========================
mongo = AsyncIOMotorClient(MONGO_URI)
db = mongo["ugcearn"]
col = db["linked_ids"]

# =========================
# ROOT
# =========================
@app.get("/")
async def root():
    return {"status": "running"}

# =========================
# AUTH START
# =========================
@app.get("/auth")
async def auth(discord_id: str):
    if not discord_id:
        raise HTTPException(status_code=400, detail="missing discord_id")

    url = (
        "https://apis.roblox.com/oauth/v1/authorize"
        f"?client_id={CLIENT_ID}"
        "&response_type=code"
        f"&redirect_uri={REDIRECT_URI}"
        "&scope=openid"
        f"&state={discord_id}"
    )

    return RedirectResponse(url)

# =========================
# CALLBACK
# =========================
@app.get("/callback")
async def callback(request: Request):
    code = request.query_params.get("code")
    discord_id = request.query_params.get("state")

    if not code or not discord_id:
        raise HTTPException(status_code=400, detail="missing code/state")

    async with aiohttp.ClientSession() as session:

        # -------------------------
        # Exchange code for token
        # -------------------------
        async with session.post(
            "https://apis.roblox.com/oauth/v1/token",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": REDIRECT_URI,
                "client_id": CLIENT_ID,
                "client_secret": CLIENT_SECRET,
            },
        ) as r:
            token = await r.json()

            if r.status != 200 or "access_token" not in token:
                raise HTTPException(status_code=400, detail={"token_error": token})

        # -------------------------
        # Get user info
        # -------------------------
        async with session.get(
            "https://apis.roblox.com/oauth/v1/userinfo",
            headers={
                "Authorization": f"Bearer {token['access_token']}"
            },
        ) as r:
            user = await r.json()

            if r.status != 200 or "sub" not in user:
                raise HTTPException(status_code=400, detail={"user_error": user})

    # -------------------------
    # Save to MongoDB
    # -------------------------
    await col.update_one(
        {"discordId": discord_id},
        {"$set": {"robloxId": user["sub"]}},
        upsert=True,
    )

    return {"ok": True, "robloxId": user["sub"]}

# =========================
# GET USER
# =========================
@app.get("/user/{discord_id}")
async def get_user(discord_id: str):
    data = await col.find_one({"discordId": discord_id})

    if not data:
        return {"robloxId": None}

    return {"robloxId": data.get("robloxId")}
