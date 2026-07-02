import {
  createContext,
  useContext,
  useState,
  useEffect,
  useCallback,
  ReactNode,
} from 'react';

export const API_BASE =
  import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8000/api/v1';

// ─── Types ────────────────────────────────────────────────────────────────────

export interface AuthSession {
  voter_id: string;
  role: 'user' | 'admin' | string;
}

interface AuthContextValue {
  /** Null while the initial /auth/me check is in-flight or not authenticated. */
  session: AuthSession | null;
  /** True only while the initial session-restore fetch is pending. */
  isCheckingSession: boolean;
  /** Call after a successful /verify-face response to populate the session. */
  setAuth: (session: AuthSession) => void;
  /** Calls POST /auth/logout to clear the HttpOnly cookie, then clears local state. */
  logout: () => Promise<void>;
}

// ─── Context ──────────────────────────────────────────────────────────────────

const AuthContext = createContext<AuthContextValue | undefined>(undefined);

// ─── Provider ─────────────────────────────────────────────────────────────────

export const AuthProvider = ({ children }: { children: ReactNode }) => {
  const [session, setSession] = useState<AuthSession | null>(null);
  const [isCheckingSession, setIsCheckingSession] = useState(true);

  // On mount: try to restore an existing session from the HttpOnly cookie.
  useEffect(() => {
    let cancelled = false;
    const checkSession = async () => {
      try {
        const res = await fetch(`${API_BASE}/auth/me`, {
          method: 'GET',
          credentials: 'include', // send the HttpOnly cookie
        });
        if (!cancelled && res.ok) {
          const data = await res.json();
          setSession({ voter_id: data.voter_id, role: data.role });
        }
      } catch {
        // Network error or backend down — treat as unauthenticated
      } finally {
        if (!cancelled) setIsCheckingSession(false);
      }
    };
    checkSession();
    return () => { cancelled = true; };
  }, []);

  const setAuth = useCallback((newSession: AuthSession) => {
    setSession(newSession);
  }, []);

  const logout = useCallback(async () => {
    try {
      await fetch(`${API_BASE}/auth/logout`, {
        method: 'POST',
        credentials: 'include',
      });
    } catch {
      // Even if the request fails, clear client-side state
    } finally {
      setSession(null);
    }
  }, []);

  return (
    <AuthContext.Provider value={{ session, isCheckingSession, setAuth, logout }}>
      {children}
    </AuthContext.Provider>
  );
};

// ─── Hook ─────────────────────────────────────────────────────────────────────

export const useAuth = (): AuthContextValue => {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used inside <AuthProvider>');
  return ctx;
};
