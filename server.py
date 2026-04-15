import os
import uuid
import aiohttp
import traceback
from datetime import datetime

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import RedirectResponse, HTMLResponse
from motor.motor_asyncio import AsyncIOMotorClient

# =========================
# ENV
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

users = db["linked_ids"]
sessions = db["sessions"]

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

    session_id = str(uuid.uuid4())

    await sessions.insert_one({
        "sessionId": session_id,
        "discordId": discord_id,
        "createdAt": datetime.utcnow()
    })

    url = (
        "https://apis.roblox.com/oauth/v1/authorize"
        f"?client_id={CLIENT_ID}"
        "&response_type=code"
        f"&redirect_uri={REDIRECT_URI}"
        "&scope=openid"
        f"&state={session_id}"
    )

    return RedirectResponse(url)

# =========================
# VERIFIED PAGE
# =========================
def verified_page():
    return """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Verified</title>
        <style>
            body {
                margin: 0;
                height: 100vh;
                display: flex;
                align-items: center;
                justify-content: center;
                background: #0b0f14;
                font-family: system-ui, Arial;
                color: white;
            }

            .card {
                text-align: center;
                padding: 40px 50px;
                border-radius: 14px;
                background: rgba(255,255,255,0.04);
                border: 1px solid rgba(255,255,255,0.08);
            }

            h1 {
                font-size: 42px;
                color: #22c55e;
                margin: 0;
                letter-spacing: 2px;
            }

            p {
                margin-top: 10px;
                color: rgba(255,255,255,0.7);
                font-size: 15px;
            }
        </style>
    </head>
    <body>
        <div class="card">
            <h1>VERIFIED</h1>
            <p>You’re all set — you can close this page.</p>
        </div>
    </body>
    </html>
    """

# =========================
# CALLBACK
# =========================
@app.get("/callback")
async def callback(request: Request):
    try:
        code = request.query_params.get("code")
        state = request.query_params.get("state")

        if not code or not state:
            raise HTTPException(400, "missing code/state")

        # -------------------------
        # GET SESSION
        # -------------------------
        session = await sessions.find_one({"sessionId": state})
        if not session:
            raise HTTPException(400, "invalid session")

        discord_id = session["discordId"]

        async with aiohttp.ClientSession() as session_http:

            # -------------------------
            # TOKEN
            # -------------------------
            async with session_http.post(
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
                    raise HTTPException(400, {"token_error": token})

            # -------------------------
            # USER INFO
            # -------------------------
            async with session_http.get(
                "https://apis.roblox.com/oauth/v1/userinfo",
                headers={"Authorization": f"Bearer {token['access_token']}"},
            ) as r:

                user = await r.json()

                if r.status != 200 or "sub" not in user:
                    raise HTTPException(400, {"user_error": user})

        # -------------------------
        # SAVE USER (NO DUPLICATES)
        # -------------------------
        await users.update_one(
            {"discordId": discord_id},
            {
                "$set": {
                    "robloxId": user["sub"]
                },
                "$setOnInsert": {
                    "tokens": 0
                }
            },
            upsert=True
        )

        # -------------------------
        # CLEAN SESSION
        # -------------------------
        await sessions.delete_one({"sessionId": state})

        return HTMLResponse(verified_page())

    except Exception as e:
        print("ERROR:")
        traceback.print_exc()
        raise HTTPException(500, str(e))

# =========================
# GET USER
# =========================
@app.get("/user/{discord_id}")
async def get_user(discord_id: str):
    data = await users.find_one({"discordId": discord_id})

    if not data:
        return {"robloxId": None, "tokens": None}

    return {
        "robloxId": data.get("robloxId"),
        "tokens": data.get("tokens", 0)
    }
