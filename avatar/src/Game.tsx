import { lazy, Suspense, useCallback, useEffect, useRef, useState } from 'react';
import { ArrowRight, Check, ChevronRight, Compass, Leaf, Mic, MicOff, Pause, Play, Volume2, VolumeX, X, Zap } from 'lucide-react';
import { getScenes } from './world/scenes';
import { formatMessage, getInitialLocale, getMessages, localeTag, persistLocale } from './locale';
import type { Locale } from './locale';
import { AVATARS, classifyMood, demoReply, sceneForIntent } from './domain';
import type { AvatarConfig, AvatarId, Phase, Transcript } from './domain';
import Workbench from './Workbench';
import type { WorkbenchHandle } from './Workbench';
import { useVoice } from './useVoice';
import { useRouterVoice } from './useRouterVoice';
import { useNativeRouterVoice } from './useNativeRouterVoice';
import { useGeminiLive } from './useGeminiLive';
import { usePersonaPlex } from './experiments/usePersonaPlex';
import { useAmbience } from './useAmbience';
import { isNativeReadRequest } from './nativeReadBridge';
import { voiceMilestone } from './voiceTelemetry';
import { useInquiryVoiceUpdates } from './useInquiryVoiceUpdates';
import './game.css';

const DEFAULT_CONFIG: AvatarConfig = { voiceAvailable: false, backendAvailable: false, saviaUrl: '', mode: 'demo', realtimeModel: '', voiceProvider: 'none' };
const World = lazy(() => import('./world/World'));
const wait = (ms: number) => new Promise(resolve => setTimeout(resolve, ms));
function CharacterIcon({ id }: { id: AvatarId }) { return id === 'moss' ? <Leaf size={19} /> : id === 'orbit' ? <Compass size={19} /> : <Zap size={19} />; }
interface NativeRead {
  message: string; epoch: number; abort: AbortController; finishHold: () => void;
  nativeOwner?: symbol;
  deadline: number; checking: boolean; resumeAfterCheck?: boolean; timer?: ReturnType<typeof setTimeout>;
}

export default function Game() {
  const [locale, setLocale] = useState<Locale>(getInitialLocale);
  const copy = getMessages(locale), characters = copy.characters, scenes = getScenes(locale);
  const [config, setConfig] = useState(DEFAULT_CONFIG);
  const [awakened, setAwakened] = useState(false), [entered, setEntered] = useState(false);
  const [avatar, setAvatar] = useState<AvatarId>('moss'), [sceneIndex, setSceneIndex] = useState(0);
  const [paused, setPaused] = useState(false), [typing, setTyping] = useState(false);
  const [chapters, setChapters] = useState(false), [computerOpen, setComputerOpen] = useState(false);
  const [automatic, setAutomatic] = useState(true), [subtitles, setSubtitles] = useState(false);
  const [reducedMotion, setReducedMotion] = useState(() => window.matchMedia('(prefers-reduced-motion: reduce)').matches);
  const [draft, setDraft] = useState(''), [caption, setCaption] = useState('');
  const [history, setHistory] = useState<Transcript[]>([]), [historyOpen, setHistoryOpen] = useState(false);
  const [previewPhase, setPreviewPhase] = useState<Phase>('idle'), [previewLevel, setPreviewLevel] = useState(0);
  const [notice, setNotice] = useState(''), [taskBusy, setTaskBusy] = useState(false);
  const [preview, setPreview] = useState(false);
  const audioProvider = config.voiceProvider === 'gemini-live' ? 'Google' : config.voiceProvider === 'openai-realtime' ? 'OpenAI' : config.voiceProvider === 'personaplex' ? 'PersonaPlex / OpenRouter' : 'OpenRouter / OpenAI';
  const audioNotice = formatMessage(copy.game.audioNotice, { provider: audioProvider });
  const pointer = useRef({ x: 0, y: 0 }), workbench = useRef<WorkbenchHandle>(null);
  const sceneEpoch = useRef(0), taskEpoch = useRef(0), bankSeen = useRef(false), bankSessionKnown = useRef(false);
  const taskOwner = useRef<symbol | null>(null), personaEngaged = useRef(false), nativeEngaged = useRef(false);
  const liveVoice = useRef({ connected: false, native: false });
  const pendingNativeRead = useRef<NativeRead | null>(null), activeNativeRead = useRef<NativeRead | null>(null);
  const nativeBridge = useRef({ observe: (_text: string) => {}, resume: () => {}, cancel: () => {} });
  const configLoaded = useRef(false);
  const ambience = useAmbience();
  const state = useRef({ config, avatar, automatic, entered, awakened, taskBusy, computerOpen, locale }); state.current = { config, avatar, automatic, entered, awakened, taskBusy, computerOpen, locale };
  useEffect(() => { document.documentElement.lang = localeTag(locale); }, [locale]);
  const loadConfig = useCallback(async () => {
    try {
      const response = await fetch('/api/avatar/config', { signal: AbortSignal.timeout(5000) });
      if (response.ok) { const next: AvatarConfig = await response.json(); configLoaded.current = true; setConfig(next); return next; }
    }
    catch { setPreview(true); }
    return undefined;
  }, []);
  useEffect(() => { void loadConfig(); }, [loadConfig]);
  const computerLoaded = useCallback(() => {
    void loadConfig();
    const epoch = taskEpoch.current;
    void fetch('/savia/api/auth/me', { signal: AbortSignal.timeout(5000) }).then(response => {
      if (epoch === taskEpoch.current && response.ok) { bankSessionKnown.current = true; nativeBridge.current.resume(); }
      void response.body?.cancel().catch(() => {});
    }).catch(() => {});
  }, [loadConfig]);

  const transcript = useCallback((id: string, role: 'user' | 'assistant', text: string, done: boolean) => {
    if (!text.trim()) return;
    setHistory(old => { const found = old.findIndex(t => t.id === id); return found < 0 ? [...old.slice(-79), { id, role, text, ...(role === 'assistant' ? { avatar: state.current.avatar } : {}) }] : old.map((t, i) => i === found ? { ...t, text } : t); });
    if (role === 'assistant') setCaption(text);
    if (role === 'user' && done) {
      setEntered(true);
      if (state.current.automatic) { const mood = classifyMood(text); setAvatar(mood.avatar); setSceneIndex(sceneForIntent(mood.intent)); }
    }
  }, []);
  const delegate = useCallback(async (message: string, execution?: { signal?: AbortSignal }) => {
    const epoch = taskEpoch.current;
    setEntered(true); setComputerOpen(true);
    if (!state.current.config.backendAvailable) throw new Error(getMessages(state.current.locale).game.saviaNotConnected);
    if (taskOwner.current) throw new Error(getMessages(state.current.locale).game.previousRequestBusy);
    const owner = Symbol('savia-read'); taskOwner.current = owner;
    setTaskBusy(true);
    voiceMilestone('task-start');
    try {
      await wait(400);
      if (epoch !== taskEpoch.current) throw new Error(getMessages(state.current.locale).game.previousRequestWithheld);
      if (execution?.signal?.aborted) throw new Error(getMessages(state.current.locale).game.requestStoppedBeforeSend);
      if (!workbench.current) throw new Error(getMessages(state.current.locale).game.poolOpening);
      const result = await workbench.current.execute(message, execution);
      voiceMilestone('task-complete');
      if (epoch !== taskEpoch.current) throw new Error(getMessages(state.current.locale).game.previousResponseWithheld);
      bankSeen.current = true; return result;
    } finally {
      if (taskOwner.current === owner) { taskOwner.current = null; if (epoch === taskEpoch.current) setTaskBusy(false); }
    }
  }, []);
  const observedTranscript = useCallback((id: string, text: string) => {
    setHistory(old => [...old.slice(-79), { id, role: 'user', text }]); setEntered(true);
    // The native role remains the operator's primed role; observed intent can
    // change its scenery without pretending the voice model changed character.
    if (state.current.automatic) setSceneIndex(sceneForIntent(classifyMood(text).intent));
    nativeBridge.current.observe(text);
  }, []);
  const initialTranscript = useCallback((id: string, text: string) => {
    // Initial recognition selects presentation and records the first request.
    // It does not admit a bank job; that integration needs its own qualification.
    setHistory(old => old.some(item => item.id === id) ? old : [...old.slice(-79), { id, role: 'user', text }]);
    setEntered(true);
    if (state.current.automatic) setSceneIndex(sceneForIntent(classifyMood(text).intent));
  }, []);
  const options = { avatar, locale, onTranscript: transcript, onUserUtterance: () => setEntered(true),
    backgroundAsr: ['personaplex', 'openrouter-native'].includes(config.voiceProvider ?? '') && Boolean(config.backgroundAsrAvailable),
    observerPaused: computerOpen || taskBusy, onObservedTranscript: observedTranscript,
    onObserverError: () => setNotice(getMessages(state.current.locale).game.backgroundTranscriptionUnavailable),
    initialRole: Boolean(config.initialVoiceAvailable), onInitialTranscript: initialTranscript,
    onInitialSelection: (id: AvatarId) => { state.current.avatar = id; setAvatar(id); setEntered(true); },
    onWorld: (id: AvatarId, scene: number) => { if (state.current.automatic) { setAvatar(id); setSceneIndex(scene); } }, onTask: delegate };
  const realtime = useVoice(options), router = useRouterVoice(options), gemini = useGeminiLive(options), personaplex = usePersonaPlex(options);
  const native = useNativeRouterVoice({ ...options, onInterrupted: () => setCaption(''), onTranscript: (id, role, text, done) => {
    if (role === 'assistant' && !done) setCaption(text);
    else {
      transcript(id, role, text, done);
      if (role === 'user' && done) nativeBridge.current.observe(text);
    }
  }, onObservedTranscript: (id, text) => {
    transcript(id, 'user', text, true); nativeBridge.current.observe(text);
  } });
  const voice = config.voiceProvider === 'gemini-live' ? gemini : config.voiceProvider === 'openrouter-native' ? native : config.voiceProvider === 'openrouter' ? router : config.voiceProvider === 'personaplex' ? personaplex : realtime;
  const inquiryVoice = useInquiryVoiceUpdates({ enabled: config.voiceProvider === 'openrouter-native' && native.connected,
    locale, getOwner: native.getSessionOwner, sendResult: native.sendTaskResult,
    onError: () => setNotice(getMessages(state.current.locale).game.previousResponseWithheld) });
  liveVoice.current = { connected: voice.connected, native: native.connected };
  useEffect(() => {
    if (config.voiceProvider !== 'gemini-live') gemini.disconnect();
    if (config.voiceProvider !== 'openrouter') router.disconnect();
    if (config.voiceProvider !== 'openrouter-native') native.disconnect();
    if (config.voiceProvider !== 'personaplex') personaplex.disconnect();
    if (config.voiceProvider !== 'openai-realtime') realtime.disconnect();
  }, [config.voiceProvider, gemini.disconnect, native.disconnect, router.disconnect, personaplex.disconnect, realtime.disconnect]);
  useEffect(() => {
    if (personaplex.connected || personaplex.connecting) personaEngaged.current = true;
    else if (personaEngaged.current) {
      personaEngaged.current = false; nativeBridge.current.cancel();
      // An admitted UI read continues; its pre-submit signal is no longer used.
      activeNativeRead.current?.abort.abort(); void loadConfig();
    }
  }, [personaplex.connected, personaplex.connecting, loadConfig]);
  useEffect(() => {
    if (native.connected || native.connecting) nativeEngaged.current = true;
    else if (nativeEngaged.current) {
      nativeEngaged.current = false; nativeBridge.current.cancel();
      activeNativeRead.current?.abort.abort(); void loadConfig();
    }
  }, [native.connected, native.connecting, loadConfig]);
  const nativeConversation = config.voiceProvider === 'openrouter-native' && (voice.connected || voice.connecting);
  const phase = taskBusy && !nativeConversation ? 'thinking' : voice.connected || voice.connecting ? voice.phase : previewPhase;
  const level = voice.connected || voice.connecting ? voice.audioLevel : previewLevel;
  const initialListening = config.voiceProvider === 'personaplex' && personaplex.initialListening;
  const stopPreview = useCallback(() => { sceneEpoch.current++; setPreviewPhase('idle'); setPreviewLevel(0); }, []);
  const interrupt = useCallback(() => { stopPreview(); setCaption(''); realtime.interrupt(); native.interrupt(); router.interrupt(); gemini.interrupt(); personaplex.interrupt(); }, [stopPreview, realtime.interrupt, native.interrupt, router.interrupt, gemini.interrupt, personaplex.interrupt]);
  const say = useCallback((text: string, id: AvatarId = state.current.avatar) => {
    stopPreview(); setCaption(text);
    setHistory(old => [...old.slice(-79), { id: crypto.randomUUID(), role: 'assistant', text, avatar: id }]);
  }, [stopPreview]);
  const cancelPendingRead = useCallback(() => {
    const read = pendingNativeRead.current; pendingNativeRead.current = null;
    if (read) { clearTimeout(read.timer); read.abort.abort(); read.finishHold(); }
  }, []);
  const resumeNativeRead = useCallback(async () => {
    const read = pendingNativeRead.current;
    if (!read || read.epoch !== taskEpoch.current) return;
    const ownsNativeVoice = () => read.nativeOwner !== undefined &&
      state.current.config.voiceProvider === 'openrouter-native' && liveVoice.current.native &&
      native.getSessionOwner() === read.nativeOwner;
    const ownsVoice = () => read.nativeOwner === undefined ? liveVoice.current.connected : ownsNativeVoice();
    if (read.checking) { read.resumeAfterCheck = true; return; }
    if (Date.now() >= read.deadline || !state.current.computerOpen || !ownsVoice()) { cancelPendingRead(); return; }
    read.checking = true;
    try {
      const response = await fetch('/savia/api/auth/me', { credentials: 'same-origin', signal: AbortSignal.any([read.abort.signal, AbortSignal.timeout(5000)]) });
      await response.body?.cancel().catch(() => {});
      if (pendingNativeRead.current !== read || read.epoch !== taskEpoch.current || read.abort.signal.aborted) return;
      if (response.status === 401) { setCaption(getMessages(state.current.locale).game.signInAtPool); return; }
      if (!response.ok) throw new Error(getMessages(state.current.locale).game.signInCheckFailed);
      if (Date.now() >= read.deadline || !state.current.computerOpen || !ownsVoice()) { cancelPendingRead(); return; }
      bankSessionKnown.current = true;
      pendingNativeRead.current = null; clearTimeout(read.timer); activeNativeRead.current = read;
      setCaption(getMessages(state.current.locale).game.lookTogether);
      try {
        const result = await delegate(read.message, { signal: read.abort.signal });
        if (read.epoch === taskEpoch.current) {
          if (ownsNativeVoice()) {
            let receipt: Response;
            try {
              receipt = await fetch('/api/avatar/native-result-receipt', { method: 'POST', headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ reply: result.reply, locale: state.current.locale }), signal: AbortSignal.timeout(5000) });
            } catch (error) {
              if (read.epoch === taskEpoch.current && !ownsNativeVoice()) { say(result.reply); return; }
              throw error;
            }
            if (read.epoch !== taskEpoch.current || !ownsNativeVoice()) {
              await receipt.body?.cancel().catch(() => {});
              if (read.epoch === taskEpoch.current) say(result.reply);
              return;
            }
            if (!receipt.ok) throw new Error(getMessages(state.current.locale).game.previousResponseWithheld);
            const bound = await receipt.json();
            if (read.epoch !== taskEpoch.current) return;
            if (!ownsNativeVoice()) { say(result.reply); return; }
            if (typeof bound.taskId !== 'string' || !native.sendTaskResult(bound.taskId, read.nativeOwner))
              throw new Error(getMessages(state.current.locale).game.previousResponseWithheld);
            setCaption(result.reply);
          } else say(result.reply);
        }
      } finally {
        if (activeNativeRead.current === read) activeNativeRead.current = null;
        read.finishHold();
      }
    } catch (e) {
      if (read.epoch === taskEpoch.current && !read.abort.signal.aborted) {
        setNotice(e instanceof Error ? e.message : getMessages(state.current.locale).game.readFailed);
      }
      if (pendingNativeRead.current === read) cancelPendingRead();
    } finally {
      read.checking = false;
      if (pendingNativeRead.current === read && read.resumeAfterCheck) {
        read.resumeAfterCheck = false; queueMicrotask(() => nativeBridge.current.resume());
      }
    }
  }, [cancelPendingRead, delegate, native.getSessionOwner, native.sendTaskResult, say]);
  nativeBridge.current = {
    observe: text => {
      const available = state.current.config;
      if (!available.nativeReadBridgeAvailable || !available.backendAvailable || !voice.connected ||
        state.current.computerOpen || taskOwner.current || pendingNativeRead.current || activeNativeRead.current || !isNativeReadRequest(text)) return;
      const finishHold = available.voiceProvider === 'personaplex' ? personaplex.beginTaskHold() : available.voiceProvider === 'openrouter-native' ? () => {} : null;
      if (!finishHold) return;
      const nativeOwner = available.voiceProvider === 'openrouter-native' ? native.getSessionOwner() : null;
      if (available.voiceProvider === 'openrouter-native' && !nativeOwner) return;
      const read: NativeRead = { message: text.trim(), epoch: taskEpoch.current, ...(nativeOwner ? { nativeOwner } : {}), abort: new AbortController(), finishHold, deadline: Date.now() + 120000, checking: false };
      pendingNativeRead.current = read;
      read.timer = setTimeout(() => { if (pendingNativeRead.current === read) { cancelPendingRead(); setNotice(getMessages(state.current.locale).game.signInRequestExpired); } }, 120000);
      setEntered(true); setComputerOpen(true); setCaption(getMessages(state.current.locale).game.comeToPool);
    },
    resume: () => { void resumeNativeRead(); }, cancel: cancelPendingRead,
  };
  useEffect(() => {
    if (computerOpen && pendingNativeRead.current) void resumeNativeRead();
    else if (!computerOpen) cancelPendingRead();
  }, [computerOpen, resumeNativeRead, cancelPendingRead]);
  const showPreview = useCallback(() => {
    setPreview(true); setEntered(true);
    const epoch = sceneEpoch.current;
    setTimeout(() => { if (epoch === sceneEpoch.current) say(getMessages(state.current.locale).game.greeting, 'moss'); }, 1200);
  }, [say]);
  useEffect(() => {
    if (voice.error && awakened) {
      setNotice(voice.error);
      if (!entered) showPreview();
    }
  }, [voice.error, awakened, entered, showPreview]);
  const wake = async () => {
    if (awakened) return;
    setAwakened(true);
    if (!ambience.enabled) ambience.toggle();
    void document.documentElement.requestFullscreen?.().catch(() => {});
    const available = configLoaded.current ? config : await loadConfig();
    const connection = available?.voiceProvider === 'gemini-live' ? gemini : available?.voiceProvider === 'openrouter-native' ? native : available?.voiceProvider === 'openrouter' ? router : available?.voiceProvider === 'personaplex' ? personaplex : realtime;
    if (available?.voiceAvailable || available?.initialVoiceAvailable) {
      setPreview(false);
      if (available.voiceProvider === 'personaplex') {
        const nativeAvatar = available.voiceAvatar ?? 'moss'; if (!available.initialVoiceAvailable) setAvatar(nativeAvatar);
        await personaplex.connect(nativeAvatar, available.backgroundAsrAvailable, available.initialVoiceAvailable);
      } else await connection.connect();
    }
    else { await wait(850); showPreview(); }
  };
  const startVoice = async () => {
    setAwakened(true); setPreview(false); setNotice(''); setPaused(false);
    if (config.voiceProvider === 'personaplex') {
      const available = await loadConfig();
      if (!available?.voiceAvailable && !available?.initialVoiceAvailable) { setPreview(true); setNotice(copy.game.nativeAuditionEnded); return; }
      const nativeAvatar = available.voiceAvatar ?? 'moss'; if (!available.initialVoiceAvailable) setAvatar(nativeAvatar); await personaplex.connect(nativeAvatar, available.backgroundAsrAvailable, available.initialVoiceAvailable);
    }
    else await voice.connect();
  };
  const pickAvatar = (id: AvatarId) => {
    interrupt(); setAvatar(id); setAutomatic(false); setPaused(false); setEntered(true);
    if (config.voiceProvider === 'personaplex' && (voice.connecting || voice.connected && id !== (personaplex.voiceAvatar ?? config.voiceAvatar ?? 'moss'))) {
      personaplex.disconnect(); setPreview(true); say(characters[id].line, id); return;
    }
    voice.setPersona(id);
    if (voice.connected) voice.sendText(locale === 'pt' ? `Converse como ${characters[id].name}, ${characters[id].role}. Faça uma saudação curta em português do Brasil.` : `Conversa como ${characters[id].name}, ${characters[id].role}. Saluda brevemente en español latinoamericano.`);
    else say(characters[id].line, id);
  };
  const travel = () => {
    if (taskBusy) return;
    if (voice.connected && config.voiceProvider === 'personaplex') { setSceneIndex(i => (i + 1) % 10); return; }
    if (voice.connected && config.voiceProvider === 'openrouter-native') setSceneIndex(i => (i + 1) % 10);
    if (voice.connected) {
      voice.sendText(copy.game.travelInstruction); return;
    }
    say(characters[avatar].travel);
    const epoch = sceneEpoch.current;
    setTimeout(() => { if (epoch === sceneEpoch.current) setSceneIndex(i => (i + 1) % 10); }, avatar === 'moss' ? 2600 : 850);
  };
  const submit = async (event: React.FormEvent) => {
    event.preventDefault(); const message = draft.trim(); if (!message) return;
    if (taskBusy && (!voice.connected || config.voiceProvider === 'personaplex')) return;
    setDraft(''); setTyping(false); setPaused(false); setAwakened(true);
    if (config.voiceProvider === 'personaplex' && (personaplex.connected || personaplex.connecting)) {
      personaplex.disconnect(); setPreview(true); setCaption('');
    }
    if (voice.sendText(message)) return;
    transcript(crypto.randomUUID(), 'user', message, true);
    const mood = classifyMood(message); const chosen = automatic ? mood.avatar : avatar;
    if (config.backendAvailable && ['inquiry','dispute'].includes(mood.intent)) {
      setPreviewPhase('thinking');
      try { const result = await delegate(message); say(result.reply, chosen); }
      catch (e) { const message = e instanceof Error ? e.message : copy.game.signInRequired; setNotice(message); say(copy.game.waitAtPool, chosen); }
      finally { setPreviewPhase('idle'); }
    } else { setPreview(true); say(demoReply(message, chosen, locale), chosen); }
  };
  const accountChanged = useCallback((reason?: 'login' | 'logout' | 'unauthorized' | 'navigation') => {
    inquiryVoice.clear();
    personaplex.resetObserver();
    if (reason === 'unauthorized' && !bankSeen.current && !bankSessionKnown.current && !state.current.taskBusy) return;
    if (reason === 'login' && !bankSeen.current && !bankSessionKnown.current && !state.current.taskBusy) {
      native.resetAccountContext();
      bankSessionKnown.current = true; nativeBridge.current.resume(); void loadConfig(); return;
    }
    nativeBridge.current.cancel(); activeNativeRead.current?.abort.abort();
    taskEpoch.current++; taskOwner.current = null; bankSeen.current = false; setTaskBusy(false); setHistory([]); setCaption('');
    bankSessionKnown.current = reason === 'login';
    stopPreview(); realtime.disconnect(); native.disconnect(); router.disconnect(); gemini.disconnect(); personaplex.disconnect(); void loadConfig();
  }, [stopPreview, realtime.disconnect, native.disconnect, native.resetAccountContext, router.disconnect, gemini.disconnect, personaplex.disconnect, personaplex.resetObserver, loadConfig, inquiryVoice.clear]);
  const changeLocale = (next: Locale) => {
    if (next === locale || taskBusy) return;
    interrupt(); nativeBridge.current.cancel();
    realtime.disconnect(); native.disconnect(); router.disconnect(); gemini.disconnect(); personaplex.disconnect();
    realtime.clearError(); native.clearError(); router.clearError(); gemini.clearError(); personaplex.clearError();
    persistLocale(next); setLocale(next); setNotice(''); setCaption('');
    if (entered) setPreview(true);
    else setAwakened(false);
  };
  useEffect(() => {
    const keys = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement;
      if (target.closest('input,textarea')) { if (event.key === 'Escape') { setTyping(false); setPaused(false); } return; }
      if (event.key === 'Escape') { interrupt(); if (computerOpen) setComputerOpen(false); else if (chapters) setChapters(false); else if (historyOpen) setHistoryOpen(false); else setPaused(p => !p); }
      if (event.code === 'Space' && entered) { event.preventDefault(); interrupt(); }
      if (event.key.toLowerCase() === 't') { setTyping(p => !p); setPaused(false); }
      if (event.key === 'ArrowRight' && entered) travel();
      if (event.key === 'ArrowLeft' && entered) setSceneIndex(i => (i + 9) % 10);
    };
    window.addEventListener('keydown', keys); return () => window.removeEventListener('keydown', keys);
  });
  useEffect(() => () => {
    sceneEpoch.current++; taskEpoch.current++; taskOwner.current = null;
    nativeBridge.current.cancel(); activeNativeRead.current?.abort.abort();
  }, []);

  return <main className={`game story story-${avatar} ${entered ? 'game-entered' : 'game-black'} ${paused ? 'game-paused' : ''} ${computerOpen ? 'computer-visible' : ''}`} onPointerMove={event => { pointer.current.x = (event.clientX / window.innerWidth - .5) * 2; pointer.current.y = (event.clientY / window.innerHeight - .5) * 2; }}>
    {entered ? <Suspense fallback={<div className="darkness" />}><World locale={locale} avatar={avatar} sceneIndex={sceneIndex} phase={phase} audioLevel={level} reducedMotion={reducedMotion} pointer={pointer.current} /></Suspense> : <div className={`darkness ${awakened ? 'eyes-awake' : ''} ${voice.connecting && !initialListening ? 'eyes-connecting' : ''}`} style={{ '--listen-level': level } as React.CSSProperties}>
      <svg className="drawn-eyes" viewBox="0 0 190 58" aria-hidden="true"><path d="M15 32 Q 42 6 70 29" /><path d="M120 29 Q 148 6 175 32" /></svg>
      {!awakened && <button className="wake-surface" onClick={() => void wake()} aria-label={copy.ui.wakeWorld} />}
      {!awakened && (config.voiceAvailable || config.initialVoiceAvailable) && <p className="audio-provider-notice">{audioNotice}</p>}
      {awakened && !voice.connected && voice.connecting && <span className="sr-only" role="status">{initialListening ? copy.status.listening : copy.status.connectingVoice}</span>}
      {initialListening && <div className="first-listen"><span>{copy.game.firstListen}</span><button onClick={() => { personaplex.disconnect(); setAwakened(false); }} aria-label={copy.ui.stopListening}><MicOff size={14} /></button></div>}
      {voice.connected && <span className="sr-only" role="status">{voice.muted ? copy.status.microphoneMuted : copy.status.listening}</span>}
    </div>}
    {entered && !paused && <><button className={`world-hotspot character-hotspot character-hotspot-${avatar}`} aria-label={formatMessage(copy.ui.talkTo, { name: characters[avatar].name })} onClick={travel}><span className="hotspot-ring" /></button><button className={`world-hotspot pond-hotspot pond-hotspot-${avatar}`} aria-label={avatar === 'moss' ? copy.ui.lookPool : copy.ui.useComputer} onClick={() => setComputerOpen(true)}><span className="hotspot-ring" /></button><button className="pause-control" aria-label={copy.ui.pauseStory} onClick={() => { interrupt(); setPaused(true); }}><Pause size={14} /></button><div className="game-signal" aria-label={voice.connected ? voice.muted ? copy.status.microphoneMuted : copy.status.listening : preview ? copy.status.worldPreview : copy.status.voiceOffline}><span className={voice.connected && !voice.muted ? 'signal-live' : 'signal-preview'} />{voice.connected ? '' : preview ? copy.ui.preview : ''}</div></>}
    {entered && subtitles && caption && <div className="movie-subtitle" aria-live="polite">{caption}</div>}
    <div className="sr-only" aria-live="polite">{caption}</div>
    {taskBusy && <div className="quiet-work" aria-label={copy.status.saviaWorking}><span /><span /><span /></div>}

    <Workbench locale={locale} ref={workbench} avatar={avatar} open={computerOpen} mode={config.backendAvailable ? 'connected' : 'demo'} saviaUrl={config.saviaUrl} onClose={() => setComputerOpen(false)} onLoad={computerLoaded} onAccountChange={accountChanged} onInquiryUpdate={inquiryVoice.notify} />
    {paused && <div className="game-pause-overlay"><section className="game-pause-menu" aria-label={copy.ui.pauseMenu}>
      <p className="pause-title">elsewhere.</p>
      <button className="resume-game" onClick={() => setPaused(false)}><Play size={15} />{copy.ui.returnWorld}</button>
      <div className="pause-characters">{(Object.keys(AVATARS) as AvatarId[]).map(id => <button key={id} aria-label={formatMessage(copy.ui.chooseCharacter, { name: characters[id].name })} aria-pressed={avatar === id} onClick={() => pickAvatar(id)} className={avatar === id ? 'chosen' : ''}><CharacterIcon id={id} /><span>{characters[id].name}</span></button>)}</div>
      <div className="pause-options">
        {(config.voiceAvailable || config.initialVoiceAvailable) && <p className="audio-provider-notice audio-provider-notice-menu">{audioNotice}</p>}
        <div className="pause-language" role="group" aria-label={copy.ui.language}>
          <button aria-pressed={locale === 'es'} disabled={taskBusy} onClick={() => changeLocale('es')} lang="es-CO">Español{locale === 'es' && <Check size={15} />}</button>
          <button aria-pressed={locale === 'pt'} disabled={taskBusy} onClick={() => changeLocale('pt')} lang="pt-BR">Português{locale === 'pt' && <Check size={15} />}</button>
        </div>
        <button onClick={() => { setPaused(false); setChapters(true); }}>{copy.ui.wander}<ChevronRight size={15} /></button>
        <button onClick={() => { setPaused(false); setTyping(true); }}>{copy.ui.useKeyboard}<ChevronRight size={15} /></button>
        <button onClick={() => { setPaused(false); setComputerOpen(true); }}>{copy.ui.lookPool}<ChevronRight size={15} /></button>
        <button onClick={() => setAutomatic(p => !p)} aria-pressed={automatic}>{copy.ui.followPace}{automatic && <Check size={15} />}</button>
        <button onClick={ambience.toggle}>{copy.ui.worldSound}{ambience.enabled ? <Volume2 size={15} /> : <VolumeX size={15} />}</button>
        <button onClick={() => setSubtitles(p => !p)} aria-pressed={subtitles}>{copy.ui.subtitles}{subtitles && <Check size={15} />}</button>
        <button onClick={() => setReducedMotion(p => !p)} aria-pressed={reducedMotion}>{copy.ui.gentlerMotion}{reducedMotion && <Check size={15} />}</button>
        {voice.connected || voice.connecting ? <>
          {voice.connected && <button onClick={voice.toggleMute}>{voice.muted ? copy.ui.unmuteMicrophone : copy.ui.muteMicrophone}{voice.muted ? <MicOff size={15} /> : <Mic size={15} />}</button>}
          <button onClick={voice.disconnect}>{copy.ui.endVoice}<MicOff size={15} /></button>
        </> : (config.voiceAvailable || config.initialVoiceAvailable) && <button onClick={() => void startVoice()}>{copy.ui.startVoice}<Mic size={15} /></button>}
        <button onClick={() => { setPaused(false); setHistoryOpen(true); }}>{copy.ui.wordsAlongWay}<ChevronRight size={15} /></button>
      </div><span className="pause-key">{copy.ui.escapeToReturn}</span>
    </section></div>}
    {typing && <div className="keyboard-layer"><form onSubmit={event => void submit(event)} className="game-keyboard"><input autoFocus value={draft} onChange={event => setDraft(event.target.value)} placeholder="…" aria-label={copy.ui.messageCompanion} maxLength={2000} /><button type="submit" aria-label={copy.ui.sendMessage} disabled={!draft.trim() || taskBusy && (!voice.connected || config.voiceProvider === 'personaplex')}><ArrowRight size={18} /></button><button type="button" aria-label={copy.ui.closeKeyboard} onClick={() => setTyping(false)}><X size={16} /></button></form></div>}
    {chapters && <div className="game-chapters" aria-label={copy.ui.choosePlace}><button className="chapter-close" aria-label={copy.ui.closePlaces} onClick={() => setChapters(false)}><X size={18} /></button><div className="game-chapter-grid">{scenes.map((scene, i) => <button key={scene.id} className={sceneIndex === i ? 'active' : ''} onClick={() => {
      if (config.voiceProvider === 'personaplex' && (personaplex.connecting || personaplex.connected && (personaplex.voiceAvatar ?? config.voiceAvatar ?? 'moss') !== 'moss')) {
        personaplex.disconnect(); setPreview(true); setCaption('');
      }
      setAvatar('moss'); setSceneIndex(i); setEntered(true); setChapters(false);
    }} aria-label={formatMessage(copy.ui.travelTo, { place: scene.name })}><img src={scene.image} alt={scene.name} loading="lazy" /><span>{String(i + 1).padStart(2, '0')}</span></button>)}</div></div>}
    {historyOpen && <aside className="history-panel" aria-label={copy.ui.conversationTranscript}><div className="panel-heading"><h2>{copy.ui.wordsAlongWay}.</h2><button className="icon-button" aria-label={copy.ui.closeTranscript} onClick={() => setHistoryOpen(false)}><X size={18} /></button></div><div className="history-messages">{history.map(item => <article key={item.id} className={`history-message history-${item.role}`}><span>{item.role === 'user' ? copy.ui.you : item.avatar ? characters[item.avatar].name.toUpperCase() : copy.ui.companion}</span><p>{item.text}</p></article>)}</div></aside>}
    {(notice || voice.error) && <div className="game-notice" role="alert"><span>{notice || voice.error}</span><button onClick={() => { setNotice(''); voice.clearError(); }} aria-label={copy.ui.dismissNotice}><X size={14} /></button></div>}
    {entered && <button className="sr-only" onClick={interrupt}>{copy.ui.interruptCompanion}</button>}
  </main>;
}
