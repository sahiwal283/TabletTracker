# Zoho API Setup - Step by Step Guide

This walks you through getting Zoho API credentials working with your tablet tracker.

## Step 1: Create Zoho API Application

1. **Go to:** https://api-console.zoho.com/
2. **Click:** "Create New Application"
3. **Choose:** "Server-based Applications"
4. **Fill out:**
   - Application Name: `Tablet Tracker`
   - Homepage URL: `http://localhost:5000` (for testing)
   - Authorized Redirect URIs: `http://localhost:8080`

5. **Click:** "Create"
6. **Copy:** Your Client ID and Client Secret (save these!)

## Step 2: Get Authorization Code

1. **Replace YOUR_CLIENT_ID** in this URL with your actual Client ID:
```
https://accounts.zoho.com/oauth/v2/auth?scope=ZohoInventory.FullAccess.all&client_id=YOUR_CLIENT_ID&response_type=code&redirect_uri=http://localhost:8080&access_type=offline
```

2. **Paste the URL** in your browser
3. **Login** to your Zoho account
4. **Grant permissions** 
5. **You'll be redirected** to something like:
```
http://localhost:8080/?code=1000.abcd1234.xyz789&location=us&accounts-server=https%3A%2F%2Faccounts.zoho.com
```
6. **Copy the code** (the part after `code=` and before `&`)

## Step 3: Exchange Code for Refresh Token

### Option A: Using Terminal (easier)
In Terminal, run this command (replace YOUR_CLIENT_ID, YOUR_CLIENT_SECRET, and YOUR_CODE):

```bash
curl -X POST https://accounts.zoho.com/oauth/v2/token \
  -d "grant_type=authorization_code" \
  -d "client_id=YOUR_CLIENT_ID" \
  -d "client_secret=YOUR_CLIENT_SECRET" \
  -d "redirect_uri=http://localhost:8080" \
  -d "code=YOUR_CODE"
```

### Option B: Using Postman/Insomnia
- **Method:** POST
- **URL:** `https://accounts.zoho.com/oauth/v2/token`
- **Body:** (form-data)
  - `grant_type`: `authorization_code`
  - `client_id`: `YOUR_CLIENT_ID`
  - `client_secret`: `YOUR_CLIENT_SECRET`
  - `redirect_uri`: `http://localhost:8080`
  - `code`: `YOUR_CODE`

## Step 4: Save the Response

You'll get a response like:
```json
{
  "access_token": "1000.abc123...",
  "refresh_token": "1000.def456...",
  "expires_in": 3600,
  "token_type": "Bearer"
}
```

**Save the `refresh_token`** - this is what your app will use!

## Step 5: Update Your .env File

Edit your `.env` file:
```
ZOHO_CLIENT_ID=your_client_id_here
ZOHO_CLIENT_SECRET=your_client_secret_here  
ZOHO_REFRESH_TOKEN=your_refresh_token_here
ZOHO_ORGANIZATION_ID=856048585
```

## Step 6: Test the Connection

Visit: http://localhost:5000/api/sync_zoho_pos

You should see either:
- ✅ "Synced X tablet POs" (success!)
- ❌ Error message (we'll debug together)

## Common Issues & Fixes

**"Invalid Client"**
- Double-check Client ID and Client Secret
- Make sure redirect URI is exactly `http://localhost:8080`

**"Invalid Code"**  
- Authorization codes expire quickly (15 minutes)
- Get a fresh code and exchange immediately

**"Invalid Grant"**
- Make sure you're using `authorization_code` grant type
- Check that all parameters are exactly correct

**"Invalid Scope"**
- Use `ZohoInventory.FullAccess.all` for the scope
- Make sure you granted permissions during authorization

## Need Help?

If you get stuck on any step, just let me know:
1. **Which step** you're on
2. **What error** you're seeing  
3. **Screenshot** if helpful

I'll help you debug it!
