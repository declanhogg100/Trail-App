import { createContext, useContext, useEffect, useState, type PropsWithChildren } from 'react';
import {
  restoreSession,
  signIn as appleSignIn,
  signInDev as devSignIn,
  signOut as clearSession,
} from './auth';

type SessionContextValue = {
  isSignedIn: boolean;
  isLoading: boolean;
  signIn: () => Promise<void>;
  signInDev: () => Promise<void>;
  signOut: () => Promise<void>;
};

const SessionContext = createContext<SessionContextValue | null>(null);

export function SessionProvider({ children }: PropsWithChildren) {
  const [isSignedIn, setIsSignedIn] = useState(false);
  // starts true -- we don't know yet whether a saved session exists, and
  // the root layout uses this to keep the splash screen up rather than
  // flashing the sign-in screen at an already-signed-in user
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    restoreSession()
      .then(setIsSignedIn)
      .finally(() => setIsLoading(false));
  }, []);

  const signIn = async () => {
    await appleSignIn();
    setIsSignedIn(true);
  };

  const signInDev = async () => {
    await devSignIn();
    setIsSignedIn(true);
  };

  const signOut = async () => {
    await clearSession();
    setIsSignedIn(false);
  };

  return (
    <SessionContext.Provider value={{ isSignedIn, isLoading, signIn, signInDev, signOut }}>
      {children}
    </SessionContext.Provider>
  );
}

export function useSession(): SessionContextValue {
  const context = useContext(SessionContext);
  if (!context) {
    throw new Error('useSession must be used within a SessionProvider');
  }
  return context;
}
