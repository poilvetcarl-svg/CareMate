# CareMate Android app (Health Connect)

The full CareMate web product in a WebView, plus the one thing the web cannot
do: reading REAL watch data (steps, sleep, resting heart rate, HRV, SpO2)
through Google Health Connect and syncing it to the backend. This is what
makes Tomo's activity XP verified instead of self-reported, for any watch
brand (Samsung, Garmin, Fitbit, Xiaomi, Amazfit...) at zero API cost.

This project SUPERSEDES the PWABuilder TWA in `android/` — same package name
(`com.mycaremate.app`), so publish this one to the Play Store instead.

## How it works
1. User signs into mycaremate.me inside the app's WebView.
2. User taps "Sync my watch" → Health Connect permission sheet appears.
3. App calls `POST /api/wearable/link` (using the WebView session cookie) and
   receives a long-lived sync token.
4. App reads the last 7 days from Health Connect, aggregates per day, and
   posts to `POST /api/wearable/sync` (Bearer token). A WorkManager job
   repeats this every ~6 hours.
5. The backend upserts `WearableMetric` rows → Tomo mood, the recovery card,
   and the +15 XP "active day" (8000+ steps) all use this verified data.

Both endpoints are already LIVE on production and tested.

## Build steps (Carl)
1. Install Android Studio (free): https://developer.android.com/studio
2. Open Android Studio → "Open" → select this `android-app` folder.
3. Let it sync Gradle (first time downloads dependencies; accept any prompt
   to upgrade Gradle/AGP versions if suggested).
4. Generate the launcher icon: right-click `app` → New → Image Asset → pick
   `static/img/favicon-512.png` from the main repo → finish. Then add
   `android:icon="@mipmap/ic_launcher"` to the `<application>` tag in
   `AndroidManifest.xml` (a comment marks the spot).
5. Run on your own phone first (USB, developer mode) → sign in → tap
   "Sync my watch" → check your dashboard shows real watch data.
6. For the Play Store: Build → Generate Signed App Bundle (.aab), create the
   keystore when prompted and BACK IT UP (losing it means losing the app
   listing). Upload the .aab in Play Console.

## Play Store notes
- Health Connect apps must declare the health data use in the Play Console
  Data Safety form (read-only: activity, sleep, vitals; purpose: showing the
  user their own prevention insights).
- Google requires a privacy policy URL: use https://mycaremate.me/privacy
  (already states health data handling).

## Honest limitations
- Written and reviewed, but NOT compiled here (this machine has no Android
  SDK). Expect Android Studio to surface small version alignment prompts on
  first sync; accept its suggestions.
- Apple Watch/iPhone users are not covered by Health Connect; that requires
  an iOS app with HealthKit later.
