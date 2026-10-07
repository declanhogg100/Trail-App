import * as AppleAuthentication from 'expo-apple-authentication';
import { Alert, Image, Pressable, StyleSheet, Text, View } from 'react-native';
import { useSession } from '../src/session';
import { colors } from '../src/theme';

export default function SignInScreen() {
  const { signIn, signInDev } = useSession();

  return (
    <View style={styles.container}>
      <View style={styles.brand}>
        <Image source={require('../assets/icon.png')} style={styles.icon} />
        <Text style={styles.title}>HoggHikes</Text>
        <Text style={styles.tagline}>Find a trail. Hike it, even off the grid.</Text>
      </View>
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
    paddingHorizontal: 32,
  },
  brand: { alignItems: 'center', marginBottom: 56 },
  icon: {
    width: 88,
    height: 88,
    borderRadius: 20,
    marginBottom: 20,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: colors.border,
  },
  title: { fontSize: 30, fontWeight: '700', color: colors.text },
  tagline: {
    fontSize: 15,
    color: colors.textSecondary,
    marginTop: 8,
    textAlign: 'center',
  },
  appleButton: { width: 240, height: 46 },
  devButton: { marginTop: 20, padding: 8 },
  devButtonText: { color: colors.textMuted, fontSize: 13, textDecorationLine: 'underline' },
});
