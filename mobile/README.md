# Aide for Android (Expo)

The main product: a native Android app (iOS later, same code) for the Aide assistant. It talks to the
Python backend in the repo root through the same JSON API as the web app at `/app`.

**Screens:** sign in with an email or SMS code, in-app consent, Connect Google (or skip), Today
(greeting, approvals, open loops with Draft / Done / Snooze, calendar, goals, subscriptions), Chat
(text, photos, camera, PDFs, text files, voice notes, suggestion chips), Approvals (numbered slips with
the exact details), and More: Activity, Goals, Standing tasks, Memory, Skills, Money, Vault and Settings.
Push notifications arrive for briefs, task results and anything the assistant sends on its own.
Tapping one opens the chat.

## Run it

```bash
cd mobile
npm install
EXPO_PUBLIC_API_URL=http://<your-computer's-LAN-IP>:8000 npx expo start
```

The backend must be reachable from the phone. Use your computer's LAN IP, or `http://10.0.2.2:8000`
from the Android emulator. In development, sign-in codes are printed in the backend log.

The app uses native modules (notifications, audio recording, secure storage), so use a development
build rather than Expo Go:

```bash
npx eas-cli@latest login
npx eas-cli@latest init                       # writes the EAS projectId into app.json
npx eas-cli@latest build -p android --profile development   # installable APK with the dev client
```

## Release builds

| Profile | Output | Use |
| --- | --- | --- |
| `development` | APK with dev client | Daily development on a phone |
| `preview` | APK | Share with design partners (install link from EAS) |
| `production` | AAB | Upload to Google Play |

Before a release:

1. Set `extra.apiUrl` in `app.json` (or `EXPO_PUBLIC_API_URL` in the EAS profile) to the deployed backend's HTTPS URL.
2. Push notifications on Android need Firebase Cloud Messaging: create a Firebase project, then add its
   FCM V1 service-account key with `npx eas-cli@latest credentials`. Without it the app still works, with no push.
3. Replace the placeholder icon and splash images in `assets/images/`.
4. Change `android.package` (`app.aide.assistant`) if you want a different Play Store ID. It can't change after the first upload.

## Checks

```bash
npx tsc --noEmit                               # typecheck
npx expo export --platform web                 # bundles every screen; also gives a browser build for quick testing
```

Code layout: `src/app/` holds the screens (Expo Router; `(tabs)/` is the tab bar), `src/lib/` the API
client, auth, push and theme, and `src/components/ui.tsx` the shared UI pieces.
