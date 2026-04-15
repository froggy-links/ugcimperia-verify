import os
import aiohttp
import traceback
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
col = db["linked_ids"]

# =========================
# ROOT
# =========================
@app.get("/")
async def root():
    return {"status": "running", "debug": "ok"}

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
# SUCCESS PAGE
# =========================
def verified_page():
    return """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Verified</title>
        <meta http-equiv="refresh" content="5;url=https://discord.com">
        <style>
            body {
                margin: 0;
                height: 100vh;
                display: flex;
                align-items: center;
                justify-content: center;
                background: #0b0f14;
                font-family: system-ui, -apple-system, Segoe UI, Roboto, Arial, sans-serif;
                color: white;
            }

            .card {
                text-align: center;
                padding: 40px 50px;
                border-radius: 14px;
                background: rgba(255, 255, 255, 0.04);
                border: 1px solid rgba(255, 255, 255, 0.08);
                backdrop-filter: blur(10px);
            }

            h1 {
                font-size: 42px;
                letter-spacing: 2px;
                margin: 0;
                color: #22c55e;
            }

            p {
                margin-top: 10px;
                font-size: 15px;
                color: rgba(255, 255, 255, 0.7);
            }
        </style>
    </head>

    <body>
        <div class="card">
            <h1>VERIFIED</h1>
            <p>You’re all set — feel free to close this page.</p>
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
        discord_id = request.query_params.get("state")

        print("CALLBACK HIT")
        print("CODE:", code)
        print("STATE:", discord_id)

        if not code or not discord_id:
            raise HTTPException(status_code=400, detail="missing code/state")

        async with aiohttp.ClientSession() as session:

            # TOKEN
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

                token = await r.json()

                if r.status != 200 or "access_token" not in token:
                    raise HTTPException(status_code=400, detail={"token_error": token})

            # USER INFO
            async with session.get(
                "https://apis.roblox.com/oauth/v1/userinfo",
                headers={"Authorization": f"Bearer {token['access_token']}"},
            ) as r:

                user_text = await r.text()
                print("USER STATUS:", r.status)
                print("USER RESPONSE:", user_text)

                user = await r.json()

                if r.status != 200 or "sub" not in user:
                    raise HTTPException(status_code=400, detail={"user_error": user})

        # =========================
        # SAVE / REPLACE ONLY (NO DUPLICATES)
        # =========================
        await col.update_one(
            {"discordId": discord_id},
            {"$set": {"robloxId": user["sub"]}},
            upsert=True,
        )

        return HTMLResponse(verified_page())

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
