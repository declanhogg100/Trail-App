import * as AppleAuthentication from 'expo-apple-authentication';
import { Alert, Pressable, StyleSheet, Text, View } from 'react-native';
import { useSession } from '../src/session';
import { colors } from '../src/theme';

export default function SignInScreen() {
  const { signIn, signInDev } = useSession();

  return (
    <View style={styles.container}>
      <Text style={styles.title}>HoggHikes</Text>
      <AppleAuthentication.AppleAuthenticationButton
        buttonType={AppleAuthentication.AppleAuthenticationButtonType.SIGN_IN}
        buttonStyle={AppleAuthentication.AppleAuthenticationButtonStyle.WHITE}
        cornerRadius={8}
        style={styles.appleButton}
        onPress={async () => {
          try {
            await signIn();
          } catch (e) {
            // the system sheet throws this specific code when the person
            // taps "Cancel" -- that's not a failure worth alerting about
            if ((e as { code?: string })?.code === 'ERR_REQUEST_CANCELED') return;
            Alert.alert('Sign-in failed', 'Please try again.');
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
