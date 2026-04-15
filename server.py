import os
import aiohttp
import traceback
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import RedirectResponse
from motor.motor_asyncio import AsyncIOMotorClient

# =========================
# ENV (with safety debug)
# =========================
CLIENT_ID = os.getenv("ROBLOX_CLIENT_ID")
CLIENT_SECRET = os.getenv("ROBLOX_CLIENT_SECRET")
REDIRECT_URI = os.getenv("REDIRECT_URI")
MONGO_URI = os.getenv("MONGO_URI")

def check_env():
    missing = []
    if not CLIENT_ID: missing.append("ROBLOX_CLIENT_ID")
    if not CLIENT_SECRET: missing.append("ROBLOX_CLIENT_SECRET")
    if not REDIRECT_URI: missing.append("REDIRECT_URI")
    if not MONGO_URI: missing.append("MONGO_URI")
    if missing:
        raise RuntimeError(f"Missing env vars: {missing}")

# run check at startup
check_env()

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
    return {
        "status": "running",
        "debug": "ok",
    }

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
# CALLBACK (FULL DEBUG)
# =========================
@app.get("/callback")
async def callback(request: Request):
    try:
        code = request.query_params.get("code")
        discord_id = request.query_params.get("state")

        print("CALLBACK HIT")
        print("CODE:", code)
        print("STATE:", discord_id)

        if not code or not discord_id:
            raise HTTPException(status_code=400, detail="missing code/state")

        async with aiohttp.ClientSession() as session:

            # =========================
            # TOKEN REQUEST (DEBUG)
            # =========================
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

                token_text = await r.text()
                print("TOKEN STATUS:", r.status)
                print("TOKEN RESPONSE:", token_text)

                try:
                    token = await r.json()
                except:
                    raise HTTPException(status_code=400, detail=f"Token not JSON: {token_text}")

                if r.status != 200 or "access_token" not in token:
                    raise HTTPException(status_code=400, detail={"token_error": token})

            # =========================
            # USER INFO REQUEST (DEBUG)
            # =========================
            async with session.get(
                "https://apis.roblox.com/oauth/v1/userinfo",
                headers={
                    "Authorization": f"Bearer {token['access_token']}"
                },
            ) as r:

                user_text = await r.text()
                print("USER STATUS:", r.status)
                print("USER RESPONSE:", user_text)

                try:
                    user = await r.json()
                except:
                    raise HTTPException(status_code=400, detail=f"User not JSON: {user_text}")

                if r.status != 200 or "sub" not in user:
                    raise HTTPException(status_code=400, detail={"user_error": user})

        # =========================
        # SAVE TO MONGO
        # =========================
        await col.update_one(
            {"discordId": discord_id},
            {"$set": {"robloxId": user["sub"]}},
            upsert=True,
        )

        return {
            "ok": True,
            "robloxId": user["sub"]
        }

    except Exception as e:
        print("FATAL ERROR:")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

# =========================
# GET USER
# =========================
@app.get("/user/{discord_id}")
async def get_user(discord_id: str):
    data = await col.find_one({"discordId": discord_id})

    if not data:
        return {"robloxId": None}

    return {"robloxId": data.get("robloxId")}
