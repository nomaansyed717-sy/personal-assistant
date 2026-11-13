# Publishing Aide on Google Play

## Two Android builds

| Build | Where it comes from | Phone agent | How people install it |
| --- | --- | --- | --- |
| **Play Store** (`aide-play-bundle`, .aab) | `Android release (Play Store)` workflow | No | Google Play |
| **Full** (`aide-android-apk`) | `Android APK` workflow | Yes | Direct download (sideload) |
| **Lite** (`aide-android-apk-lite`) | `Android APK` workflow | No | Direct download, same as the Play build |

Why the Play build has no phone agent: Google Play's policy on the AccessibilityService API says using it to
"autonomously initiate, plan, and execute actions or decisions is strictly prohibited" for apps that are not
accessibility tools, and assistants can't claim to be accessibility tools. The phone agent plans and acts on its
own, so it can't ship on Play. In the Play build, **Do it** sends the errand to chat, and the assistant runs it
on the web with its secure browser (up to the payment step, after the user's yes). Connected apps (Zapier,
Notion, GitHub…) and automations work the same in every build.

Source: <https://support.google.com/googleplay/android-developer/answer/10964491>

## One-time setup

1. **Play Console account.** Create one at <https://play.google.com/console> (one-time fee). Use an
   organisation account for SuperBeez Commerce Pvt Ltd if you want the company name on the listing.
2. **Upload key.** On your computer:

   ```bash
   keytool -genkeypair -v -keystore aide-upload.jks -alias aide-upload -keyalg RSA -keysize 2048 -validity 10000
   base64 -i aide-upload.jks | pbcopy        # macOS: copies the keystore as text
   ```

   Keep `aide-upload.jks` and its passwords somewhere safe (a password manager). Google re-signs releases with
   its own app signing key, so losing the upload key is recoverable, but it's a support ticket.
3. **GitHub secrets** (repo > Settings > Secrets and variables > Actions > New repository secret):
   `ANDROID_UPLOAD_KEYSTORE_BASE64` (the copied text), `ANDROID_UPLOAD_KEYSTORE_PASSWORD`,
   `ANDROID_UPLOAD_KEY_ALIAS` (`aide-upload`), `ANDROID_UPLOAD_KEY_PASSWORD`.
4. **Build.** Actions > *Android release (Play Store)* > Run workflow, or push a tag `android-v1.0.0`. Download
   `aide-play-bundle` from the run.
5. **Create the app** in Play Console: name *Aide*, default language English (India), App, Free.
6. **Internal testing** > Create release > upload the .aab > add testers' emails > roll out. Testers install from
   the opt-in link. Move to closed, then production testing when you're happy. New personal developer accounts
   must run a closed test with at least 12 testers for 14 days before production.

## Store listing

- **App name:** Aide: your chief of staff
- **Short description (80):** Tracks what you've promised, books what you ask for, and asks before it pays.
- **Full description:**

  > Aide is a personal AI assistant built in India for the world.
  >
  > • Your day in one place: what you owe people, what they owe you, today's calendar and your goals.
  > • Replies drafted in your voice. Nothing is sent until you say yes.
  > • Errands on the web: compare options, fill forms, book up to the payment step. You always pay yourself.
  > • Connect your apps: Notion, GitHub, Stripe, and 8,000+ more through Zapier.
  > • Automations: "when an invoice email arrives, note the due date and remind me".
  > • Speak in Hindi, Marathi, Tamil, Telugu, Bengali and more.
  > • Standing tasks that keep running: price watches, slot checks, invoice chasers.
  > • Private by design: per-user encryption, memory you can see and delete, never used for ads.

- **Category:** Productivity. **Tags:** assistant, productivity, AI.
- **Privacy policy URL:** `https://<your server>/privacy` (for example `https://aide-server-y2eu.onrender.com/privacy`).
- **Graphics:** 512×512 icon (`mobile/assets/images/icon.png`), 1024×500 feature graphic, 2–8 phone screenshots
  (Today, Chat, Approvals, Connected apps, Automations).

## App content answers

- **Ads:** No ads.
- **Target audience:** 18 and over.
- **Data safety** (collected, encrypted in transit, users can request deletion):
  - Personal info: name, email address, phone number (account management, app functionality).
  - Messages: emails (Gmail, when connected), in-app messages (app functionality).
  - Calendar events (app functionality).
  - Audio: voice notes and dictation, only when the user taps the mic (app functionality; not stored after
    transcription).
  - Photos and files the user sends in chat (app functionality).
  - App activity: in-app actions (analytics, only with the user's opt-in under *Help improve the product*).
  - Not shared with third parties for advertising. Processing partners: Anthropic (AI), Google (Gmail and
    Calendar, at the user's request), Sarvam or OpenAI (speech to text, when enabled).
- **Permissions to justify:** `RECORD_AUDIO` (dictation and voice notes), `CAMERA` (photos the user sends),
  `POST_NOTIFICATIONS` (approvals and replies). The Play build has no accessibility service, so no
  AccessibilityService declaration is needed.
- **Financial features:** None. Aide never makes payments.

## The full build (phone agent), outside Play

It's distributed as a direct download. Before turning the service on, the app shows a prominent disclosure and
an **Agree and turn on** button (recorded as an `accessibility` consent), and the service's own description
repeats what it reads and why. On phones in India, Play Protect blocks installing sideloaded apps that declare
an accessibility service; the user has to pause Play Protect scanning for the install (Play Store > profile >
Play Protect > settings) or install from a computer with `adb install`.
