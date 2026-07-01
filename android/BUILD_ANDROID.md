# Publishing CareMate to the Google Play Store

CareMate is already an installable PWA (`https://mycaremate.me/manifest.webmanifest`).
This wraps that exact PWA into a real Play Store app using a **TWA** (Trusted Web
Activity) via **Bubblewrap**. You reuse 100% of the web app, no separate codebase.

## What you need first
- **Node.js 18+** and **JDK 17** installed
- A **Google Play Developer account** (one-time $25): https://play.google.com/console
- ~30 minutes

## 1. Install Bubblewrap
```bash
npm install -g @bubblewrap/cli
```

## 2. Generate the Android project
From this `android/` folder:
```bash
bubblewrap init --manifest https://mycaremate.me/manifest.webmanifest
```
When prompted:
- **Package name / Application ID**: `com.mycaremate.app`
- **Launcher name**: `CareMate`
- Accept the colors/icons it pulls from the web manifest (coral `#FF6B6B`)
- Let it create a **signing key** (or point it at `android.keystore`, alias `caremate`)

(The `twa-manifest.json` in this folder mirrors these settings if you prefer to reuse it.)

## 3. Build the app bundle
```bash
bubblewrap build
```
This produces `app-release-bundle.aab` (upload to Play) and `app-release-signed.apk`
(for local testing). It also prints your **SHA-256 fingerprint**. If you miss it:
```bash
keytool -list -v -keystore android.keystore -alias caremate
```
Copy the `SHA256:` value (format `AB:CD:...`).

## 4. Verify domain ownership (removes the browser URL bar)
The site already serves `/.well-known/assetlinks.json` and reads the fingerprint from
an env var. In **Vercel → CareMate project → Settings → Environment Variables**, add:
- `ANDROID_CERT_SHA256` = the SHA-256 fingerprint from step 3
- `ANDROID_PACKAGE` = `com.mycaremate.app`  (only if you changed the default)

Redeploy (or it applies on next deploy). Confirm it works:
```bash
curl https://mycaremate.me/.well-known/assetlinks.json
```
It should now list your package + fingerprint. Google verifies this to hide the URL bar.

## 5. Publish on Play Console
1. Create a new app → upload `app-release-bundle.aab` to a testing track first.
2. Store listing: name **CareMate**, short + full description, the coral icon, and a
   few phone screenshots (open `mycaremate.me` on a phone and screenshot the dashboard,
   assessment, and teleconsultation).
3. Set the **Privacy Policy URL**: `https://mycaremate.me/privacy` (already live).
4. Fill the **Data safety** form using `mycaremate.me/privacy` as your reference
   (account details, health inputs, consultation summaries, wearable metrics — demo).
5. Complete content rating, then submit for review.

## Keep safe
- **Back up `android.keystore` + its passwords.** You need the same key to ship every
  future update; losing it means you cannot update the app.

## Later: push notifications
When you want vaccine-reminder push, re-run with notifications enabled (or move to a
Capacitor wrapper). Ask and I'll set it up.
