import { useCallback, useEffect, useMemo, useState } from "react";
import { hasSession, clearSession } from "./api";
import { LANGS, translator } from "./i18n";
import type { Filters, Lang } from "./types";
import { EMPTY_FILTERS } from "./types";
import { ShellContext, VIEW_GLYPH, type Shell, type View } from "./ui";
import SignIn from "./views/SignIn";
import Home from "./views/Home";
import Movements from "./views/Movements";
import Insights from "./views/Insights";
import DataRoom from "./views/DataRoom";
import TxnDrawer from "./views/TxnDrawer";
import Palette from "./views/Palette";

type Toast = { id: number; message: string; tone: "ok" | "bad" };

const LANG_KEY = "savia.lang";
const THEME_KEY = "savia.theme";

export default function App() {
  const [lang, setLang] = useState<Lang>(
    () => (localStorage.getItem(LANG_KEY) as Lang) || "es");
  const [theme, setTheme] = useState<"dark" | "light">(
    () => (localStorage.getItem(THEME_KEY) as "dark" | "light") || "dark");

  const [signedIn, setSignedIn] = useState(hasSession());
  const [alias, setAlias] = useState<string>("");
  const [view, setView] = useState<View>("home");
  const [filters, setFilters] = useState<Filters>(EMPTY_FILTERS);
  const [openRef, setOpenRef] = useState<string | null>(null);
  const [palette, setPalette] = useState(false);
  const [toasts, setToasts] = useState<Toast[]>([]);

  const t = useMemo(() => translator(lang), [lang]);

  useEffect(() => {
    document.documentElement.lang = lang;
    localStorage.setItem(LANG_KEY, lang);
  }, [lang]);

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    localStorage.setItem(THEME_KEY, theme);
  }, [theme]);

  const toast = useCallback((message: string, tone: "ok" | "bad" = "ok") => {
    const id = Date.now() + Math.random();
    setToasts((list) => [...list, { id, message, tone }]);
    setTimeout(() => setToasts((list) => list.filter((item) => item.id !== id)), 4200);
  }, []);

  /* Keyboard: the palette and the theme toggle are reachable without a mouse. */
  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      const typing = /^(INPUT|TEXTAREA|SELECT)$/.test(
        (event.target as HTMLElement)?.tagName ?? "");
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setPalette((open) => !open);
        return;
      }
      if (typing) return;
      if (event.key === "/") { event.preventDefault(); setPalette(true); }
      if (event.shiftKey && event.key.toLowerCase() === "t") {
        setTheme((current) => (current === "dark" ? "light" : "dark"));
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const go = useCallback((next: View, patch?: Record<string, unknown>) => {
    if (patch) setFilters({ ...EMPTY_FILTERS, ...patch } as Filters);
    setView(next);
    window.scrollTo({ top: 0, behavior: "smooth" });
  }, []);

  const shell: Shell = useMemo(
    () => ({ lang, t, toast, openTxn: setOpenRef, go }), [lang, t, toast, go]);

  function signOut() {
    clearSession();
    setSignedIn(false);
    setAlias("");
    setView("home");
    setFilters(EMPTY_FILTERS);
    setOpenRef(null);
  }

  if (!signedIn) {
    return (
      <SignIn lang={lang} setLang={setLang}
              onSignedIn={() => { setSignedIn(true); setView("home"); }} />
    );
  }

  const tabs: View[] = ["home", "movements", "insights", "data"];

  return (
    <ShellContext.Provider value={shell}>
      <div className="app">
        <a className="skip" href="#main">{t("a11y.skip")}</a>

        <header className="topbar">
          <div className="brand">
            savia<span className="dot">.</span><span className="pro">PRO</span>
          </div>

          <nav className="tabs" aria-label={t("nav.home")}>
            {tabs.map((item) => (
              <button key={item} className="tab"
                      aria-current={view === item ? "page" : undefined}
                      onClick={() => setView(item)}>
                <span aria-hidden="true">{VIEW_GLYPH[item]}</span>
                {t(`nav.${item === "movements" ? "movements" : item === "insights" ? "insights" : item === "data" ? "data" : "home"}`)}
              </button>
            ))}
          </nav>

          <span className="spacer" />

          <button className="searchbtn" onClick={() => setPalette(true)}>
            <span aria-hidden="true">⌕</span>
            <span>{t("nav.search")}</span>
            <span className="kbd">Ctrl K</span>
          </button>

          <div className="seg" role="group" aria-label={t("gate.language")}>
            {LANGS.map((item) => (
              <button key={item.code} aria-pressed={lang === item.code}
                      onClick={() => setLang(item.code)}>{item.code.toUpperCase()}</button>
            ))}
          </div>

          <button className="iconbtn" title={t("nav.theme")} aria-label={t("nav.theme")}
                  onClick={() => setTheme(theme === "dark" ? "light" : "dark")}>
            {theme === "dark" ? "☾" : "☀"}
          </button>

          <div className="who">
            <span className="avatar" aria-hidden="true">
              {(alias || "·").split(" ").map((w) => w[0]).slice(0, 2).join("")}
            </span>
            <span>
              <span className="who-name">{alias}</span><br />
              <button className="linkbtn who-meta" onClick={signOut}>{t("nav.signOut")}</button>
            </span>
          </div>
        </header>

        <main id="main">
          {view === "home" && <Home onAlias={setAlias} />}
          {view === "movements" && <Movements filters={filters} setFilters={setFilters} />}
          {view === "insights" && <Insights />}
          {view === "data" && <DataRoom />}
        </main>

        {openRef && (
          <TxnDrawer reference={openRef} onClose={() => setOpenRef(null)} />
        )}

        {palette && (
          <Palette onClose={() => setPalette(false)}
                   onNavigate={(next) => { setPalette(false); go(next); }}
                   onOpenTxn={(reference) => { setPalette(false); setOpenRef(reference); }} />
        )}

        <div className="toasts" role="status" aria-live="polite">
          {toasts.map((item) => (
            <div key={item.id} className={`toast ${item.tone}`}>
              <b className="mark" aria-hidden="true">{item.tone === "ok" ? "✓" : "!"}</b>
              <span>{item.message}</span>
            </div>
          ))}
        </div>
      </div>
    </ShellContext.Provider>
  );
}
