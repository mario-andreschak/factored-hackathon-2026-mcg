# Savia eyes and voice

`Eyes.tsx`, `eyes.module.css`, `audio.ts`, `utteranceObserver.ts` and
`../../public/avatar-audio-capture.js` come from
[flujo-avatar](https://github.com/flujo-app/flujo-avatar) at
`23955370541c93786db1840a40cf31c87aae2e90`. Edit them there and copy again.
They are formatted with this project's Prettier. Two local changes: `Eyes.tsx` drops the Next.js `'use client'` line and skips
its animation loop where `matchMedia` is missing (jsdom tests).

`useSaviaVoice.ts` is Savia's own hook. It keeps flujo-avatar's microphone
capture and end-of-utterance detection, and replaces the native conversation
transport: speech is transcribed and sent through the normal Savia chat, and
the bank's actual reply is read aloud. The voice layer never answers on its own.
