# Connecting real Garmin data (Terra) to CareMate

The code is fully built and deployed. It activates the moment the three Terra keys
exist in the environment. Until then, the wearable card stays in demo mode.

## Your 10-minute checklist

1. **Create a Terra developer account**: https://dashboard.tryterra.co (free tier).
2. In the Terra dashboard, open **Connections** and enable **Garmin**
   (enable Fitbit / Oura / Withings too if you want, the app already supports them).
3. Under **API settings**, set the **webhook / destination URL** to:
   `https://mycaremate.me/api/terra/webhook`
4. Copy these three values from the dashboard:
   - Dev ID
   - API key
   - Signing secret
5. In **Vercel → CareMate project → Settings → Environment Variables**, add:
   - `TERRA_DEV_ID` = your dev id
   - `TERRA_API_KEY` = your API key
   - `TERRA_SIGNING_SECRET` = your signing secret
   Then redeploy (Deployments → Redeploy) so they take effect.
   For local testing, add the same three lines to `.env`.

## What happens once the keys are in

- The **Garmin button** on the dashboard stops creating demo data and instead sends
  you to Garmin Connect's real login (hosted by Terra). You grant access once.
- As your watch syncs, Terra pushes your **steps, sleep, resting HR, HRV** to
  `/api/terra/webhook`; CareMate stores one row per day (`WearableMetric`).
- The dashboard card switches to **live data** and the "Demo data" badge disappears.
- **Tomo reacts to your real recovery**, and every day you hit **8,000+ verified
  steps earns +15 XP** toward his evolution (watch-verified, so it can't be faked).
- Disconnect works from the same card and revokes the link.

## How to verify it works

1. Connect Garmin from the dashboard, approve on Garmin's page.
2. Terra sends an `auth` webhook, the card should show "Garmin" without the demo badge.
3. After your next watch sync (or use Terra's dashboard "generate test data" button),
   real numbers appear on the card and Tomo's recovery uses them.
