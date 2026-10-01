import { Alert, Pressable, StyleSheet, Text, View } from 'react-native';
import { useSession } from '../src/session';
import { colors } from '../src/theme';

export default function SignInScreen() {
  const { signInDev } = useSession();

  return (
    <View style={styles.container}>
      <Text style={styles.title}>Trail App</Text>
      {/* expo-apple-authentication temporarily uninstalled -- see src/auth.ts.
          Apple sign-in button removed from local builds until it's reinstalled. */}
      {/* __DEV__ is a React Native global, true in Expo Go / dev builds,
          false in any production build -- this button physically cannot
          ship, so it's safe to leave in the source */}
      {__DEV__ && (
        <Pressable
          style={styles.devButton}
          onPress={async () => {
            try {
              await signInDev();
            } catch {
              Alert.alert('Sign-in failed', 'Is the backend running?');
            }
          }}
        >
          <Text style={styles.devButtonText}>Continue as test user (dev only)</Text>
        </Pressable>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: colors.background,
    alignItems: 'center',
    justifyContent: 'center',
    paddingHorizontal: 16,
  },
  title: { fontSize: 28, fontWeight: '700', marginBottom: 24, color: colors.text },
  appleButton: { width: 200, height: 44 },
  devButton: { marginTop: 16, padding: 8 },
  devButtonText: { color: colors.textMuted, fontSize: 13, textDecorationLine: 'underline' },
});
