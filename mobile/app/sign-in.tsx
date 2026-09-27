import { useState } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import * as AppleAuthentication from 'expo-apple-authentication';
import { useSession } from '../src/session';

export default function SignInScreen() {
  const { signIn, signInDev } = useSession();
  const [error, setError] = useState<string | null>(null);

  return (
    <View style={styles.container}>
      <Text style={styles.title}>Trail App</Text>
      <AppleAuthentication.AppleAuthenticationButton
        buttonType={AppleAuthentication.AppleAuthenticationButtonType.SIGN_IN}
        buttonStyle={AppleAuthentication.AppleAuthenticationButtonStyle.BLACK}
        cornerRadius={5}
        style={styles.appleButton}
        onPress={async () => {
          try {
            await signIn();
          } catch (err) {
            setError(String(err));
          }
        }}
      />
      {/* __DEV__ is a React Native global, true in Expo Go / dev builds,
          false in any production build -- this button physically cannot
          ship, so it's safe to leave in the source */}
      {__DEV__ && (
        <Pressable
          style={styles.devButton}
          onPress={async () => {
            try {
              await signInDev();
            } catch (err) {
              setError(String(err));
            }
          }}
        >
          <Text style={styles.devButtonText}>Continue as test user (dev only)</Text>
        </Pressable>
      )}
      {error && <Text style={styles.error}>{error}</Text>}
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#fff',
    alignItems: 'center',
    justifyContent: 'center',
    paddingHorizontal: 16,
  },
  title: { fontSize: 28, fontWeight: '700', marginBottom: 24 },
  error: { color: 'red', marginTop: 12 },
  appleButton: { width: 200, height: 44 },
  devButton: { marginTop: 16, padding: 8 },
  devButtonText: { color: '#999', fontSize: 13, textDecorationLine: 'underline' },
});
