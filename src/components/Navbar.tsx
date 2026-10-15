import { Link, useLocation } from "react-router-dom";
import { Chakra } from "./Chakra";
import { ArrowRight } from "lucide-react";
import { useLanguage } from "../context/LanguageContext";
import { useAuth } from "../context/AuthContext";

export default function Navbar() {
  const { setLang, t } = useLanguage();
  const { session, logout } = useAuth();
  const location = useLocation();

  return (
    <>
      <div className="tricolor-bar h-0.75 w-full" />

      {/* Top utility bar */}
      <div className="border-b border-hairline bg-paper-warm">
        <div className="mx-auto flex max-w-7xl items-center justify-between px-6 py-2 text-xs text-muted-foreground">
          <div className="flex items-center gap-3">
            <span className="font-semibold tracking-wide text-ink">
              भारत सरकार
            </span>
            <span className="text-hairline">|</span>
            <span>Government of India · Election Commission</span>
          </div>
          <div className="flex items-center gap-4">
            <button onClick={() => setLang('en')} className="font-medium text-ink hover:text-saffron">
              EN
            </button>
            <span className="text-hairline">·</span>
            <button onClick={() => setLang('hi')} className="font-hindi text-ink hover:text-saffron">
              हिंदी
            </button>
            <span className="text-hairline">·</span>
            <button onClick={() => setLang('kn')} className="font-medium text-ink hover:text-saffron">
              ಕನ್ನಡ
            </button>
            <span className="text-hairline">·</span>
            <button onClick={() => setLang('ta')} className="font-medium text-ink hover:text-saffron">
              தமிழ்
            </button>
            <span className="text-hairline">·</span>
            <button onClick={() => setLang('ml')} className="font-medium text-ink hover:text-saffron">
              മലയാളം
            </button>
            <span className="text-hairline">·</span>
            <span>Helpline 1950</span>
          </div>
        </div>
      </div>

      {/* Nav */}
      <header className="sticky top-0 z-40 border-b border-hairline bg-paper/90 backdrop-blur">
        <div className="mx-auto flex max-w-7xl items-center justify-between px-6 py-4">
          <Link to="/" className="flex items-center gap-3">
            <Chakra size={32} className="text-ashoka" />
            <div className="leading-tight">
              <div className="font-display text-lg font-semibold">
                {t('layout.title')}
              </div>
              <div className="text-[10px] uppercase tracking-[0.18em] text-muted-foreground">
                {t('layout.desc')}
              </div>
            </div>
          </Link>
          <nav className="hidden items-center gap-8 text-sm text-ink md:flex">
            <Link to="/results" className="hover:text-saffron font-medium inline-flex items-center gap-1.5 text-ashoka">
              <span className="size-2 rounded-full bg-emerald-500 animate-pulse"></span>
              Live Results
            </Link>
            {session && session.role === 'user' && (
              <Link to="/voting" className="hover:text-saffron">{t('layout.cast_vote')}</Link>
            )}
            {session && session.role === 'admin' && (
              <Link to="/admin" className="hover:text-saffron">{t('layout.admin')}</Link>
            )}
            <a href="/#how" className="hover:text-saffron">
              {t('home.how_it_works') || 'How it works'}
            </a>
            <a href="/#chain" className="hover:text-saffron">
              {t('home.verify_vote') || 'Verify vote'}
            </a>
            <a href="/#security" className="hover:text-saffron">
              {t('home.security') || 'Security'}
            </a>
            <a href="/#faq" className="hover:text-saffron">
              {t('home.about') || 'About'}
            </a>
          </nav>
          {session ? (
            <button
              onClick={() => logout()}
              className="inline-flex items-center gap-2 rounded-md bg-ink px-4 py-2 text-sm font-medium text-paper hover:bg-saffron cursor-pointer"
            >
              {t('layout.logout')} <ArrowRight className="size-4" />
            </button>
          ) : !['/login', '/admin-login'].includes(location.pathname) ? (
            <Link
              to="/login"
              className="inline-flex items-center gap-2 rounded-md bg-ink px-4 py-2 text-sm font-medium text-paper hover:bg-saffron"
            >
              {t('layout.voter_portal')} <ArrowRight className="size-4" />
            </Link>
          ) : null}
        </div>
      </header>
    </>
  );
}
