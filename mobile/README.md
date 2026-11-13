# Aide for Android (Expo)

The main product: a native Android app (iOS later, same code) for the Aide assistant. It talks to the
Python backend in the repo root through the same JSON API as the web app at `/app`.

**Screens:** sign in with an email or SMS code, in-app consent, Connect Google (or skip), Today
(greeting, approvals, open loops with Draft / Done / Snooze, calendar, goals, subscriptions), Chat
(text, photos, camera, PDFs, text files, voice notes, suggestion chips), Approvals (numbered slips with
the exact details), and More: Activity, Goals, Standing tasks, Memory, Skills, Money, Vault and Settings.
Push notifications arrive for briefs, task results and anything the assistant sends on its own.
Tapping one opens the chat.

## The phone agent ("Do it" tab)

Tell Aide what to do ("book a sleeper bus from Pune to Aurangabad on Friday night under ₹1,500", "book an auto to
the station", "find the cheapest flight to Dubai on 5 December") and it does it in the apps on your phone:
it opens the right app, searches, compares, fills in the details and gets to checkout.

- **How it works:** a native Android accessibility service (`modules/phone-agent`, Kotlin) reads the screen, the
  backend (`app/phone_agent.py`) decides the next step, and the service taps, types, scrolls or opens an app.
  The loop runs natively, so it keeps going while other apps are on screen.
- **You stay in charge:** it stops and hands over for every **login, OTP and captcha**, and for **every payment**.
  It goes as far as the final review screen, then notifies you with exactly what's about to be paid. It never
  types into password fields, never types card numbers or PINs, and never operates UPI, wallet or banking apps.
  These rules are enforced on the phone and again on the server, whatever the AI decides.
- **A Stop button floats on screen** the whole time a task runs. After you sign in or pay, tap **Resume** on it.
- Tasks can be typed in the "Do it" tab, or proposed in Chat and approved in Approvals.
- **Turning it on:** the "Do it" tab shows what the agent can access, then opens Android's accessibility settings
  where you switch on "Aide phone agent".

**Google Play:** apps that use the accessibility service for anything other than helping people with disabilities
must declare it in the Play Console, show a prominent disclosure in the app (the "Do it" tab does) and pass review.
Plan for that before the Play Store launch. Sideloaded APKs (below) work without it.

## Get an APK without EAS

Every push that changes `mobile/` runs the **Android APK** GitHub Action, which builds an installable APK (with the
phone agent) and attaches it to the run as `aide-android-apk`. Set the repository variable `AIDE_API_URL` to your
backend's URL first. Download the artifact, unzip it, and install the APK on your phone.

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
