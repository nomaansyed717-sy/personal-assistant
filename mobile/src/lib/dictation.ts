import * as Localization from 'expo-localization';
import { ExpoSpeechRecognitionModule, useSpeechRecognitionEvent } from 'expo-speech-recognition';
import { useRef, useState } from 'react';

/** Live dictation with the phone's own speech recognition: free, fast, and good at Indian languages. */
export function dictationLocale(voiceLanguage: string | undefined): string {
  if (voiceLanguage && voiceLanguage !== 'auto') return voiceLanguage;
  const tag = Localization.getLocales()[0]?.languageTag;
  return tag && /^[a-z]{2,3}-[A-Z]{2}$/.test(tag) ? tag : 'en-IN';
}

export function useDictation(onText: (text: string, final: boolean) => void) {
  const [listening, setListening] = useState(false);
  const [error, setError] = useState('');
  const handler = useRef(onText);
  handler.current = onText;

  useSpeechRecognitionEvent('start', () => setListening(true));
  useSpeechRecognitionEvent('end', () => setListening(false));
  useSpeechRecognitionEvent('result', e => {
    const text = e.results[0]?.transcript;
    if (text) handler.current(text, e.isFinal);
  });
  useSpeechRecognitionEvent('error', e => {
    setListening(false);
    if (e.error === 'no-speech' || e.error === 'aborted') return;
    setError(e.error === 'language-not-supported'
      ? 'Your phone can’t dictate in that language yet. Pick another under Settings > Voice language.'
      : e.error === 'not-allowed' ? 'Microphone permission is off. Turn it on in your phone’s settings.'
        : 'Dictation stopped. Try again, or hold the mic to send a voice note.');
  });

  const available = (): boolean => {
    try { return ExpoSpeechRecognitionModule.isRecognitionAvailable(); } catch { return false; }
  };

  const start = async (lang: string): Promise<boolean> => {
    setError('');
    if (!available()) return false;
    const perm = await ExpoSpeechRecognitionModule.requestPermissionsAsync();
    if (!perm.granted) { setError('Microphone permission is off. Turn it on in your phone’s settings.'); return true; }
    ExpoSpeechRecognitionModule.start({ lang, interimResults: true, continuous: false, addsPunctuation: true });
    return true;
  };

  const stop = () => { try { ExpoSpeechRecognitionModule.stop(); } catch { /* not running */ } };

  return { listening, error, start, stop, available };
}
