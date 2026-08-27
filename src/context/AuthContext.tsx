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

export interface AuthSession {
  voter_id: string;
  role: 'user' | 'admin' | string;
}

interface AuthContextValue {
  session: AuthSession | null;
  isCheckingSession: boolean;
  setAuth: (session: AuthSession) => void;
  refreshSession: () => Promise<boolean>;
  logout: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | undefined>(undefined);

export const AuthProvider = ({ children }: { children: ReactNode }) => {
  const [session, setSession] = useState<AuthSession | null>(null);
  const [isCheckingSession, setIsCheckingSession] = useState(true);

  const refreshSession = useCallback(async () => {
    try {
      const response = await fetch(`${API_BASE}/auth/refresh`, {
        method: 'POST',
        credentials: 'include',
      });
      if (!response.ok) return false;

      const data = await response.json();
      setSession({ voter_id: data.voter_id, role: data.role });
      return true;
    } catch {
      return false;
    }
  }, []);

  useEffect(() => {
    let cancelled = false;

    const checkSession = async () => {
      try {
        const response = await fetch(`${API_BASE}/auth/me`, {
          method: 'GET',
          credentials: 'include',
        });
        if (!cancelled && response.ok) {
          const data = await response.json();
          setSession({ voter_id: data.voter_id, role: data.role });
        }
      } catch {
        // A missing auth service should not prevent the public landing page from loading.
      } finally {
        if (!cancelled) setIsCheckingSession(false);
      }
    };

    void checkSession();
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    if (!session) return;
    const refreshInterval = window.setInterval(() => {
      void refreshSession();
    }, 10 * 60 * 1000);
    return () => window.clearInterval(refreshInterval);
  }, [refreshSession, session]);

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
      // Clear local state even when the server is unreachable.
    } finally {
      setSession(null);
    }
  }, []);

  return (
    <AuthContext.Provider value={{ session, isCheckingSession, setAuth, refreshSession, logout }}>
      {children}
    </AuthContext.Provider>
  );
};

export const useAuth = (): AuthContextValue => {
  const context = useContext(AuthContext);
  if (!context) throw new Error('useAuth must be used inside <AuthProvider>');
  return context;
};
