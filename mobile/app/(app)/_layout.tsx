import { Pressable } from 'react-native';
import { router, Tabs } from 'expo-router';
import { FontAwesome } from '@expo/vector-icons';
import { ActiveHikeProvider } from '../../src/activeHike';
import { colors } from '../../src/theme';

export default function AppLayout() {
  return (
    // wraps the whole tab navigator, not any one screen -- so GPS tracking
    // and the timer keep running in the background if you switch tabs
    // mid-hike, rather than being torn down when the Active Hike screen
    // itself unmounts
    <ActiveHikeProvider>
      <Tabs
        screenOptions={{
          headerShown: true,
          headerStyle: { backgroundColor: colors.surface },
          headerTintColor: colors.text,
          headerShadowVisible: false,
          tabBarStyle: { backgroundColor: colors.surface, borderTopColor: colors.border },
          tabBarActiveTintColor: colors.maroonLight,
          tabBarInactiveTintColor: colors.textMuted,
        }}
      >
        <Tabs.Screen
          name="index"
          options={{
            title: 'Search',
            tabBarIcon: ({ color, size }) => <FontAwesome name="search" size={size} color={color} />,
          }}
        />
        <Tabs.Screen
          name="explore"
          options={{
            title: 'Explore',
            tabBarIcon: ({ color, size }) => <FontAwesome name="compass" size={size} color={color} />,
          }}
        />
        <Tabs.Screen
          name="liked"
          options={{
            title: 'Liked',
            tabBarIcon: ({ color, size }) => <FontAwesome name="heart" size={size} color={color} />,
          }}
        />
        <Tabs.Screen
          name="active-hike"
          options={{
            title: 'Active Hike',
            tabBarIcon: ({ color, size }) => <FontAwesome name="map-marker" size={size} color={color} />,
          }}
        />
        <Tabs.Screen
          name="hikes"
          options={{
            title: 'History',
            tabBarIcon: ({ color, size }) => <FontAwesome name="history" size={size} color={color} />,
            headerRight: () => (
              <Pressable onPress={() => router.push('/settings')} hitSlop={12} style={{ marginRight: 16 }}>
                <FontAwesome name="gear" size={22} color={colors.text} />
              </Pressable>
            ),
          }}
        />
        {/* pushed from within a tab (e.g. tapping a search or explore
            result), not itself a destination in the tab bar */}
        <Tabs.Screen name="trail/[osmId]" options={{ href: null }} />
        {/* reached via the gear icon in History's header, not a tab of its
            own -- see the headerRight above */}
        <Tabs.Screen name="settings" options={{ href: null, title: 'Settings' }} />
      </Tabs>
    </ActiveHikeProvider>
  );
}
