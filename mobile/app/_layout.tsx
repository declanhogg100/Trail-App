import { useEffect } from 'react';
import { Stack } from 'expo-router';
import * as SplashScreen from 'expo-splash-screen';
import { SessionProvider, useSession } from '../src/session';

SplashScreen.preventAutoHideAsync();

function RootNavigator() {
  const { isSignedIn, isLoading } = useSession();

  useEffect(() => {
    if (!isLoading) {
      SplashScreen.hideAsync();
    }
  }, [isLoading]);

  // keep the splash screen up rather than rendering anything while we're
  // still checking SecureStore for a saved session
  if (isLoading) {
    return null;
  }

  return (
    <Stack screenOptions={{ headerShown: false }}>
      <Stack.Protected guard={isSignedIn}>
        <Stack.Screen name="(app)" />
      </Stack.Protected>
      <Stack.Protected guard={!isSignedIn}>
        <Stack.Screen name="sign-in" />
      </Stack.Protected>
    </Stack>
  );
}

export default function RootLayout() {
  return (
    <SessionProvider>
      <RootNavigator />
    </SessionProvider>
  );
}
