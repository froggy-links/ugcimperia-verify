import os
import aiohttp
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

if not all([CLIENT_ID, CLIENT_SECRET, REDIRECT_URI, MONGO_URI]):
    raise RuntimeError("Missing environment variables")

# =========================
# APP + DB
# =========================
app = FastAPI()

mongo = AsyncIOMotorClient(MONGO_URI)
db = mongo["ugcearn"]

sessions = db["sessions"]
users = db["linked_ids"]

# =========================
# ROOT
# =========================
@app.get("/")
async def root():
    return {"status": "running"}

# =========================
# AUTH (uses session)
# =========================
@app.get("/auth")
async def auth(session: str):

    session_data = await sessions.find_one({"sessionId": session})

    if not session_data:
        raise HTTPException(status_code=400, detail="invalid session")

    url = (
        "https://apis.roblox.com/oauth/v1/authorize"
        f"?client_id={CLIENT_ID}"
        "&response_type=code"
        f"&redirect_uri={REDIRECT_URI}"
        "&scope=openid"
        f"&state={session}"
    )

    return RedirectResponse(url)

# =========================
# CALLBACK (final link step)
# =========================
@app.get("/callback")
async def callback(request: Request):

    code = request.query_params.get("code")
    session = request.query_params.get("state")

    if not code or not session:
        raise HTTPException(status_code=400, detail="missing code/state")

    session_data = await sessions.find_one({"sessionId": session})

    if not session_data:
        raise HTTPException(status_code=400, detail="invalid session")

    discord_id = session_data["discordId"]

    async with aiohttp.ClientSession() as client:

        # -------------------------
        # Exchange code for token
        # -------------------------
        async with client.post(
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
        # Get Roblox user
        # -------------------------
        async with client.get(
            "https://apis.roblox.com/oauth/v1/userinfo",
            headers={"Authorization": f"Bearer {token['access_token']}"},
        ) as r:
            user = await r.json()

            if r.status != 200 or "sub" not in user:
                raise HTTPException(status_code=400, detail={"user_error": user})

    # -------------------------
    # Save / update user
    # -------------------------
    await users.update_one(
        {"discordId": discord_id},
        {
            "$set": {
                "robloxId": user["sub"],
                "tokens": 0
            }
        },
        upsert=True
    )

    # -------------------------
    # Cleanup session
    # -------------------------
    await sessions.delete_one({"sessionId": session})

    # -------------------------
    # Simple success page
    # -------------------------
    return HTMLResponse("""
    <html>
        <body style="background:#0b0f14;color:white;display:flex;align-items:center;justify-content:center;height:100vh;font-family:sans-serif;">
            <div style="text-align:center;">
                <h1 style="color:#22c55e;">You are all set</h1>
                <p>You can close this page now.</p>
            </div>
        </body>
    </html>
    """)

# =========================
# GET USER
# =========================
@app.get("/user/{discord_id}")
async def get_user(discord_id: str):

    data = await users.find_one({"discordId": discord_id})

    if not data:
        return {"robloxId": None, "tokens": 0}

    return {
        "robloxId": data.get("robloxId"),
        "tokens": data.get("tokens", 0)
    }
