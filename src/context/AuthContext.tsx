import {
  createContext,
  useContext,
  useState,
  useEffect,
  useCallback,
  useRef,
  ReactNode,
} from "react";
import { API_BASE } from "../services/apiBase";

export { API_BASE } from "../services/apiBase";

export interface AuthSession {
  voter_id: string;
  role: "user" | "admin" | string;
  name?: string;
  usn?: string;
  branch?: string;
  validity?: string;
  dob?: string;
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
  const sessionEpoch = useRef(0);
  const [session, setSession] = useState<AuthSession | null>(null);
  const [isCheckingSession, setIsCheckingSession] = useState(true);

  const refreshSession = useCallback(async () => {
    const epoch = sessionEpoch.current;
    try {
      const response = await fetch(`${API_BASE}/auth/refresh`, {
        method: "POST",
        credentials: "include",
      });
      if (epoch !== sessionEpoch.current) return false;
      if (!response.ok) {
        if (response.status === 401) setSession(null);
        return false;
      }

      const data = await response.json();
      setSession({
        voter_id: data.voter_id,
        role: data.role,
        name: data.name || undefined,
        usn: data.usn || undefined,
        branch: data.branch || undefined,
        validity: data.validity || undefined,
        dob: data.dob || undefined,
      });
      return true;
    } catch {
      return false;
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    const epoch = sessionEpoch.current;

    const checkSession = async () => {
      try {
        const response = await fetch(`${API_BASE}/auth/me`, {
          method: "GET",
          credentials: "include",
        });
        if (!cancelled && epoch === sessionEpoch.current && response.ok) {
          const data = await response.json();
          setSession({
            voter_id: data.voter_id,
            role: data.role,
            name: data.name || undefined,
            usn: data.usn || undefined,
            branch: data.branch || undefined,
            validity: data.validity || undefined,
            dob: data.dob || undefined,
          });
        }
      } catch {
        // A missing auth service should not prevent the public landing page from loading.
      } finally {
        if (!cancelled) setIsCheckingSession(false);
      }
    };

    void checkSession();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!session) return;
    const refreshInterval = window.setInterval(
      () => {
        void refreshSession();
      },
      10 * 60 * 1000,
    );
    return () => window.clearInterval(refreshInterval);
  }, [refreshSession, session]);

  const setAuth = useCallback((newSession: AuthSession) => {
    sessionEpoch.current += 1;
    setSession(newSession);
  }, []);

  const logout = useCallback(async () => {
    sessionEpoch.current += 1;
    try {
      await fetch(`${API_BASE}/auth/logout`, {
        method: "POST",
        credentials: "include",
      });
    } catch {
      // Clear local state even when the server is unreachable.
    } finally {
      setSession(null);
    }
  }, []);

  return (
    <AuthContext.Provider
      value={{ session, isCheckingSession, setAuth, refreshSession, logout }}
    >
      {children}
    </AuthContext.Provider>
  );
};

export const useAuth = (): AuthContextValue => {
  const context = useContext(AuthContext);
  if (!context) throw new Error("useAuth must be used inside <AuthProvider>");
  return context;
};
