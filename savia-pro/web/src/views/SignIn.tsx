import { useEffect, useState } from "react";
import { api } from "../api";
import { LANGS, translator } from "../i18n";
import type { Lang, Profile, Snapshot } from "../types";
import { count, percent } from "../format";
import { useCountUp } from "../motion";
import { Card, ErrorBox, Skeleton } from "../ui";

function Fact({ value, label, lang, small }: {
  value: number; label: string; lang: Lang; small?: boolean;
}) {
  const shown = useCountUp(value, 1400);
  return (
    <div className={`fact ${small ? "small" : ""}`}>
      <b>{count(Math.round(shown), lang)}</b>
      <span>{label}</span>
    </div>
  );
}

export default function SignIn(props: {
  lang: Lang; setLang: (lang: Lang) => void; onSignedIn: () => void;
}) {
  const { lang, setLang, onSignedIn } = props;
  const t = translator(lang);

  const [profiles, setProfiles] = useState<Profile[] | null>(null);
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);
  const [chosen, setChosen] = useState<string>("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let alive = true;
    setError("");
    Promise.all([api.profiles(), api.snapshot()])
      .then(([list, snap]) => {
        if (!alive) return;
        setProfiles(list);
        setSnapshot(snap);
        setChosen(list[0]?.slug ?? "");
      })
      .catch((caught) => alive && setError(caught?.message || t("err.offline")));
    return () => { alive = false; };
  }, [lang]);

  async function enter() {
    if (!chosen) return;
    setBusy(true);
    try {
      await api.signIn(chosen);
      onSignedIn();
    } catch (caught: any) {
      setError(caught?.message ?? "sign-in failed");
      setBusy(false);
    }
  }

  const totals = snapshot?.totals;

  return (
    <div className="gate">
      <div className="gate-inner">
        <header className="gate-hero reveal">
          <div className="brand">
            savia<span className="dot">.</span><span className="pro">PRO</span>
          </div>
          <h1>{t("gate.title")}</h1>
          <p className="note">{t("gate.lead")}</p>
          <div className="seg" role="group" aria-label={t("gate.language")}>
            {LANGS.map((item) => (
              <button key={item.code} aria-pressed={lang === item.code}
                      onClick={() => setLang(item.code)}>{item.label}</button>
            ))}
          </div>
        </header>

        {error && <div className="reveal" style={{ ["--i" as string]: 1 }}>
          <ErrorBox message={error} t={t} onRetry={() => setLang(lang)} />
        </div>}

        <div className="gate-cols">
          <Card index={1}>
            <div className="profiles">
              {!profiles && <Skeleton kind="row" count={5} />}
              {profiles?.map((profile, index) => (
                <button key={profile.slug} className="profile reveal"
                        style={{ ["--i" as string]: index + 2 }}
                        aria-pressed={chosen === profile.slug}
                        onClick={() => setChosen(profile.slug)}>
                  <span className="avatar" aria-hidden="true">
                    {profile.alias.split(" ").map((w) => w[0]).slice(0, 2).join("")}
                  </span>
                  <span>
                    <span className="profile-name">{profile.alias}</span>
                    <span className="profile-meta">
                      {profile.city}, {profile.country} · {profile.segment}
                      {profile.customer_status !== "Active" &&
                        <> · <b>{t(`cstatus.${profile.customer_status}`)}</b></>}
                    </span>
                    <span className="profile-note">{t(`pnote.${profile.slug}`)}</span>
                  </span>
                  <span className="profile-stats">
                    <span className="profile-stat">
                      <b className="num">{profile.transactions}</b>
                      <span>{t("gate.stat.tx")}</span>
                    </span>
                    <span className="profile-stat">
                      <b className="num">{profile.products}</b>
                      <span>{t("gate.stat.prod")}</span>
                    </span>
                  </span>
                </button>
              ))}
            </div>
            <div style={{ display: "flex", gap: 12, alignItems: "center", marginTop: 16, flexWrap: "wrap" }}>
              <button className="btn" onClick={enter} disabled={!chosen || busy}>
                {busy ? t("mov.loading") : t("gate.enter")} →
              </button>
              <p className="note" style={{ flex: "1 1 240px" }}>{t("gate.alias")}</p>
            </div>
          </Card>

          <Card title={t("gate.liveTitle")} index={2}>
            {!totals && <Skeleton kind="text" count={5} />}
            {totals && snapshot && (
              <>
                <div className="factlist">
                  <Fact value={totals.transactions} label={t("gate.txns")} lang={lang} />
                  <div className="grid g2" style={{ gap: 12 }}>
                    <Fact value={totals.customers} label={t("gate.customers")} lang={lang} small />
                    <Fact value={totals.distinct_merchant_names} label={t("gate.merchants")} lang={lang} small />
                  </div>
                </div>
                <hr className="hr" />
                <div className="meters">
                  <div className="meter is-in">
                    <div className="meter-head">
                      <span>{t("gate.noMerchant")}</span>
                      <b>{percent(snapshot.shares.no_merchant, lang)}</b>
                    </div>
                    <div className="meter-track">
                      <i className="tone-warn" style={{ ["--w" as string]: `${snapshot.shares.no_merchant * 100}%` }} />
                    </div>
                  </div>
                  <div className="meter is-in">
                    <div className="meter-head">
                      <span>{t("gate.nextDay")}</span>
                      <b>{percent(snapshot.shares.next_day_event, lang)}</b>
                    </div>
                    <div className="meter-track">
                      <i className="tone-info" style={{ ["--w" as string]: `${snapshot.shares.next_day_event * 100}%` }} />
                    </div>
                  </div>
                </div>
                <p className="note" style={{ marginTop: 14 }}>
                  <span className="mono">{snapshot.build.build_id}</span>
                </p>
              </>
            )}
          </Card>
        </div>
      </div>
    </div>
  );
}
