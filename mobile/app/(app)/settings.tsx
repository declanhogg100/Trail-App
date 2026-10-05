import { useState } from 'react';
import { ActivityIndicator, Alert, Pressable, StyleSheet, Text, View } from 'react-native';
import { deleteAccount } from '../../src/api';
import { useSession } from '../../src/session';
import { colors } from '../../src/theme';

export default function SettingsScreen() {
  const { signOut } = useSession();
  const [deleting, setDeleting] = useState(false);

  const confirmDeleteAccount = () => {
    Alert.alert(
      'Delete account?',
      'This permanently deletes your account, liked trails, and hike history. This can’t be undone.',
      [
        { text: 'Cancel', style: 'cancel' },
        { text: 'Delete', style: 'destructive', onPress: handleDeleteAccount },
      ]
    );
  };

  const handleDeleteAccount = async () => {
    setDeleting(true);
    try {
      await deleteAccount();
      // the account no longer exists server-side either way -- clear the
      // local session so the app returns to sign-in regardless
      await signOut();
    } catch {
      setDeleting(false);
      Alert.alert('Couldn’t delete account', 'Please check your connection and try again.');
    }
  };

  return (
    <View style={styles.container}>
      <Pressable style={styles.row} onPress={() => signOut()}>
        <Text style={styles.rowText}>Sign out</Text>
      </Pressable>

      <Pressable style={styles.row} onPress={confirmDeleteAccount} disabled={deleting}>
        {deleting ? (
          <ActivityIndicator color={colors.error} />
        ) : (
          <Text style={[styles.rowText, styles.dangerText]}>Delete account</Text>
        )}
      </Pressable>
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.background, paddingTop: 16 },
  row: {
    paddingVertical: 16,
    paddingHorizontal: 16,
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderColor: colors.border,
  },
  rowText: { fontSize: 16, color: colors.text },
  dangerText: { color: colors.error },
});
