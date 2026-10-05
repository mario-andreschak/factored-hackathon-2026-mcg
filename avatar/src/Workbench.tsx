import { forwardRef, useEffect, useImperativeHandle, useMemo, useRef, useState } from 'react';
import { ArrowUpRight, Check, ChevronRight, MousePointer2, ShieldCheck, X } from 'lucide-react';
import type { AvatarId } from './domain';
import type { TaskReply } from './useVoice';
import { type Locale, localeTag } from './locale';
import { validInquiryNotification } from './useInquiryVoiceUpdates';

export interface WorkbenchHandle { execute: (message: string, options?: { signal?: AbortSignal }) => Promise<TaskReply>; }
interface Props { avatar: AvatarId; open: boolean; mode: 'demo' | 'connected'; saviaUrl: string; locale?: Locale; onClose: () => void; onLoad: () => void; onAccountChange?: (reason?: 'login' | 'logout' | 'unauthorized' | 'navigation') => void; onInquiryUpdate?: (caseId: string, eventId: number) => void; }
const delay = (ms: number) => new Promise(resolve => setTimeout(resolve, ms));
const spanish = {
  privacy: 'Tu cuenta se consulta después de iniciar sesión. Solo lectura.',
  connect: 'Conecta Savia para consultar tu cuenta real.',
  busy: 'Savia ya está consultando información. Espera a que termine.',
  stoppedBeforeSubmit: 'La consulta se detuvo antes de enviarse.',
  openVisible: 'Abre la ventana de Savia y mantenla visible antes de enviar tu consulta.',
  loading: 'La ventana de Savia sigue cargando. Inténtalo en un momento.',
  sessionRequestChanged: 'Tu sesión de Savia cambió. La consulta anterior no se envió.',
  keepVisible: 'Mantén visible el control de Savia antes de enviar tu consulta.',
  openingNavigation: 'Abriendo el menú de Savia',
  signIn: 'Primero inicia sesión dentro de Savia. Tu contraseña permanece en esa ventana.',
  openingAssistant: 'Abriendo el asistente de Savia',
  loadingHistory: 'Cargando tu conversación en Savia',
  historyNotReady: 'Savia sigue cargando tu conversación. Espera a que aparezca el historial antes de intentarlo.',
  processing: 'Savia ya está procesando una consulta.',
  unavailable: 'El asistente de Savia no está disponible. Revisa su estado dentro de la ventana.',
  openAssistant: 'Abre el asistente en la ventana visible de Savia antes de enviar tu consulta.',
  maxCharacters: 'Savia acepta mensajes de hasta {count} caracteres.',
  writing: 'Escribiendo tu consulta en Savia',
  cannotSend: 'Savia todavía no puede recibir mensajes. Revisa tu sesión y el estado del asistente.',
  sending: 'Enviando tu consulta',
  working: 'Savia está consultando la información',
  storyClosed: 'La ventana de la historia se cerró. Tu consulta en Savia podría completarse.',
  sessionResponseChanged: 'Tu sesión de Savia cambió. La respuesta anterior no se mostró.',
  returned: 'Savia respondió a tu consulta',
  upstreamError: 'Savia no pudo completar la consulta. Revisa el aviso en esa ventana antes de intentarlo de nuevo.',
  longRead: 'La consulta está tardando más de lo esperado. Revisa el resultado en Savia antes de volver a enviarla.',
  demoStart: 'Una demostración con datos ficticios',
  demoLooking: 'Revisando la suscripción de ejemplo',
  demoDone: 'Ejemplo revisado · no se envió ninguna consulta',
  inWorldComputer: 'Computadora del mundo',
  pool: 'El estanque de los reflejos', observatory: 'El observatorio', controlRoom: 'La sala de control',
  previewWindow: 'Una ventana a lo que podemos hacer', actualWorkspace: 'Tu espacio de Savia',
  closeComputer: 'Cerrar computadora', iframeTitle: 'Espacio bancario seguro de Savia',
  fictional: 'Ejemplo ficticio', clearer: 'Una mirada más clara.', detailPlace: 'Cada pequeño detalle tiene su lugar.',
  movements: 'Movimientos recientes', coffee: 'Café de la mañana', cloud: 'Suscripción a la nube', bookshop: 'Librería de la esquina',
  card: 'Tarjeta •• 1042', invented: 'Esta transacción es ficticia y forma parte de la escena. Conecta Savia para consultar tu propia cuenta.',
  walkingExample: 'Recorriendo el ejemplo…', watchExample: 'Ver un ejemplo',
};
const copyByLocale: Record<Locale, typeof spanish> = {
  es: spanish,
  pt: {
    privacy: 'Sua conta é consultada após entrar. Somente leitura.',
    connect: 'Conecte o Savia para consultar sua conta real.',
    busy: 'O Savia já está consultando informações. Aguarde a conclusão.',
    stoppedBeforeSubmit: 'A consulta foi interrompida antes do envio.',
    openVisible: 'Abra a janela do Savia e mantenha-a visível antes de enviar sua consulta.',
    loading: 'A janela do Savia ainda está carregando. Tente novamente em um momento.',
    sessionRequestChanged: 'Sua sessão no Savia mudou. A consulta anterior não foi enviada.',
    keepVisible: 'Mantenha o controle do Savia visível antes de enviar sua consulta.',
    openingNavigation: 'Abrindo o menu do Savia',
    signIn: 'Primeiro entre no Savia. Sua senha permanece nessa janela.',
    openingAssistant: 'Abrindo o assistente do Savia',
    loadingHistory: 'Carregando sua conversa no Savia',
    historyNotReady: 'O Savia ainda está carregando sua conversa. Aguarde o histórico aparecer antes de tentar novamente.',
    processing: 'O Savia já está processando uma consulta.',
    unavailable: 'O assistente do Savia não está disponível. Confira o status dentro da janela.',
    openAssistant: 'Abra o assistente na janela visível do Savia antes de enviar sua consulta.',
    maxCharacters: 'O Savia aceita mensagens de até {count} caracteres.',
    writing: 'Escrevendo sua consulta no Savia',
    cannotSend: 'O Savia ainda não pode receber mensagens. Confira sua sessão e o status do assistente.',
    sending: 'Enviando sua consulta',
    working: 'O Savia está consultando as informações',
    storyClosed: 'A janela da história foi fechada. Sua consulta no Savia ainda pode ser concluída.',
    sessionResponseChanged: 'Sua sessão no Savia mudou. A resposta anterior não foi exibida.',
    returned: 'O Savia respondeu à sua consulta',
    upstreamError: 'O Savia não conseguiu concluir a consulta. Confira o aviso nessa janela antes de tentar novamente.',
    longRead: 'A consulta está demorando mais que o esperado. Confira o resultado no Savia antes de enviar novamente.',
    demoStart: 'Uma demonstração com dados fictícios',
    demoLooking: 'Revisando a assinatura de exemplo',
    demoDone: 'Exemplo revisado · nenhuma consulta foi enviada',
    inWorldComputer: 'Computador do mundo',
    pool: 'O lago dos reflexos', observatory: 'O observatório', controlRoom: 'A sala de controle',
    previewWindow: 'Uma janela para o que podemos fazer', actualWorkspace: 'Seu espaço no Savia',
    closeComputer: 'Fechar computador', iframeTitle: 'Espaço bancário seguro do Savia',
    fictional: 'Exemplo fictício', clearer: 'Uma visão mais clara.', detailPlace: 'Cada pequeno detalhe tem seu lugar.',
    movements: 'Movimentações recentes', coffee: 'Café de manhã', cloud: 'Assinatura na nuvem', bookshop: 'Livraria da esquina',
    card: 'Cartão •• 1042', invented: 'Esta transação é fictícia e faz parte da cena. Conecte o Savia para consultar sua própria conta.',
    walkingExample: 'Percorrendo o exemplo…', watchExample: 'Ver um exemplo',
  },
};
const demoRows = [
  { name: 'coffee', date: '2026-10-01T00:00:00Z', amount: -4.50 },
  { name: 'cloud', date: '2026-09-30T00:00:00Z', amount: -24.00 },
  { name: 'bookshop', date: '2026-09-29T00:00:00Z', amount: -18.75 },
] as const;

export default forwardRef<WorkbenchHandle, Props>(function Workbench({ avatar, open, mode, saviaUrl, locale = 'es', onClose, onLoad, onAccountChange, onInquiryUpdate }, ref) {
  const copy = copyByLocale[locale];
  const dateFormat = useMemo(() => new Intl.DateTimeFormat(localeTag(locale), { day: 'numeric', month: 'short', timeZone: 'UTC' }), [locale]);
  const amountFormat = useMemo(() => new Intl.NumberFormat(localeTag(locale), { style: 'currency', currency: 'USD' }), [locale]);
  const frame = useRef<HTMLIFrameElement>(null);
  const surface = useRef<HTMLElement>(null);
  const isOpen = useRef(open); isOpen.current = open;
  const mounted = useRef(true);
  const busy = useRef(false);
  const accountEpoch = useRef(0);
  const loadedOnce = useRef(false);
  const [computerInitialized, setComputerInitialized] = useState(false);
  const accountCallback = useRef(onAccountChange); accountCallback.current = onAccountChange;
  const inquiryCallback = useRef(onInquiryUpdate); inquiryCallback.current = onInquiryUpdate;
  const [cursor, setCursor] = useState({ x: 50, y: 60, active: false });
  const [step, setStep] = useState<keyof typeof spanish>('privacy');
  const [demoSelected, setDemoSelected] = useState(-1);
  const [demoRunning, setDemoRunning] = useState(false);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  useEffect(() => { if (open && mode === 'connected' && saviaUrl) setComputerInitialized(true); }, [open, mode, saviaUrl]);
  useEffect(() => {
    const update = (event: MessageEvent) => {
      if (event.source !== frame.current?.contentWindow || event.origin !== window.location.origin || !validInquiryNotification(event.data)) return;
      inquiryCallback.current?.(event.data.case_id, event.data.event_id);
    };
    window.addEventListener('message', update);
    return () => window.removeEventListener('message', update);
  }, []);

  useImperativeHandle(ref, () => ({
    async execute(message: string, options = {}) {
      if (mode !== 'connected' || !saviaUrl) throw new Error(copy.connect);
      if (busy.current) throw new Error(copy.busy);
      const assertBeforeSubmit = () => {
        if (options.signal?.aborted) throw new Error(copy.stoppedBeforeSubmit);
        const computer = surface.current, rect = computer?.getBoundingClientRect();
        const style = computer ? window.getComputedStyle(computer) : undefined;
        if (!mounted.current || !isOpen.current || !computer?.isConnected || computer.inert ||
            !rect?.width || !rect.height || rect.right <= 0 || rect.bottom <= 0 || rect.left >= window.innerWidth || rect.top >= window.innerHeight ||
            style?.display === 'none' || style?.visibility === 'hidden' || Number(style?.opacity) === 0) {
          throw new Error(copy.openVisible);
        }
      };
      assertBeforeSubmit();
      busy.current = true;
      const epoch = accountEpoch.current;
      try {
        let doc: Document | null = null;
        for (let i = 0; i < 40; i++) {
          assertBeforeSubmit();
          doc = frame.current?.contentDocument ?? null;
          if (doc?.querySelector('button')) break;
          await delay(100);
        }
        if (!doc) throw new Error(copy.loading);
        const assertCurrent = () => {
          if (epoch !== accountEpoch.current || frame.current?.contentDocument !== doc) throw new Error(copy.sessionRequestChanged);
          assertBeforeSubmit();
        };
        const visible = (el: HTMLElement) => {
          const rect = el.getBoundingClientRect();
          const style = doc!.defaultView!.getComputedStyle(el);
          return rect.width > 0 && rect.height > 0 && rect.right > 0 && rect.bottom > 0 &&
            rect.left < (frame.current?.clientWidth ?? 0) && rect.top < (frame.current?.clientHeight ?? 0) &&
            style.visibility !== 'hidden' && style.display !== 'none' && Number(style.opacity) !== 0;
        };
        const moveTo = async (el: HTMLElement, label: keyof typeof spanish) => {
          assertCurrent();
          const rect = el.getBoundingClientRect();
          const width = frame.current?.clientWidth || 1, height = frame.current?.clientHeight || 1;
          setStep(label); setCursor({ x: (rect.x + rect.width / 2) / width * 100, y: (rect.y + rect.height / 2) / height * 100, active: true });
          await delay(420);
          assertCurrent();
          if (!visible(el)) throw new Error(copy.keepVisible);
        };
        let input = doc.querySelector<HTMLInputElement>('input[aria-label="Mensaje para el asistente"]');
        if (!input) {
          const findLaunch = () => [...doc!.querySelectorAll('button')].find(b => /Hablemos|Estado del asistente|Asistente|Assistente/.test(b.textContent ?? '') && visible(b));
          let launch = findLaunch();
          if (!launch) {
            const menu = [...doc.querySelectorAll('button')].find(b => /Abrir men[uú]|Open menu/i.test(`${b.getAttribute('aria-label') ?? ''} ${b.textContent ?? ''}`) && visible(b));
            if (menu) {
              await moveTo(menu, 'openingNavigation'); assertCurrent(); menu.click();
              for (let i = 0; i < 20 && !launch; i++) { await delay(100); assertCurrent(); launch = findLaunch(); }
            }
          }
          if (!launch) throw new Error(copy.signIn);
          await moveTo(launch, 'openingAssistant'); assertCurrent(); launch.click(); await delay(250); assertCurrent();
          input = doc.querySelector<HTMLInputElement>('input[aria-label="Mensaje para el asistente"]');
        }
        const loadingHistory = () => /Recuperando tu conversaci[oó]n/i.test(doc!.querySelector('.chat-thinking')?.textContent ?? '');
        // Savia uses this spinner for both history retrieval and active worker
        // requests. History is safe to await; an admitted inquiry stays exclusive.
        for (let i = 0; i < 100 && loadingHistory(); i++) {
          setStep('loadingHistory');
          await delay(200); assertCurrent();
        }
        assertCurrent();
        if (loadingHistory()) throw new Error(copy.historyNotReady);
        if (doc.querySelector('.chat-thinking')) throw new Error(copy.processing);
        input = doc.querySelector<HTMLInputElement>('input[aria-label="Mensaje para el asistente"]');
        if (!input) throw new Error(copy.unavailable);
        if (!visible(input)) throw new Error(copy.openAssistant);
        if (message.length > input.maxLength && input.maxLength > 0) throw new Error(copy.maxCharacters.replace('{count}', new Intl.NumberFormat(localeTag(locale)).format(input.maxLength)));
        const existing = [...doc.querySelectorAll('.chat-message.assistant')];
        const oldCount = existing.length;
        await moveTo(input, 'writing'); input.focus();
        const ownerWindow = frame.current!.contentWindow! as Window & typeof globalThis;
        const setter = Object.getOwnPropertyDescriptor(ownerWindow.HTMLInputElement.prototype, 'value')?.set;
        assertCurrent(); setter?.call(input, message); input.dispatchEvent(new Event('input', { bubbles: true }));
        await delay(100);
        assertCurrent();
        const send = doc.querySelector<HTMLButtonElement>('button[aria-label="Enviar mensaje"]');
        if (!send || send.disabled || !visible(send)) throw new Error(copy.cannotSend);
        await moveTo(send, 'sending'); assertCurrent();
        if (send.disabled || !visible(send)) throw new Error(copy.cannotSend);
        send.click();
        setStep('working');
        // The click admits the read. Later close/voice aborts stop no bank work.
        // Observe the real UI. No invented cursor trace, tool result, or account data.
        for (let i = 0; i < 2400; i++) {
          await delay(200);
          if (!mounted.current) throw new Error(copy.storyClosed);
          if (epoch !== accountEpoch.current || frame.current?.contentDocument !== doc) throw new Error(copy.sessionResponseChanged);
          const messages = [...doc.querySelectorAll('.chat-message.assistant')];
          const latest = messages.at(-1);
          if (messages.length > oldCount && latest?.textContent?.trim() && !doc.querySelector('.chat-thinking')) {
            // Savia renders speaker labels and Markdown separately. Preserve its
            // original response for the server's exact, owned receipt match.
            const reply = latest.getAttribute('data-savia-reply') ?? latest.textContent.trim();
            setStep('returned'); setCursor(p => ({ ...p, active: false }));
            return { reply, mode: 'flujo', status: 'completed' };
          }
          const error = doc.querySelector('[role="alert"]');
          if (error?.textContent?.trim() && !doc.querySelector('.chat-thinking')) throw new Error(copy.upstreamError);
        }
        throw new Error(copy.longRead);
      } finally { busy.current = false; setCursor(p => ({ ...p, active: false })); }
    },
  }), [mode, saviaUrl, locale, copy]);

  const frameLoaded = () => {
    if (loadedOnce.current) { accountEpoch.current++; accountCallback.current?.('navigation'); }
    loadedOnce.current = true;
    const owner = frame.current?.contentWindow;
    if (owner) {
      const original = owner.fetch.bind(owner);
      owner.fetch = async (input, init) => {
        const target = new URL(typeof input === 'string' ? input : input instanceof URL ? input.href : input.url, owner.location.href);
        const method = (init?.method ?? (typeof input === 'object' && 'method' in input ? input.method : 'GET')).toUpperCase();
        const logout = method === 'POST' && target.pathname === '/savia/api/auth/logout';
        if (logout) { accountEpoch.current++; accountCallback.current?.('logout'); }
        const response = await original(input, init);
        if (!logout && (response.status === 401 && target.pathname.startsWith('/savia/api/') || method === 'POST' && ['/savia/api/auth/login', '/savia/api/auth/invite'].includes(target.pathname) && response.ok)) {
          accountEpoch.current++; accountCallback.current?.(response.status === 401 ? 'unauthorized' : 'login');
        }
        return response;
      };
    }
    onLoad();
  };
  const runDemo = async () => {
    if (demoRunning) return;
    setDemoRunning(true); setStep('demoStart');
    setCursor({ x: 28, y: 42, active: true }); await delay(650);
    if (!mounted.current) return;
    setDemoSelected(1); setStep('demoLooking');
    setCursor({ x: 73, y: 72, active: true }); await delay(900);
    if (!mounted.current) return;
    setStep('demoDone'); setCursor(p => ({ ...p, active: false })); setDemoRunning(false);
  };
  return <aside ref={surface} className={`workbench ${open ? 'workbench-open' : ''} workbench-${avatar}`} lang={localeTag(locale)} aria-label={copy.inWorldComputer} aria-hidden={!open} inert={!open}>
    <div className="workbench-top"><div className="pool-icon">◌</div><div><p className="eyebrow">{(avatar === 'moss' ? copy.pool : avatar === 'orbit' ? copy.observatory : copy.controlRoom).toLocaleUpperCase(localeTag(locale))}</p><span>{mode === 'demo' ? copy.previewWindow : copy.actualWorkspace}</span></div><button className="icon-button" aria-label={copy.closeComputer} onClick={onClose}><X size={18} /></button></div>
    <div className="computer-surface">
      {mode === 'connected' && saviaUrl ? computerInitialized ? <iframe ref={frame} title={copy.iframeTitle} src={saviaUrl} onLoad={frameLoaded} sandbox="allow-same-origin allow-scripts allow-forms" referrerPolicy="same-origin" /> : <div className="computer-wait" /> : <div className="demo-bank">
        <div className="demo-bank-header"><span className="savia-wordmark">savia<span>↗</span></span><span className="sample-pill">{copy.fictional.toLocaleUpperCase(localeTag(locale))}</span></div>
        <div className="demo-bank-intro"><p>{copy.clearer}</p><span>{copy.detailPlace}</span></div>
        <p className="demo-label">{copy.movements.toLocaleUpperCase(localeTag(locale))}</p>
        {demoRows.map((row, i) => <button key={row.name} className={`demo-row ${demoSelected === i ? 'selected' : ''}`} onClick={() => setDemoSelected(i)}><span className="demo-row-icon">{i === 0 ? '☕' : i === 1 ? '↗' : '✧'}</span><span><strong>{copy[row.name]}</strong><small>{dateFormat.format(new Date(row.date))} · {copy.card}</small></span><span className="amount">{amountFormat.format(row.amount)}</span><ChevronRight size={14} /></button>)}
        {demoSelected >= 0 && <div className="demo-detail"><Check size={16} /><div><strong>{copy[demoRows[demoSelected].name]}</strong><p>{copy.invented}</p></div></div>}
        <button className="demo-review" onClick={() => void runDemo()} disabled={demoRunning}><MousePointer2 size={15} />{demoRunning ? copy.walkingExample : copy.watchExample}<ArrowUpRight size={15} /></button>
      </div>}
      {cursor.active && <div className="agent-cursor" style={{ left: `${cursor.x}%`, top: `${cursor.y}%` }}><MousePointer2 size={24} fill="currentColor" /><span>{avatar === 'moss' ? 'Moss' : avatar === 'orbit' ? 'Orbit' : 'Spark'}</span></div>}
    </div>
    <div className="workbench-footer"><ShieldCheck size={14} /><span>{copy[step]}</span><span className="workbench-dot" /></div>
  </aside>;
});
