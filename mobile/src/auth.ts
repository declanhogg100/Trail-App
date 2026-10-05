import * as AppleAuthentication from 'expo-apple-authentication';
import * as SecureStore from 'expo-secure-store';
import { devSignIn, setSessionToken, signInWithApple } from './api';

const SESSION_TOKEN_KEY = 'sessionToken';

// Called once on app launch -- if a session token was saved from a previous
// sign-in, restore it so the user doesn't have to sign in again every time
// the app opens. Returns whether a session was actually restored.
export async function restoreSession(): Promise<boolean> {
  const token = await SecureStore.getItemAsync(SESSION_TOKEN_KEY);
  if (token) {
    setSessionToken(token);
    return true;
  }
  return false;
}

// Runs Apple's native sign-in sheet, exchanges the resulting identity token
// for our own session token via the backend, and persists it for next launch.
export async function signIn(): Promise<void> {
  // no requestedScopes -- the backend only ever authenticates by the
  // identity token's own stable Apple user id (see api/src/api/auth.py),
  // never the person's name, so there's no reason to ask Apple for it
  const credential = await AppleAuthentication.signInAsync();

  if (!credential.identityToken) {
    throw new Error('Apple did not return an identity token');
  }

  // signInWithApple() exchanges Apple's token for our own session token,
  // and already calls setSessionToken() internally so the client is
  // authenticated immediately -- it's returned here too so it can be
  // persisted for the next app launch
  const sessionToken = await signInWithApple(credential.identityToken);
  await SecureStore.setItemAsync(SESSION_TOKEN_KEY, sessionToken);
}

export async function signOut(): Promise<void> {
  await SecureStore.deleteItemAsync(SESSION_TOKEN_KEY);
  setSessionToken(null);
}

// dev-only: skips Apple entirely, requires the backend to have
// DEV_AUTH_ENABLED set. Same persistence behavior as a real sign-in.
export async function signInDev(): Promise<void> {
  const sessionToken = await devSignIn();
  await SecureStore.setItemAsync(SESSION_TOKEN_KEY, sessionToken);
}
